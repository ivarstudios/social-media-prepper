"""Real ExifTool round trips on every format SMP writes."""

import os

import pytest

from smp import plan
from smp.exif import ExifTool, field_value
from tests.conftest import make_image

FORMATS = ["jpg", "png", "webp", "tif", "heic"]


def read1(et, p):
    return et.read([str(p)])[os.path.normpath(str(p))]


@pytest.mark.parametrize("ext", FORMATS)
def test_write_read_undo(tmp_path, exiftool_path, ext):
    et = ExifTool(exiftool_path)
    p = make_image(tmp_path / f"Tärna ö.{ext}")
    before = read1(et, p)
    rows = [{"field": "title", "proposed": "Fjäll at dawn"},
            {"field": "caption", "proposed": "Snow, wind and a hut."},
            {"field": "alt_text", "proposed": "A red hut in snow."},
            {"field": "keywords", "proposed": ["snow", "hut", "fjäll"]},
            {"field": "creator", "proposed": ["José Muñoz"]},
            {"field": "flags", "proposed": ["minors", "text"]}]
    res = plan.write(et, str(tmp_path), {str(p): {"meta": before, "rows": rows, "model": "m", "brief": "b"}})
    assert res["written"] == 1 and not res["errors"]
    after = read1(et, p)
    assert field_value(after, "title") == "Fjäll at dawn"
    assert field_value(after, "keywords") == ["snow", "hut", "fjäll"]
    assert field_value(after, "alt_text") == "A red hut in snow."
    assert plan.owner(after, "title") == "smp" and plan.owner(after, "caption") == "smp"
    plan.undo(et, res["run_id"])
    restored = read1(et, p)
    assert field_value(restored, "title") == "" and field_value(restored, "keywords") == []
    assert not restored.get("XMP-smp:Fingerprints")


def test_jpeg_iptc_caption_is_kept_in_sync(tmp_path, exiftool_path):
    et = ExifTool(exiftool_path)
    p = make_image(tmp_path / "a.jpg")
    et.write([(str(p), ["-IPTC:Caption-Abstract=Old caption", "-XMP-dc:Description=Old caption"])])
    meta = read1(et, p)
    plan.write(et, str(tmp_path), {str(p): {"meta": meta, "rows": [{"field": "caption", "proposed": "New"}]}})
    after = read1(et, p)
    assert after.get("IPTC:Caption-Abstract") == "New" and after.get("XMP-dc:Description") == "New"


def test_gps_removed_and_restored(tmp_path, exiftool_path):
    et = ExifTool(exiftool_path)
    p = make_image(tmp_path / "g.jpg")
    et.write([(str(p), ["-GPSLatitude*=67.9", "-GPSLongitude*=18.5"])])
    meta = read1(et, p)
    res = plan.write(et, str(tmp_path), {str(p): {"meta": meta, "rows": [{"field": "gps", "proposed": ""}]}})
    assert read1(et, p).get("Composite:GPSLatitude") is None
    plan.undo(et, res["run_id"])
    assert abs(read1(et, p)["Composite:GPSLatitude"] - 67.9) < 1e-6


def test_rewriting_lists_replaces_them_and_undo_restores_them(tmp_path, exiftool_path):
    """Writing keywords to a file that already has keywords replaces the list (no duplicates), twice in a row,
    and undo puts the exact old list back."""
    et = ExifTool(exiftool_path)
    p = make_image(tmp_path / "k.jpg")
    et.write([(str(p), ["-XMP-dc:Subject=nepal", "-XMP-dc:Subject=trek, winter", "-IPTC:Keywords=nepal"])])
    before = read1(et, p)
    plan.write(et, str(tmp_path), {str(p): {"meta": before, "rows": [{"field": "keywords", "proposed": ["a", "b"]}]}})
    res = plan.write(et, str(tmp_path), {str(p): {"meta": read1(et, p),
                                                  "rows": [{"field": "keywords", "proposed": ["a", "c"]}]}})
    after = read1(et, p)
    assert field_value(after, "keywords") == ["a", "c"]
    assert after.get("IPTC:Keywords") == ["a", "c"]
    assert after.get("XMP-smp:AddedKeywords") == ["a", "c"]
    plan.undo(et, res["run_id"])
    assert field_value(read1(et, p), "keywords") == ["a", "b"]
