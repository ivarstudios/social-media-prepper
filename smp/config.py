"""Settings (per user, per PC) and the folders SMP uses.

settings.json holds only what the user chose. Anything left empty (tool paths, the local model, the Ollama address)
is worked out on every start, so a later install or a bigger GPU is picked up without editing settings.

The folders are chosen when installing and kept in locations.json in the app folder (the data folder can't hold
the record of where the data folder is): tools (uv, Python, ExifTool, Ollama), models and data. A folder that
isn't in it is the default, all inside the app folder: <app>/tools, <app>/data and <data>/ollama-models."""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "IVAR-SMP"
PKG_DIR = Path(__file__).resolve().parent
APP_DIR = PKG_DIR.parent
LOCATIONS_FILE = APP_DIR / "locations.json"
LOCATION_KEYS = ("tools", "models", "data")


def locations() -> dict:
    """The folders chosen when installing; a missing one is the default."""
    try:
        d = json.loads(LOCATIONS_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in d.items() if k in LOCATION_KEYS and isinstance(v, str) and v} if isinstance(d, dict) \
        else {}


def tools_dir() -> Path:
    return Path(locations().get("tools") or APP_DIR / "tools")


def legacy_data_dir() -> Path:
    """Where versions before 0.1.2 kept the data: in the user profile, shared by every copy of SMP."""
    return Path(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")) / APP_NAME


def data_dir() -> Path:
    chosen = os.environ.get("SMP_DATA_DIR") or locations().get("data")
    p = Path(chosen or APP_DIR / "data")
    old = legacy_data_dir()
    if not chosen and not p.exists() and old.is_dir() and any(old.iterdir()):
        p = old           # not moved yet: the installer moves it into the app folder
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> str:
    # before locations.json, the models folder was a setting
    return locations().get("models") or stored().get("ollama_models_dir") or str(data_dir() / "ollama-models")


DEFAULTS: dict = {
    # prefilled into a new brief.md; each brief can override them
    "creator": "",
    "credit": "",
    "copyright": "",
    "language": "en",
    "density": "comfortable",      # spacing in the app: comfortable, medium or tight
    # vision model
    "backend": "ollama",           # "ollama" (local) or "claude"
    "ollama_url": "",              # empty: SMP's own Ollama on port 11436 (started when needed)
    "ollama_model": "",            # empty: the best model for this GPU
    "ollama_exe": "",              # empty: tools/ollama, then PATH
    "ollama_image_px": 1024,
    "claude_model": "claude-opus-5-5",
    "claude_effort": "medium",
    "claude_image_px": 1568,
    "claude_api_key": "",          # empty: ANTHROPIC_API_KEY or an `ant auth login` profile
    "exiftool": "",                # empty: tools/exiftool, then PATH
    "port": 8765,
    "lan": "on",                   # "on": other computers on the network can open SMP too; "off": this one only
    "recent_folders": [],
}
OWN_OLLAMA_PORT = 11436


def settings_path() -> Path:
    return data_dir() / "settings.json"


def stored() -> dict:
    try:
        s = json.loads(settings_path().read_text(encoding="utf-8"))
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def load() -> dict:
    """Settings with every empty path or model filled in for this PC."""
    from smp import machine

    s = dict(DEFAULTS)
    s.update({k: v for k, v in stored().items() if k in DEFAULTS})
    s["exiftool"] = s["exiftool"] or machine.find_exiftool()
    s["ollama_exe"] = s["ollama_exe"] or machine.find_ollama()
    s["ollama_models_dir"] = models_dir()
    s["ollama_url"] = s["ollama_url"] or f"http://127.0.0.1:{OWN_OLLAMA_PORT}"
    return s


def save(changes: dict) -> dict:
    """Store the user's choices. A value equal to the default (or empty) is removed, so it's detected again."""
    s = stored()
    for k, v in changes.items():
        if k not in DEFAULTS:
            continue
        if v in ("", None) or v == DEFAULTS[k]:
            s.pop(k, None)
        else:
            s[k] = v
    settings_path().write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    return load()


def remember_folder(folder: str) -> None:
    recent = [folder] + [f for f in load().get("recent_folders", []) if f != folder]
    save({"recent_folders": recent[:12]})
