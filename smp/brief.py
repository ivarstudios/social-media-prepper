"""brief.md: what a photographer tells SMP about a folder of images.

A brief is optional YAML front matter (fixed fields, written straight into the files) plus free text (context
for the vision model). Briefs apply to subfolders: a folder's brief is every brief.md from the drive root down
to that folder, the nearest one winning for each front-matter field and all free text kept, top first."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

BRIEF_NAME = "brief.md"

# front-matter fields, in the order they are written and shown
META_FIELDS = ["set", "language", "creator", "credit", "copyright", "usage",
               "place", "city", "region", "country", "no_geotag", "sensitive"]
BOOL_FIELDS = {"no_geotag", "sensitive"}


@dataclass
class Brief:
    folder: Path
    meta: dict = field(default_factory=dict)
    body: str = ""

    @property
    def path(self) -> Path:
        return self.folder / BRIEF_NAME


def _clean_meta(meta: dict) -> dict:
    """SMP's fields tidied, in their usual order. Other fields a person added to the file are kept as they are."""
    out = {}
    for k in META_FIELDS:
        v = meta.get(k)
        if k in BOOL_FIELDS:
            if v in (True, "true", "yes", "1", 1):
                out[k] = True
        elif v not in (None, ""):
            out[k] = str(v).strip()
    out.update({k: v for k, v in meta.items() if k not in META_FIELDS and v not in (None, "")})
    return out


def parse(text: str) -> tuple[dict, str]:
    text = text.lstrip("﻿")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            try:
                meta = yaml.safe_load(text[3:end]) or {}
            except yaml.YAMLError:
                meta = {}
            body = text[end + 4:].lstrip("-").lstrip("\r\n")
            return _clean_meta(meta if isinstance(meta, dict) else {}), body.strip()
    return {}, text.strip()


def render(meta: dict, body: str) -> str:
    meta = _clean_meta(meta)
    head = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=1000).strip() if meta else ""
    parts = ["---", head, "---", ""] if head else []
    return "\n".join(parts + [body.strip(), ""])


def load(folder: Path) -> Brief | None:
    p = Path(folder) / BRIEF_NAME
    if not p.is_file():
        return None
    meta, body = parse(p.read_text(encoding="utf-8", errors="replace"))
    return Brief(Path(folder), meta, body)


def save(folder: Path, meta: dict, body: str) -> Brief:
    b = Brief(Path(folder), _clean_meta(meta), body.strip())
    b.path.write_text(render(b.meta, b.body), encoding="utf-8")
    return b


def chain(folder: Path) -> list[Brief]:
    """Every brief.md from the top of the drive down to `folder` (top first)."""
    folder = Path(folder).resolve()
    found = [load(p) for p in reversed([folder, *folder.parents])]
    return [b for b in found if b is not None]


@dataclass
class Resolved:
    """The brief that applies to one folder."""
    folder: Path
    meta: dict
    context: str                # free text of every brief in the chain, labelled by folder
    sources: list[Path]         # brief.md files used, top first
    own: bool                   # the folder has its own brief.md

    @property
    def missing(self) -> bool:
        return not self.sources

    @property
    def digest(self) -> str:
        blob = json.dumps([self.meta, self.context], sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha1(blob).hexdigest()[:12]


def resolve(folder: Path, defaults: dict | None = None) -> Resolved:
    folder = Path(folder).resolve()
    briefs = chain(folder)
    meta = _clean_meta(defaults or {})
    texts = []
    for b in briefs:
        meta.update(b.meta)
        if b.body:
            texts.append(f"[{b.folder.name}]\n{b.body}" if len(briefs) > 1 else b.body)
    return Resolved(folder, meta, "\n\n".join(texts), [b.path for b in briefs],
                    own=bool(briefs) and briefs[-1].folder == folder)
