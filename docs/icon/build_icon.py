"""Build the IVAR SMP icon files from smp-icon.svg (Windows, needs Microsoft Edge for the one SVG render).

    .venv\\Scripts\\python docs\\icon\\build_icon.py

Writes docs/icon/png/smp-icon-<size>.png, docs/icon/smp-icon.ico, and the copies the app uses in smp/static/.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
STATIC = HERE.parent.parent / "smp" / "static"
SVG = HERE / "smp-icon.svg"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
RENDER_H = 2000


def edge() -> str:
    for p in (Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
              Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")):
        if p.exists():
            return str(p)
    raise SystemExit("Microsoft Edge not found")


def render() -> Image.Image:
    w = round(RENDER_H * 173.2 / 200)
    with tempfile.TemporaryDirectory() as tmp:
        page, shot = Path(tmp) / "icon.html", Path(tmp) / "icon.png"
        page.write_text(f'<!doctype html><body style="margin:0;background:transparent">'
                        f'<img src="{SVG.as_uri()}" style="display:block;width:{w}px;height:{RENDER_H}px">',
                        encoding="utf-8")
        subprocess.run([edge(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=1", "--default-background-color=00000000",
                        f"--user-data-dir={Path(tmp) / 'edge'}", f"--window-size={w},{RENDER_H}",
                        f"--screenshot={shot}", page.as_uri()], capture_output=True, timeout=60)
        img = Image.open(shot).convert("RGBA")
        img.load()
    square = Image.new("RGBA", (RENDER_H, RENDER_H), (0, 0, 0, 0))
    square.paste(img, ((RENDER_H - img.width) // 2, 0), img)
    return square


def main() -> None:
    big = render()
    (HERE / "png").mkdir(exist_ok=True)
    for s in SIZES:
        big.resize((s, s), Image.Resampling.LANCZOS).save(HERE / "png" / f"smp-icon-{s}.png")
    big.resize((256, 256), Image.Resampling.LANCZOS).save(
        HERE / "smp-icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    for name in ("smp-icon.svg", "smp-icon.ico"):
        shutil.copy(HERE / name, STATIC / name)
    for s in (32, 256):
        shutil.copy(HERE / "png" / f"smp-icon-{s}.png", STATIC / f"smp-icon-{s}.png")
    print("icon files written")


if __name__ == "__main__":
    main()
