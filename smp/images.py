"""Finding images in a folder, their thumbnails and the facts SMP tells the vision model about each one."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from smp.config import data_dir
from smp.exif import WRITABLE_EXTS, as_text

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:          # HEIC files are then listed but can't be previewed
    pass

Image.MAX_IMAGE_PIXELS = None
KIND = re.compile(r"^(Carousel|360 Carousel|Panorama Carousel|Panorama|BTS|3D|Screengrabs|Extras|Event|HDR|SDR)\b")


@dataclass
class ImageFile:
    path: Path
    meta: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        st = self.path.stat()
        return hashlib.sha1(f"{self.path}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]

    @property
    def size(self) -> tuple[int, int]:
        w, h = self.meta.get("File:ImageWidth"), self.meta.get("File:ImageHeight")
        if (not w or not h) and self.meta.get("Composite:ImageSize"):
            w, h = (int(float(x)) for x in str(self.meta["Composite:ImageSize"]).split())
        if w and h and int(self.meta.get("IFD0:Orientation") or 1) in (5, 6, 7, 8):
            w, h = h, w
        return int(w or 0), int(h or 0)


def list_images(folder: Path, recursive: bool) -> list[Path]:
    folder = Path(folder)
    if not recursive:
        items = [p for p in folder.iterdir() if p.is_file()]
    else:
        items = []
        for d, dirs, files in os.walk(folder):
            dirs[:] = sorted(x for x in dirs if not x.startswith((".", "__")))
            items += [Path(d) / f for f in files]
    return sorted(p for p in items if p.suffix.lower() in WRITABLE_EXTS and not p.name.startswith("."))


def _open(path: Path, px: int) -> Image.Image:
    im = Image.open(path)
    im.draft("RGB", (px, px))
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((px, px), Image.Resampling.LANCZOS)
    return im


def thumbnail(img: ImageFile, px: int = 480) -> Path:
    out = data_dir() / "thumbs" / f"{img.key}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        _open(img.path, px).save(out, "JPEG", quality=82)
    return out


def pixel_id(img: ImageFile) -> str:
    """Identity of the picture itself: survives metadata writes, so cached answers stay valid after writing."""
    im = _open(img.path, 64)
    return hashlib.sha1(im.tobytes()).hexdigest()[:16]


def jpeg_bytes(path: Path, px: int) -> bytes:
    buf = io.BytesIO()
    _open(path, px).save(buf, "JPEG", quality=88)
    return buf.getvalue()


def jpeg_b64(path: Path, px: int) -> str:
    return base64.b64encode(jpeg_bytes(path, px)).decode("ascii")


def capture_date(meta: dict) -> str:
    for tag in ("ExifIFD:DateTimeOriginal", "XMP-photoshop:DateCreated", "ExifIFD:CreateDate", "XMP-xmp:CreateDate"):
        v = as_text(meta.get(tag))
        if v and not v.startswith("0000"):
            m = re.match(r"(\d{4})[:-](\d\d)[:-](\d\d)(?:[ T](\d\d):(\d\d))?", v)
            if m:
                y, mo, d, hh, mm = m.groups()
                try:
                    dt = datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0))
                    return dt.strftime("%Y-%m-%d %H:%M") if hh else dt.strftime("%Y-%m-%d")
                except ValueError:
                    return v[:16]
    return ""


def kind_of(folder: Path, root: Path) -> str:
    try:
        parts = folder.relative_to(root.parent).parts
    except ValueError:
        parts = folder.parts
    for part in reversed(parts):
        m = KIND.match(part)
        if m:
            return m.group(1)
    return ""


def facts(img: ImageFile, root: Path, place_label: str = "") -> list[str]:
    """Plain-language facts about the file for the prompt."""
    w, h = img.size
    shape = "square" if w and abs(w - h) <= 0.03 * max(w, h) else ("landscape" if w > h else "portrait")
    try:
        rel = img.path.parent.relative_to(root.parent)
    except ValueError:
        rel = img.path.parent
    lines = [f"Folder: {rel.as_posix()}", f"File name: {img.path.name}"]
    kind = kind_of(img.path.parent, root)
    if kind:
        lines.append(f"Folder kind: {kind}")
    if w and h:
        lines.append(f"Size: {w} x {h} px ({shape}, {w / h:.2f}:1)")
    date = capture_date(img.meta)
    if date:
        lines.append(f"Captured: {date}")
    cam = " ".join(x for x in (as_text(img.meta.get("IFD0:Make")), as_text(img.meta.get("IFD0:Model"))) if x)
    if cam:
        lines.append(f"Camera: {cam}")
    lat, lon = img.meta.get("Composite:GPSLatitude"), img.meta.get("Composite:GPSLongitude")
    if lat not in (None, "") and lon not in (None, ""):
        lines.append(f"GPS: {float(lat):.4f}, {float(lon):.4f}" + (f" ({place_label})" if place_label else ""))
    return lines
