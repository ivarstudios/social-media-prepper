"""python -m smp [FOLDER]: start IVAR SMP and open it in the browser.
python -m smp doctor: check this computer's setup (used by the installer)."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import webbrowser

from smp import __version__, config


def free_port(start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


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

    port = a.port or free_port(int(config.load().get("port") or 8765))
    url = f"http://127.0.0.1:{port}/"
    if a.folder:
        S.scan(a.folder, True)
    print(f"IVAR SMP {__version__} is running at {url}  (close this window to stop it)")
    if not a.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
