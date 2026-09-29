"""What would change in each file, and writing (and undoing) it.

Every proposed change is a row: field, current value, proposed value, action, and whether it's ticked.
Text SMP wrote carries a fingerprint in XMP-smp:Fingerprints; any other text in a field is the photographer's,
which is kept (and given to the model as context) unless the run is told to replace it."""

from __future__ import annotations

import hashlib
import json
import time
import unicodedata
from dataclasses import asdict, dataclass

from smp import __version__, store
from smp.exif import FIELDS, GPS_TAGS, SMP_TAGS, ExifTool, as_list, as_text, assignments, field_value, \
    remove_gps, restore_gps
from smp.geo import NEAR_KM, Place

# What SMP writes: only what matters when preparing images for social media.
AI_TEXT = ["title", "caption", "alt_text"]
CLASSIFY = ["flags"]                      # minors, content warning: what a posting assistant must know
CREDITS = ["creator", "credit", "copyright", "usage"]
LOCATION = ["place", "city", "region", "country", "country_code"]
# Written by earlier versions and no longer used: removed on the next write (only where SMP wrote them).
OBSOLETE_SMP = ["season", "time_of_day", "shot_type", "crop_fit", "focal_point", "language"]   # XMP-smp only
OBSOLETE_IF_OURS = ["extended_description", "source_type"]
LABELS = {"title": "Title", "caption": "Caption", "alt_text": "Alt text", "keywords": "Keywords", "flags": "Flags",
          "creator": "Creator", "credit": "Credit line", "copyright": "Copyright", "usage": "Usage terms",
          "place": "Place", "city": "City", "region": "Region", "country": "Country", "country_code": "Country code",
          "gps": "GPS position", "season": "Season (old)", "time_of_day": "Time of day (old)",
          "shot_type": "Shot type (old)", "crop_fit": "Crops that work (old)", "focal_point": "Focal point (old)",
          "language": "Language (old)", "extended_description": "Extended description (old)",
          "source_type": "Source type (old)"}


def same_text(a, b) -> bool:
    """Equal apart from case, accents and spacing ("JOSE MUNOZ" is "José Muñoz")."""
    def norm(v):
        items = v if isinstance(v, list) else [v]
        out = []
        for x in items:
            x = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode()
            out.append(" ".join(x.casefold().replace("(c)", "").split()))     # "©" is already dropped above
        return sorted(x for x in out if x)
    return norm(a) == norm(b)


def fingerprint(value) -> str:
    norm = "\n".join(sorted(x.strip().lower() for x in value)) if isinstance(value, list) else str(value).strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]


def fingerprints(meta: dict) -> dict:
    try:
        return json.loads(as_text(meta.get("XMP-smp:Fingerprints")) or "{}")
    except ValueError:
        return {}


def owner(meta: dict, name: str) -> str:
    """"empty", "smp" (written by SMP, unchanged since) or "human"."""
    cur = field_value(meta, name)
    if not cur:
        return "empty"
    return "smp" if fingerprints(meta).get(name) == fingerprint(cur) else "human"


def own_text(meta: dict) -> dict:
    """The photographer's own text in the file: context for the model."""
    out = {n: field_value(meta, n) for n in ("title", "caption", "alt_text") if owner(meta, n) == "human"}
    added = {k.lower() for k in as_list(meta.get("XMP-smp:AddedKeywords"))}
    kws = [k for k in field_value(meta, "keywords") if k.lower() not in added]
    if kws:
        out["keywords"] = kws
    return out


@dataclass
class Row:
    field: str
    label: str
    current: object
    proposed: object
    action: str        # new | update | replace | keep | fill | differs | remove
    selected: bool
    group: str         # text | keywords | classify | credits | location | gps | cleanup


def _row(field, current, proposed, action, selected, group) -> Row:
    return Row(field, LABELS[field], current, proposed, action, selected, group)


def ai_values(ai: dict) -> dict:
    flags = ["minors"] if ai.get("minors_visible") else []
    if ai.get("content_warning"):
        flags.append(f"warning:{ai['content_warning']}")
    return {"title": ai.get("title", ""), "caption": ai.get("caption", ""), "alt_text": ai.get("alt_text", ""),
            "keywords": ai.get("keywords", []), "flags": flags}


def propose(meta: dict, ai: dict | None, brief_meta: dict, place: Place | None, replace_human: bool = False,
            override_credits: bool = False) -> list[Row]:
    rows: list[Row] = []
    if ai:
        vals = ai_values(ai)
        for name in AI_TEXT:
            cur, new, who = field_value(meta, name), vals[name], owner(meta, name)
            if not new or cur == new:
                continue
            if who == "empty":
                rows.append(_row(name, cur, new, "new", True, "text"))
            elif who == "smp":
                rows.append(_row(name, cur, new, "update", True, "text"))
            else:
                rows.append(_row(name, cur, new, "replace" if replace_human else "keep", replace_human, "text"))
        cur = field_value(meta, "keywords")
        added = {k.lower() for k in as_list(meta.get("XMP-smp:AddedKeywords"))}
        human = [k for k in cur if k.lower() not in added]
        merged = human + [k for k in vals["keywords"] if k.lower() not in {h.lower() for h in human}]
        if [k.lower() for k in merged] != [k.lower() for k in cur]:
            rows.append(_row("keywords", cur, merged, "update" if cur else "new", True, "keywords"))
        cur, new = field_value(meta, "flags"), vals["flags"]
        if cur != new and (cur or new):
            rows.append(_row("flags", cur, new, "remove" if not new else "update" if cur else "new", True, "classify"))

    for name in CREDITS:
        want = brief_meta.get(name)
        if not want:
            continue
        cur = field_value(meta, name)
        want_cmp = as_list(want) if FIELDS[name].is_list else as_text(want)
        if cur == want_cmp or (cur and same_text(cur, want_cmp)):
            continue
        if not cur:
            rows.append(_row(name, cur, want_cmp, "fill", True, "credits"))
        else:
            rows.append(_row(name, cur, want_cmp, "differs", override_credits, "credits"))

    loc = {k: brief_meta.get(k, "") for k in ("place", "city", "region", "country")}
    if place:
        if place.km <= NEAR_KM:
            loc["city"] = loc["city"] or place.city
        loc["region"] = loc["region"] or place.region
        loc["country"] = loc["country"] or place.country
        if not brief_meta.get("country") or brief_meta.get("country") == place.country:
            loc["country_code"] = place.country_code
    for name in LOCATION:
        want, cur = loc.get(name, ""), field_value(meta, name)
        if want and not cur:
            rows.append(_row(name, cur, want, "fill", True, "location"))

    if brief_meta.get("no_geotag") and meta.get("Composite:GPSLatitude") not in (None, ""):
        cur = f"{meta['Composite:GPSLatitude']:.4f}, {meta['Composite:GPSLongitude']:.4f}"
        rows.append(_row("gps", cur, "", "remove", True, "gps"))

    for name in OBSOLETE_SMP + OBSOLETE_IF_OURS:
        cur = field_value(meta, name)
        if cur and (name in OBSOLETE_SMP or owner(meta, name) == "smp"):
            rows.append(_row(name, cur, [] if FIELDS[name].is_list else "", "remove", True, "cleanup"))
    return rows


# ---- writing -------------------------------------------------------------------------------------------------

def changes_for(meta: dict, rows: list[dict], model: str, brief_digest: str) -> list[str]:
    """ExifTool arguments for the ticked rows of one file. rows: [{field, proposed, edited}] (ticked only)."""
    fps = fingerprints(meta)
    added = as_list(meta.get("XMP-smp:AddedKeywords"))
    values: dict[str, object] = {}
    gps_off = False
    for r in rows:
        name, value, edited = r["field"], r["proposed"], bool(r.get("edited"))
        if name == "gps":
            gps_off = True
            continue
        values[name] = value
        if name in OBSOLETE_SMP or name in OBSOLETE_IF_OURS:
            fps.pop(name, None)
        elif name == "keywords":
            before = {k.lower() for k in field_value(meta, "keywords")} - {k.lower() for k in added}
            added = [] if edited else [k for k in as_list(value) if k.lower() not in before]
        elif name in AI_TEXT or name in CLASSIFY:
            if edited:
                fps.pop(name, None)       # the person's words now: never overwritten by a later run
            else:
                fps[name] = fingerprint(value)
    if not values and not gps_off:
        return []
    args = assignments(meta, values)
    if gps_off:
        args += remove_gps()
    args += ["-XMP-smp:Fingerprints=" + json.dumps(fps, sort_keys=True), "-XMP-smp:AddedKeywords="]
    args += [f"-XMP-smp:AddedKeywords+={k}" for k in added]
    args += [f"-XMP-smp:Version={__version__}", f"-XMP-smp:Model={model}", f"-XMP-smp:BriefHash={brief_digest}",
             "-XMP-smp:Written=" + time.strftime("%Y-%m-%dT%H:%M:%S")]
    return args


def managed_snapshot(meta: dict) -> dict:
    keep = {t for f in FIELDS.values() for t in f.tags} | set(SMP_TAGS) | set(GPS_TAGS)
    return {k: v for k, v in meta.items() if k in keep}


def write(et: ExifTool, folder: str, plans: dict[str, dict]) -> dict:
    """plans: {path: {"meta": current meta, "rows": ticked rows, "model": .., "brief": digest}}."""
    jobs = []
    for path, p in plans.items():
        args = changes_for(p["meta"], p["rows"], p.get("model", ""), p.get("brief", ""))
        if args:
            jobs.append((path, args))
    if not jobs:
        return {"run_id": None, "written": 0, "errors": {}}
    run_id = store.start_run(folder, len(jobs))
    for path, _ in jobs:
        store.snapshot(run_id, path, managed_snapshot(plans[path]["meta"]))
    errors = et.write(jobs)
    return {"run_id": run_id, "written": len(jobs) - len(errors), "errors": errors}


def undo(et: ExifTool, run_id: int) -> dict:
    snaps = store.snapshots(run_id)
    jobs = []
    for path, before in snaps.items():
        args = []
        for f in FIELDS.values():
            # the older EXIF/IPTC copies were only written when the file had them
            for tag in (f.tags[0], *(t for t in f.tags[1:] if t in before)):
                if f.is_list:
                    args += [f"-{tag}="] + [f"-{tag}+={v}" for v in as_list(before.get(tag))]
                else:
                    args.append(f"-{tag}={as_text(before.get(tag))}")
        for tag in SMP_TAGS:
            v = before.get(tag)
            if tag == "XMP-smp:AddedKeywords":
                args += [f"-{tag}="] + [f"-{tag}+={x}" for x in as_list(v)]
            else:
                args.append(f"-{tag}={as_text(v)}")
        args += restore_gps(before)
        jobs.append((path, args))
    errors = et.write(jobs)
    store.mark_undone(run_id)
    return {"restored": len(jobs) - len(errors), "errors": errors}


def rows_json(rows: list[Row]) -> list[dict]:
    return [asdict(r) for r in rows]
