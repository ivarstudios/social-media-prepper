"""The whole flow through the web API: scan, brief, generate, preview, write, undo."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smp import server, vlm
from smp.geo import Geocoder
from tests.conftest import FakeBackend, make_image


@pytest.fixture
def client(monkeypatch, exiftool_path, tmp_path):
    fake = FakeBackend()
    monkeypatch.setattr(vlm, "backend", lambda s, name=None: fake)
    offline = Geocoder(tmp_path / "no-geonames")
    offline.download = lambda: None                  # never fetch place names in tests
    monkeypatch.setattr(server, "geocoder", lambda: offline)
    server.S = server.Session()
    return TestClient(server.create_app()), fake


def wait_job(c):
    for _ in range(100):
        j = c.get("/api/job").json()
        if not j["running"]:
            return j
        time.sleep(0.05)
    raise AssertionError("job didn't finish")


def test_full_flow(client, tmp_path):
    c, fake = client
    root = tmp_path / "Travel"
    img = make_image(root / "2024 Summer trip" / "a.jpg")
    make_image(root / "2024 Summer trip" / "b.png", color=(10, 200, 30))
    r = c.post("/api/scan", json={"folder": str(root), "recursive": True}).json()
    summer = next(f for f in r["folders"] if f["rel"].endswith("2024 Summer trip"))
    assert summer["images"] == 2 and summer["brief"] == "missing"

    c.post("/api/brief", json={"folder": summer["path"], "meta": {"creator": "José Muñoz", "language": "en"},
                               "body": "Summer trip along the south coast, July 2024."})
    assert (Path(summer["path"]) / "brief.md").exists()
    assert c.get("/api/brief", params={"folder": summer["path"]}).json()["own"]["meta"]["creator"] == "José Muñoz"

    assert c.post("/api/generate", json={"folder": summer["path"]}).json()["started"]
    j = wait_job(c)
    assert j["done"] == 2 and j["errors"] == 0, j
    assert "south coast" in fake.calls[0][1]

    prev = c.post("/api/preview", json={"folder": summer["path"]}).json()["images"]
    assert len(prev) == 2
    fields = {r["field"] for r in prev[0]["rows"]}
    assert {"title", "caption", "alt_text", "keywords", "creator"} <= fields

    items = [{"path": i["path"], "rows": [r for r in i["rows"] if r["selected"]]} for i in prev]
    w = c.post("/api/write", json={"items": items}).json()
    assert w["written"] == 2 and not w["errors"]
    again = c.post("/api/preview", json={"folder": summer["path"]}).json()["images"]
    assert len(again) == 2 and all(i["rows"] == [] and i["done"] for i in again)   # still listed, nothing pending
    assert again[0]["current"]["caption"]                                          # showing what's in the file

    u = c.post("/api/undo", json={"run_id": w["run_id"]}).json()
    assert u["restored"] == 2
    assert c.post("/api/preview", json={"folder": summer["path"]}).json()["images"]

    t = c.get(prev[0]["thumb"])
    assert t.status_code == 200 and t.headers["content-type"] == "image/jpeg"
    assert img.exists()


def test_draft_brief(client, tmp_path):
    c, _ = client
    make_image(tmp_path / "Set" / "x.jpg")
    c.post("/api/scan", json={"folder": str(tmp_path / "Set"), "recursive": True})
    r = c.post("/api/brief/draft", json={"folder": str(tmp_path / "Set")}).json()
    assert "[check]" in r["body"]


def test_status_and_setup(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(vlm.OllamaBackend, "alive", lambda self: False)
    s = c.get("/api/status").json()
    assert {"gpu", "recommended", "ollama", "ready", "exiftool"} <= set(s)
    assert s["exiftool"] and s["ollama"]["model"]
    assert s["folders"]["models"].endswith("ollama-models") and s["folders"]["tools"] and s["folders"]["data"]
    c.post("/api/claude-key", json={"key": "sk-ant-test"})
    assert c.get("/api/status").json()["claude_key_saved"]
    settings = c.get("/api/settings").json()
    assert "claude_api_key" not in settings and "claude_api_key" in settings["_explicit"]
    c.post("/api/settings", json={"claude_api_key": "", "backend": "claude"})    # the form can't wipe the key
    assert c.get("/api/status").json()["claude_key_saved"]
    assert c.get("/favicon.ico").status_code == 200


def test_model_download_job(client, monkeypatch):
    c, _ = client

    def fake_pull(self, progress):
        progress("pulling", 50, 100)
        progress("success", 100, 100)

    monkeypatch.setattr(vlm.OllamaBackend, "pull", fake_pull)
    assert c.post("/api/model/pull", json={"model": "qwen3-vl:8b"}).json()["started"] == "qwen3-vl:8b"
    for _ in range(100):
        p = c.get("/api/status").json()["pull"]
        if not p["running"]:
            break
        time.sleep(0.05)
    assert p["status"] == "Downloaded" and p["done"] == 100 and not p["error"]


def test_pick_folder_endpoint(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(server.picker, "pick_folder", lambda initial: "D:\Photos" if initial == "D:\\" else "")
    assert c.post("/api/pick-folder", json={"initial": "D:\\"}).json() == {"path": "D:\Photos"}
    assert c.post("/api/pick-folder", json={}).json() == {"path": ""}


def test_saving_a_brief_keeps_fields_the_form_doesnt_show(client, tmp_path):
    c, _ = client
    d = tmp_path / "Set"
    d.mkdir()
    (d / "brief.md").write_text("---\ncreator: A\nnote: by hand\n---\nOld text.\n", encoding="utf-8")
    c.post("/api/brief", json={"folder": str(d), "meta": {"creator": "B"}, "body": "New text."})
    text = (d / "brief.md").read_text(encoding="utf-8")
    assert "creator: B" in text and "note: by hand" in text and "New text." in text


def test_folder_progress_for_step_dots(client, tmp_path):
    c, _ = client
    d = tmp_path / "Set"
    make_image(d / "a.jpg")
    make_image(d / "b.jpg", color=(1, 2, 3))
    c.post("/api/brief", json={"folder": str(d), "meta": {}, "body": "A set."})
    c.post("/api/scan", json={"folder": str(d), "recursive": True})
    f = c.get("/api/folders").json()["folders"][0]
    assert (f["images"], f["written"], f["pending"], f["stale"], f["brief"]) == (2, 0, 0, 0, "own")

    c.post("/api/generate", json={"folder": str(d)})
    wait_job(c)
    assert c.get("/api/folders").json()["folders"][0]["pending"] == 2        # generated, nothing written yet

    prev = c.post("/api/preview", json={"folder": str(d)}).json()["images"]
    first = prev[0]
    c.post("/api/write", json={"items": [{"path": first["path"], "rows": [r for r in first["rows"] if r["selected"]]}]})
    f = c.get("/api/folders").json()["folders"][0]
    assert (f["written"], f["pending"], f["stale"]) == (1, 1, 0)

    c.post("/api/brief", json={"folder": str(d), "meta": {}, "body": "A set, now described differently."})
    assert c.get("/api/folders").json()["folders"][0]["stale"] == 1       # written with the old brief


def test_scan_again_reads_only_that_folder(client, tmp_path):
    c, _ = client
    root = tmp_path / "Personal"
    make_image(root / "Wedding" / "a.jpg")
    make_image(root / "Wedding" / "b.jpg", color=(1, 2, 3))
    make_image(root / "Cabin" / "c.jpg")
    c.post("/api/scan", json={"folder": str(root), "recursive": True})
    wedding = next(f["path"] for f in c.get("/api/folders").json()["folders"] if f["rel"].endswith("Wedding"))
    c.post("/api/generate", json={"folder": wedding})
    wait_job(c)

    (root / "Wedding" / "b.jpg").unlink()
    make_image(root / "Wedding" / "d.jpg", color=(9, 9, 9))
    make_image(root / "Cabin" / "e.jpg", color=(9, 9, 9))           # another folder: not read again
    r = c.post("/api/rescan", json={"folder": wedding}).json()
    counts = {f["rel"].split("/")[-1]: (f["images"], f["pending"]) for f in r["folders"]}
    assert counts["Wedding"] == (2, 1) and counts["Cabin"] == (1, 0)   # a.jpg keeps its answer, d.jpg is new
    names = [i["name"] for i in c.get("/api/images", params={"folder": wedding}).json()]
    assert names == ["a.jpg", "d.jpg"]
    assert c.post("/api/rescan", json={"folder": str(tmp_path)}).status_code == 400


def test_page_is_never_served_stale(client):
    c, _ = client
    for url in ("/", "/static/app.js", "/static/app.css"):
        assert c.get(url).headers["cache-control"] == "no-cache"


def test_fix_a_detail_after_writing(client, tmp_path):
    c, _ = client
    d = tmp_path / "Set"
    make_image(d / "a.jpg")
    c.post("/api/scan", json={"folder": str(d), "recursive": True})
    c.post("/api/generate", json={"folder": str(d)})
    wait_job(c)
    img = c.post("/api/preview", json={"folder": str(d)}).json()["images"][0]
    c.post("/api/write", json={"items": [{"path": img["path"], "rows": [r for r in img["rows"] if r["selected"]]}]})

    # back later: fix the caption of just this image
    c.post("/api/write", json={"items": [{"path": img["path"], "rows": [
        {"field": "caption", "proposed": "A kayaker on Lake Gillöga at dawn.", "edited": True}]}]})
    again = c.post("/api/preview", json={"path": img["path"]}).json()["images"]
    assert len(again) == 1 and again[0]["current"]["caption"] == "A kayaker on Lake Gillöga at dawn."
    assert not [r for r in again[0]["rows"] if r["selected"]]         # nothing pending: the card shows written
    caption_row = next(r for r in again[0]["rows"] if r["field"] == "caption")
    assert caption_row["action"] == "keep"                             # the fix is now the person's text


def test_job_reports_finished_images_incrementally(client, tmp_path):
    c, _ = client
    d = tmp_path / "Set"
    a, b = make_image(d / "a.jpg"), make_image(d / "b.jpg", color=(9, 9, 9))
    c.post("/api/scan", json={"folder": str(d), "recursive": True})
    c.post("/api/generate", json={"folder": str(d)})
    j = wait_job(c)
    assert j["finished_total"] == 2 and sorted(j["finished"]) == sorted([str(a), str(b)])
    assert c.get("/api/job", params={"since": 2}).json()["finished"] == []
    assert j["current"] == "" and j["partial"] == {}


def test_generate_just_the_images_asked_for(client, tmp_path):
    c, fake = client
    d = tmp_path / "Set"
    a = make_image(d / "a.jpg")
    make_image(d / "b.jpg", color=(9, 9, 9))
    c.post("/api/scan", json={"folder": str(d), "recursive": True})
    c.post("/api/generate", json={"folder": str(d), "paths": [str(a)]})
    j = wait_job(c)
    assert (j["total"], j["done"], j["finished"]) == (1, 1, [str(a)])
    rows = {i["path"]: i["rows"] for i in c.post("/api/preview", json={"folder": str(d)}).json()["images"]}
    assert any(r["field"] == "caption" for r in rows[str(a)])
    assert not any(r["field"] == "caption" for r in rows[str(d / "b.jpg")])
