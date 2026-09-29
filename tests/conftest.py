import json
import os
import shutil

import pytest
from PIL import Image

from smp import config, store


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Every test gets its own settings, cache and undo database."""
    d = tmp_path / "smp-data"
    monkeypatch.setenv("SMP_DATA_DIR", str(d))
    store._conn = None
    yield d
    if store._conn is not None:
        store._conn.close()
    store._conn = None


@pytest.fixture
def exiftool_path():
    exe = config.load()["exiftool"]
    if not exe or not (os.path.exists(exe) or shutil.which(exe)):
        pytest.skip("exiftool not installed")
    return exe


def make_image(path, size=(64, 48), color=(120, 90, 60)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


class FakeBackend:
    """Stands in for a vision model: answers from a fixed dict and records what it was asked."""
    name = "fake"
    model = "fake-vlm"
    image_px = 256

    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer or {
            "title": "Kayaker on a calm lake", "caption": "A kayaker paddles across a calm lake at dawn.",
            "alt_text": "A person in a red kayak on still water with forested hills behind.",
            "keywords": ["kayak", "lake", "dawn"], "minors_visible": False, "content_warning": ""}

    def ensure(self):
        pass

    def describe(self, system, user, image_b64, on_text=None):
        self.calls.append((system, user))
        if on_text:                                   # stream the answer's JSON a few characters at a time
            text = json.dumps(self.answer, ensure_ascii=False)
            for n in range(8, len(text) + 8, 8):
                on_text(text[:n])
        return dict(self.answer)

    def write(self, system, user, images_b64):
        self.calls.append((system, user))
        return "A kayaking trip in the archipelago [check]."
