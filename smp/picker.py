"""The operating system's own folder dialog.

A web page can't learn a folder's path from the browser's picker, but SMP's server runs on the same computer, so
it opens the native dialog itself: Finder on a Mac, zenity on Linux when installed, and Tk (which shows Windows'
own "Select Folder" dialog) everywhere else. It runs in a separate process so it never blocks or crashes the app."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

TITLE = "Choose a folder of finished images"

_TK = r"""
import sys, tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)      # in front of the browser
root.update()
path = filedialog.askdirectory(parent=root, initialdir=sys.argv[1] or None, title=sys.argv[2], mustexist=True)
root.destroy()
sys.stdout.write(path or "")
"""


def pick_folder(initial: str = "") -> str:
    """The folder the user chose, or "" when they cancelled."""
    initial = initial if initial and os.path.isdir(initial) else ""
    system = platform.system()
    if system == "Darwin":
        where = f' default location (POSIX file "{_quote(initial)}")' if initial else ""
        r = subprocess.run(["osascript", "-e", f'POSIX path of (choose folder with prompt "{TITLE}"{where})'],
                           capture_output=True, text=True)
        return r.stdout.strip().rstrip("/") if r.returncode == 0 else ""
    if system == "Linux" and shutil.which("zenity"):
        r = subprocess.run(["zenity", "--file-selection", "--directory", f"--title={TITLE}",
                            *([f"--filename={initial}/"] if initial else [])], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}      # no console window flashing up
    r = subprocess.run([sys.executable, "-c", _TK, initial, TITLE], capture_output=True, text=True,
                       encoding="utf-8", **kw)
    path = r.stdout.strip()
    return os.path.normpath(path) if path else ""


def _quote(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
