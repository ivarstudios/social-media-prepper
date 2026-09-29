from smp import brief


def test_parse_and_render_round_trip():
    text = "---\nset: Alps\nlanguage: sv\nno_geotag: true\nnote: added by hand\n---\n\nThe island.\n"
    meta, body = brief.parse(text)
    assert meta == {"set": "Alps", "language": "sv", "no_geotag": True, "note": "added by hand"}
    assert body == "The island."
    assert brief.parse(brief.render(meta, body)) == (meta, body)


def test_plain_text_brief_has_no_meta():
    assert brief.parse("Just words.") == ({}, "Just words.")


def test_false_bools_dropped_and_extra_fields_kept():
    meta, _ = brief.parse("---\npeople: [Anna, Bo]\nsensitive: false\n---\nx")
    assert meta == {"people": ["Anna", "Bo"]}


def test_resolve_inherits_down_and_nearest_field_wins(tmp_path):
    top, sub = tmp_path / "Project", tmp_path / "Project" / "360 Carousel - Ridge"
    sub.mkdir(parents=True)
    brief.save(top, {"creator": "José", "language": "en"}, "Hiking trip, Norway 2021.")
    brief.save(sub, {"language": "sv"}, "Carousel slices of the first ridge.")
    r = brief.resolve(sub, {"creator": "Default", "credit": "Default credit"})
    assert r.own and not r.missing
    assert r.meta["creator"] == "José" and r.meta["language"] == "sv" and r.meta["credit"] == "Default credit"
    assert r.context.index("Hiking trip") < r.context.index("Carousel slices")


def test_missing_and_inherited(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    assert brief.resolve(tmp_path / "a" / "b").missing
    brief.save(tmp_path / "a", {}, "About a.")
    r = brief.resolve(tmp_path / "a" / "b")
    assert not r.own and not r.missing and r.context == "About a."


def test_digest_changes_with_brief(tmp_path):
    brief.save(tmp_path, {}, "One.")
    d1 = brief.resolve(tmp_path).digest
    brief.save(tmp_path, {}, "Two.")
    assert brief.resolve(tmp_path).digest != d1
