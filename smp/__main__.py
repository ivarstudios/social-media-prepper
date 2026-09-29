"""python -m smp [FOLDER]: start IVAR SMP and open it in the browser.
python -m smp doctor: check this computer's setup (used by the installer)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

from smp import __version__, config


def free_port(start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def running_at(port: int) -> bool:
    """IVAR SMP already answers on this port (started earlier, its window since closed)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/openapi.json", timeout=1) as r:
            return json.load(r).get("info", {}).get("title") == "IVAR SMP"
    except (OSError, ValueError):
        return False


def open_window(url: str) -> None:
    """A window of its own (Chrome or Edge app mode: no tabs, SMP's icon and name in the taskbar), else a
    browser tab."""
    if sys.platform == "win32":
        roots = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for sub in (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe"):
            for root in roots:
                exe = Path(root) / sub
                if root and exe.exists():
                    subprocess.Popen([str(exe), f"--app={url}", "--window-size=1440,960"])
                    return
    webbrowser.open(url)


def brand_console() -> None:
    """SMP's icon on the console window (the one that keeps the server running). Only the classic console
    has one to change; in Windows Terminal this does nothing."""
    if sys.platform != "win32":
        return
    import ctypes

    ico = Path(__file__).parent / "static" / "smp-icon.ico"
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if not hwnd or not ico.exists():
        return
    user32 = ctypes.windll.user32
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    for which, size in ((0, 16), (1, 32)):                       # WM_SETICON: ICON_SMALL, ICON_BIG
        h = user32.LoadImageW(None, str(ico), 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
        if h:
            user32.SendMessageW(hwnd, 0x80, which, h)


def doctor() -> int:
    from smp import machine
    from smp.exif import ExifTool, ExifToolError

    s = config.load()
    problems = 0
    print(f"IVAR SMP {__version__}")
    try:
        print(f"  ExifTool      {ExifTool(s['exiftool']).version()}  ({s['exiftool']})")
    except (ExifToolError, OSError):
        print("  ExifTool      MISSING: run the installer again")
        problems += 1
    g = machine.gpu()
    print(f"  GPU           {g.name or 'none found'}" + (f", {g.memory_gb} GB for models" if g.name else ""))
    rec = machine.recommended()
    installed = machine.installed_models(s["ollama_models_dir"])
    model = s["ollama_model"] or machine.pick_model(installed)
    if s["ollama_exe"]:
        print(f"  Ollama        {machine.version_of(s['ollama_exe'], ('--version',)) or '?'}  ({s['ollama_exe']})")
        ready = model in installed
        print(f"  Local model   {model}: " + ("downloaded" if ready else
                                             f"not downloaded yet (about {rec.approx_gb:g} GB, from Setup in the app)"))
    else:
        print("  Ollama        not installed: only the Claude API can be used")
    if g.memory_gb < machine.MIN_USEFUL_GB:
        print("  Note          no GPU with 8 GB or more: the local model will be very slow; the Claude API is "
              "the better choice here")
    key = bool(s.get("claude_api_key") or os.environ.get("ANTHROPIC_API_KEY"))
    print(f"  Claude API    {'key found' if key else 'no key (optional; add one in Setup)'}")
    return 1 if problems else 0


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        sys.exit(doctor())
    ap = argparse.ArgumentParser(prog="smp", description="IVAR SMP: brief-aware AI metadata for finished images")
    ap.add_argument("folder", nargs="?", help="folder to open")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    import uvicorn

    from smp.server import S, create_app

    home = a.port or int(config.load().get("port") or 8765)
    if not a.folder and running_at(home):
        print("IVAR SMP is already running: opening its window")
        if not a.no_browser:
            open_window(f"http://127.0.0.1:{home}/")
        return
    port = free_port(home)
    url = f"http://127.0.0.1:{port}/"
    brand_console()
    if a.folder:
        S.scan(a.folder, True)
    print(f"IVAR SMP {__version__} is running at {url}  (close this window to stop it)")
    if not a.no_browser:
        threading.Timer(1.2, lambda: open_window(url)).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
