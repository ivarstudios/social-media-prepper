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
    assert "Swedish" in system and "Never name people" in system
    assert "Alps hike." in user and "Glacier at sunset." in user and "2024-07-12" in user


def test_clean_removes_em_dashes_and_tidies_keywords():
    out = vlm.clean({"title": "A lake — at dawn.", "caption": "x", "alt_text": "y", "content_warning": "None.",
                     "keywords": ["Lake", "#lake", " dawn "]})
    assert out["title"] == "A lake, at dawn"
    assert out["keywords"] == ["lake", "dawn"]
    assert out["content_warning"] == ""


def test_schema_is_only_what_social_media_needs():
    schema = vlm.ImageMetadata.model_json_schema()
    assert set(schema["properties"]) == {"title", "caption", "alt_text", "keywords", "minors_visible",
                                         "content_warning"}
