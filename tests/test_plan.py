import json

from smp import plan
from smp.geo import Place

AI = {"title": "Kayaker on a lake", "caption": "A kayaker at dawn.", "alt_text": "A red kayak on still water.",
      "keywords": ["kayak", "lake"], "minors_visible": True, "content_warning": ""}


def rows_by_field(rows):
    return {r.field: r for r in rows}


def smp_meta(**fields):
    """Metadata as if SMP had written these fields itself."""
    fps = {k: plan.fingerprint(v) for k, v in fields.items()}
    meta = {"XMP-smp:Fingerprints": json.dumps(fps)}
    tags = {"title": "XMP-dc:Title", "caption": "XMP-dc:Description",
            "extended_description": "XMP-iptcCore:ExtDescrAccessibility"}
    meta.update({tags[k]: v for k, v in fields.items()})
    return meta


def test_empty_file_gets_the_social_fields_only():
    r = rows_by_field(plan.propose({}, AI, {"language": "en"}, None))
    assert set(r) == {"title", "caption", "alt_text", "keywords", "flags"}
    assert r["title"].action == "new" and r["title"].selected
    assert r["keywords"].proposed == ["kayak", "lake"]
    assert r["flags"].proposed == ["minors"]


def test_content_warning_flag():
    r = rows_by_field(plan.propose({}, {**AI, "minors_visible": False, "content_warning": "human remains"}, {}, None))
    assert r["flags"].proposed == ["warning:human remains"]
    assert "flags" not in rows_by_field(plan.propose({}, {**AI, "minors_visible": False}, {}, None))


def test_human_caption_is_kept_unless_replacing():
    meta = {"XMP-dc:Description": "Our first night on the river."}
    r = rows_by_field(plan.propose(meta, AI, {}, None))
    assert r["caption"].action == "keep" and not r["caption"].selected
    r = rows_by_field(plan.propose(meta, AI, {}, None, replace_human=True))
    assert r["caption"].action == "replace" and r["caption"].selected
    assert plan.own_text(meta) == {"caption": "Our first night on the river."}


def test_smp_written_text_is_updated():
    meta = smp_meta(title="Old AI title")
    r = rows_by_field(plan.propose(meta, AI, {}, None))
    assert r["title"].action == "update" and r["title"].selected
    assert plan.owner(meta, "title") == "smp"


def test_edited_smp_text_counts_as_human():
    meta = smp_meta(title="Old AI title")
    meta["XMP-dc:Title"] = "Old AI title, fixed by hand"
    assert plan.owner(meta, "title") == "human"


def test_keywords_keep_human_ones_and_replace_own():
    meta = {"XMP-dc:Subject": ["nepal", "old-ai"], "XMP-smp:AddedKeywords": ["old-ai"]}
    r = rows_by_field(plan.propose(meta, AI, {}, None))
    assert r["keywords"].proposed == ["nepal", "kayak", "lake"]


def test_credits_fill_empty_and_differ_only_with_override():
    b = {"creator": "José Muñoz", "copyright": "© José", "usage": "Editorial use only"}
    r = rows_by_field(plan.propose({}, None, b, None))
    assert r["creator"].action == "fill" and r["creator"].proposed == ["José Muñoz"]
    assert r["usage"].proposed == "Editorial use only"
    meta = {"XMP-dc:Creator": ["Anna Berg"]}
    r = rows_by_field(plan.propose(meta, None, b, None))
    assert r["creator"].action == "differs" and not r["creator"].selected
    r = rows_by_field(plan.propose(meta, None, b, None, override_credits=True))
    assert r["creator"].selected


def test_credit_spelled_differently_is_the_same_person():
    meta = {"XMP-dc:Creator": ["JOSE MUNOZ"], "XMP-dc:Rights": "Jose Munoz"}
    r = rows_by_field(plan.propose(meta, None, {"creator": "José Muñoz", "copyright": "© José Muñoz"}, None))
    assert "creator" not in r and "copyright" not in r


def test_location_brief_first_then_gps_and_far_towns_skipped():
    far = Place("Kiruna", "Norrbotten", "Sweden", "SE", km=40)
    r = rows_by_field(plan.propose({}, None, {"place": "Kebnekaise"}, far))
    assert r["place"].proposed == "Kebnekaise" and "city" not in r
    assert r["region"].proposed == "Norrbotten" and r["country_code"].proposed == "SE"
    r = rows_by_field(plan.propose({"XMP-photoshop:Country": "Sverige"}, None, {}, far))
    assert "country" not in r                     # never overwrites a location already in the file


def test_no_geotag_removes_gps():
    meta = {"Composite:GPSLatitude": 59.3, "Composite:GPSLongitude": 18.1}
    r = rows_by_field(plan.propose(meta, None, {"no_geotag": True}, None))
    assert r["gps"].action == "remove"


def test_old_smp_fields_are_cleaned_up_but_not_someone_elses():
    meta = smp_meta(extended_description="Old AI text")
    meta.update({"XMP-smp:Season": "winter", "XMP-smp:FocalPoint": "0.5,0.5",
                 "XMP-iptcExt:DigitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalArt"})
    r = rows_by_field(plan.propose(meta, None, {}, None))
    assert r["season"].action == "remove" and r["focal_point"].selected
    assert r["extended_description"].action == "remove"
    assert "source_type" not in r          # no SMP fingerprint: set by someone else, left alone
    args = plan.changes_for(meta, [{"field": "season", "proposed": ""},
                                   {"field": "extended_description", "proposed": ""}], "m", "d")
    assert "-XMP-smp:Season=" in args
    fps = json.loads(next(a for a in args if a.startswith("-XMP-smp:Fingerprints=")).split("=", 1)[1])
    assert "extended_description" not in fps


def test_changes_for_fingerprints_and_edits():
    rows = [{"field": "title", "proposed": "A title"}, {"field": "caption", "proposed": "Mine", "edited": True},
            {"field": "keywords", "proposed": ["a", "b"]}]
    args = plan.changes_for({}, rows, "m", "d")
    fps = json.loads(next(a for a in args if a.startswith("-XMP-smp:Fingerprints=")).split("=", 1)[1])
    assert fps == {"title": plan.fingerprint("A title")}
    assert "-XMP-smp:AddedKeywords=a" in args and "-XMP-smp:AddedKeywords=b" in args and "-XMP-dc:Title=A title" in args


def test_doubled_keywords_are_offered_once():
    meta = {"XMP-dc:Subject": ["snow", "hut", "Snow", "hut"]}
    r = rows_by_field(plan.propose(meta, None, {}, None))
    assert r["keywords"].proposed == ["snow", "hut"]
    assert "keywords" not in rows_by_field(plan.propose({"XMP-dc:Subject": ["snow", "hut"]}, None, {}, None))
