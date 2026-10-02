from smp import vlm
from tests.conftest import FakeBackend


def test_describe_uses_cache_and_context_changes_miss_it():
    be = FakeBackend()
    img = lambda px: "b64"
    a, cached = vlm.describe(be, "pix1", img, ["Folder: x"], "Brief one.", {}, "en")
    assert not cached and a["title"] == "Kayaker on a calm lake"
    _, cached = vlm.describe(be, "pix1", img, ["Folder: x"], "Brief one.", {}, "en")
    assert cached and len(be.calls) == 1
    vlm.describe(be, "pix1", img, ["Folder: x"], "Brief two.", {}, "en")
    assert len(be.calls) == 2


def test_prompt_carries_brief_own_text_and_language():
    be = FakeBackend()
    vlm.describe(be, "p", lambda px: "b", ["Captured: 2024-07-12"], "Alps hike.",
                 {"caption": "Glacier at sunset."}, "sv")
    system, user = be.calls[0]
    assert "Swedish" in system and "Never guess names" in system
    assert "Alps hike." in user and "Glacier at sunset." in user and "2024-07-12" in user


def test_clean_removes_em_dashes_and_tidies_keywords():
    out = vlm.clean({"title": "A lake — at dawn.", "caption": "x", "alt_text": "y",
                     "keywords": ["Lake", "#lake", " dawn "]})
    assert out["title"] == "A lake, at dawn"
    assert out["keywords"] == ["lake", "dawn"]


def test_schema_is_only_what_social_media_needs():
    schema = vlm.ImageMetadata.model_json_schema()
    assert set(schema["properties"]) == {"title", "caption", "alt_text", "keywords", "people_count"}


def test_clean_keeps_a_sane_people_count():
    base = {"title": "t", "caption": "c", "alt_text": "a", "keywords": []}
    assert vlm.clean({**base, "people_count": "3"})["people_count"] == 3
    assert vlm.clean({**base, "people_count": -2})["people_count"] == 0
    assert "people_count" not in vlm.clean({**base, "people_count": "a few"})
    assert "people_count" not in vlm.clean(base)              # an answer from before the count: not 0


def test_partial_fields_read_an_unfinished_answer():
    text = r'{"title": "Hiker on a ridge", "caption": "A hiker \"stands\" \u00e5 by the'
    got = vlm.partial_fields(text)
    assert got == {"title": "Hiker on a ridge", "caption": 'A hiker "stands" \u00e5 by the'}
    got = vlm.partial_fields('{"title": "T", "caption": "C", "alt_text": "A", "keywords": ["snow", "ri')
    assert got["keywords"] == ["snow", "ri"] and got["alt_text"] == "A"
    assert vlm.partial_fields(r'{"title": "Half \u00') == {"title": "Half "}      # escape not complete yet
    assert vlm.partial_fields("") == {}


def test_describe_streams_partials_then_returns_the_whole_answer():
    be = FakeBackend()
    seen = []
    ai, cached = vlm.describe(be, "px", lambda px: "b", ["Folder: x"], "Brief.", {}, "en", on_partial=seen.append)
    assert not cached and ai["caption"] == "A kayaker paddles across a calm lake at dawn."
    captions = [s.get("caption", "") for s in seen]
    assert captions[-1] == ai["caption"] and any(0 < len(c) < len(ai["caption"]) for c in captions)
    seen.clear()
    vlm.describe(be, "px", lambda px: "b", ["Folder: x"], "Brief.", {}, "en", on_partial=seen.append)
    assert seen == []                                                   # cached: nothing to stream
