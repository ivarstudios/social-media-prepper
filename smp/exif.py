"""Reading and writing image metadata with ExifTool.

Each logical field maps to one primary XMP tag plus the older EXIF/IPTC copies some files carry. SMP always
writes the XMP tag, and updates an older copy only when the file already has one, so readers that prefer
IPTC or EXIF never see a stale value next to a new one."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from smp.config import PKG_DIR

CONFIG_FILE = PKG_DIR / "smp.exiftool.config"
READERS = min(4, os.cpu_count() or 1)          # exiftools reading metadata at once
WRITABLE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".webp"}


@dataclass(frozen=True)
class Field:
    tags: tuple[str, ...]      # primary first, then older copies
    is_list: bool = False


FIELDS: dict[str, Field] = {
    "title": Field(("XMP-dc:Title", "IPTC:ObjectName")),
    "caption": Field(("XMP-dc:Description", "IFD0:ImageDescription", "IPTC:Caption-Abstract")),
    "alt_text": Field(("XMP-iptcCore:AltTextAccessibility",)),
    "extended_description": Field(("XMP-iptcCore:ExtDescrAccessibility",)),
    "keywords": Field(("XMP-dc:Subject", "IPTC:Keywords"), is_list=True),
    "place": Field(("XMP-iptcCore:Location", "IPTC:Sub-location")),
    "city": Field(("XMP-photoshop:City", "IPTC:City")),
    "region": Field(("XMP-photoshop:State", "IPTC:Province-State")),
    "country": Field(("XMP-photoshop:Country", "IPTC:Country-PrimaryLocationName")),
    "country_code": Field(("XMP-iptcCore:CountryCode", "IPTC:Country-PrimaryLocationCode")),
    "creator": Field(("XMP-dc:Creator", "IFD0:Artist", "IPTC:By-line"), is_list=True),
    "credit": Field(("XMP-photoshop:Credit", "IPTC:Credit")),
    "copyright": Field(("XMP-dc:Rights", "IFD0:Copyright", "IPTC:CopyrightNotice")),
    # Written by earlier versions only; kept so their writes can still be read, cleaned up and undone.
    "rights_url": Field(("XMP-xmpRights:WebStatement",)),
    "usage": Field(("XMP-xmpRights:UsageTerms",)),
    "people": Field(("XMP-iptcExt:PersonInImage",), is_list=True),
    "source_type": Field(("XMP-iptcExt:DigitalSourceType",)),
    "flags": Field(("XMP-smp:Flags",), is_list=True),
    "crop_fit": Field(("XMP-smp:CropFit",), is_list=True),
    "season": Field(("XMP-smp:Season",)),
    "time_of_day": Field(("XMP-smp:TimeOfDay",)),
    "shot_type": Field(("XMP-smp:ShotType",)),
    "focal_point": Field(("XMP-smp:FocalPoint",)),
    "language": Field(("XMP-smp:Language",)),
}

SMP_TAGS = ("XMP-smp:Version", "XMP-smp:Model", "XMP-smp:BriefHash", "XMP-smp:Written",
            "XMP-smp:Fingerprints", "XMP-smp:AddedKeywords")
GPS_TAGS = ("Composite:GPSLatitude", "Composite:GPSLongitude", "Composite:GPSAltitude")
FACT_TAGS = ("ExifIFD:DateTimeOriginal", "ExifIFD:CreateDate", "XMP-photoshop:DateCreated", "XMP-xmp:CreateDate",
             "IFD0:Make", "IFD0:Model", "File:ImageWidth", "File:ImageHeight", "Composite:ImageSize",
             "IFD0:Orientation", "IFD0:Software")
READ_TAGS = tuple(t for f in FIELDS.values() for t in f.tags) + SMP_TAGS + GPS_TAGS + FACT_TAGS


def as_list(v) -> list[str]:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    return [str(v)] if str(v).strip() else []


def as_text(v) -> str:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return "" if v is None else str(v).strip()


def field_value(meta: dict, name: str):
    """Current value of a logical field: the first of its tags that has one (a list for list fields)."""
    f = FIELDS[name]
    for tag in f.tags:
        if tag in meta and meta[tag] not in (None, "", []):
            return as_list(meta[tag]) if f.is_list else as_text(meta[tag])
    return [] if f.is_list else ""


class ExifToolError(RuntimeError):
    pass


class ExifTool:
    def __init__(self, exe: str):
        if not exe or not Path(exe).exists() and not _on_path(exe):
            raise ExifToolError("ExifTool not found: set its path in Settings")
        self.exe = exe

    def _run(self, args: list[str], timeout: float = 600) -> subprocess.CompletedProcess:
        # arguments go through a UTF-8 argfile so non-ASCII paths and captions survive on Windows
        with tempfile.NamedTemporaryFile("w", suffix=".args", delete=False, encoding="utf-8") as fa:
            fa.write("\n".join(a.replace("\r", " ").replace("\n", " ") for a in args))
            argfile = fa.name
        try:
            kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
            return subprocess.run([self.exe, "-config", str(CONFIG_FILE), "-charset", "filename=utf8",
                                   "-@", argfile], capture_output=True, timeout=timeout, **kw)
        finally:
            os.unlink(argfile)

    def version(self) -> str:
        r = subprocess.run([self.exe, "-ver"], capture_output=True, text=True, timeout=30)
        return r.stdout.strip()

    def read(self, paths: list[str], on_progress=None, chunk_size: int = 100) -> dict[str, dict]:
        """{path: {"Group:Tag": value}} for the managed tags, GPS and file facts.

        Read in chunks by a few exiftools at once: faster for big folders, and on_progress(files_read_so_far)
        is called after each chunk often enough to show."""
        def read_chunk(chunk: list[str]) -> list[dict]:
            args = ["-j", "-n", "-G1", "-struct", "-charset", "utf8"] + [f"-{t}" for t in READ_TAGS] + chunk
            text = self._run(args).stdout.decode("utf-8", "replace").strip()
            return json.loads(text) if text else []

        chunks = [paths[i:i + chunk_size] for i in range(0, len(paths), chunk_size)]
        out: dict[str, dict] = {}
        done = 0
        with ThreadPoolExecutor(max_workers=min(READERS, len(chunks)) or 1) as pool:
            for chunk, rows in zip(chunks, pool.map(read_chunk, chunks)):
                for row in rows:
                    out[os.path.normpath(row.pop("SourceFile"))] = row
                done += len(chunk)
                if on_progress:
                    on_progress(done)
        return out

    def write(self, jobs: list[tuple[str, list[str]]]) -> dict[str, str]:
        """jobs: [(path, ["-TAG=value", ...])]. Returns {path: error} for files that failed ({} when all worked)."""
        errors: dict[str, str] = {}
        if not jobs:
            return errors
        args: list[str] = []
        for i, (path, assigns) in enumerate(jobs):
            args += ["-overwrite_original", "-codedcharacterset=utf8", "-charset", "utf8",
                     "-echo4", f"@@SMP {i}", *assigns, path, "-execute"]
        r = self._run(args[:-1])
        err = r.stderr.decode("utf-8", "replace")
        current = None
        for line in err.splitlines():
            if line.startswith("@@SMP "):
                current = int(line.split()[1])
            elif line.startswith("Error") and current is not None:
                errors[jobs[current][0]] = line.strip()
        return errors


def _on_path(exe: str) -> bool:
    from shutil import which

    return which(exe) is not None


def set_list(tag: str, values) -> list[str]:
    """Arguments that replace a list tag with exactly these values. ExifTool builds the new list from repeated
    -TAG=value; "-TAG=" followed by "-TAG+=value" would add to the old list instead of replacing it."""
    values = as_list(values)
    return [f"-{tag}={v}" for v in values] if values else [f"-{tag}="]


def assignments(meta: dict, changes: dict[str, object]) -> list[str]:
    """ExifTool arguments setting logical fields to new values ("" or [] clears a field)."""
    out: list[str] = []
    for name, value in changes.items():
        f = FIELDS[name]
        present = [t for t in f.tags[1:] if t in meta and meta[t] not in (None, "", [])]
        for tag in (f.tags[0], *present):
            if f.is_list:
                out += set_list(tag, value)
            else:
                out.append(f"-{tag}={as_text(value)}")
    return out


def remove_gps() -> list[str]:
    return ["-gps:all=", "-XMP-exif:GPSLatitude=", "-XMP-exif:GPSLongitude=", "-XMP-exif:GPSAltitude="]


def restore_gps(meta: dict) -> list[str]:
    out = []
    for key, tag in (("Composite:GPSLatitude", "GPSLatitude"), ("Composite:GPSLongitude", "GPSLongitude"),
                     ("Composite:GPSAltitude", "GPSAltitude")):
        if meta.get(key) not in (None, ""):
            out.append(f"-{tag}*={meta[key]}")
    return out
