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
    assert again == []                               # nothing left to change once written

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
