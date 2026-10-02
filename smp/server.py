"""The local web app: FastAPI routes and the one background job (generating metadata) a session runs."""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from smp import __version__, brief, config, images, machine, network, picker, plan, store, vlm
from smp.exif import ExifTool, ExifToolError, field_value
from smp.geo import geocoder

log = logging.getLogger(__name__)
STATIC = Path(__file__).resolve().parent / "static"


class Session:
    """One scanned folder: its images, their current metadata and the model's answers."""

    def __init__(self):
        self.lock = threading.Lock()
        self.root: Path | None = None
        self.recursive = True
        self.files: dict[str, images.ImageFile] = {}
        self.results: dict[str, dict] = {}         # path -> {"ai": {...}} or {"error": "..."}
        self.job = {"running": False, "done": 0, "total": 0, "cached": 0, "errors": 0, "message": "", "stop": False,
                    "current": "", "partial": {}, "finished": []}
        # current: the image being described; partial: its text fields as they stream in;
        # finished: every image with an answer (or an error) so far, in order
        self.last_run: dict | None = None
        self.scanning = {"running": False}          # see read_tree
        self.writing = {"running": False}           # see writing_files

    def exiftool(self) -> ExifTool:
        return ExifTool(config.load()["exiftool"])

    def read_tree(self, folder: Path, recursive: bool, root: Path) -> tuple[list[Path], dict]:
        """The images in folder and their metadata, keeping self.scanning up to date for /api/scan-progress.

        scanning: phase "listing" (looking through folders: current, found so far) then "reading" (metadata:
        read of total images)."""
        sc = self.scanning = {"running": True, "phase": "listing", "root": str(folder), "current": "", "found": [],
                              "images": 0, "read": 0, "total": 0}

        def on_folder(d: Path, n: int):
            r = rel(d, root)
            sc["current"] = r
            sc["found"].append({"rel": r, "depth": len(d.relative_to(root).parts), "images": n})
            sc["images"] += n

        try:
            paths = images.list_images(folder, recursive, on_folder)
            sc.update(phase="reading", current="", total=len(paths))
            metas = self.exiftool().read([str(p) for p in paths], lambda n: sc.update(read=n)) if paths else {}
            return paths, metas
        finally:
            sc["running"] = False

    def scan(self, folder: str, recursive: bool) -> None:
        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            raise HTTPException(400, f"Not a folder: {folder}")
        paths, metas = self.read_tree(root, recursive, root)
        with self.lock:
            if self.root != root:
                self.results = {}
            self.root, self.recursive = root, recursive
            self.files = {str(p): images.ImageFile(p, metas.get(os.path.normpath(str(p)), {})) for p in paths}
        config.remember_folder(str(root))

    def rescan_folder(self, folder: str) -> None:
        """Read one folder's images again (not its subfolders): removed files go, new ones come in."""
        d = Path(folder).expanduser().resolve()
        if not self.root or not (d == self.root or self.root in d.parents):
            raise HTTPException(400, f"Not in the scanned folder: {folder}")
        paths, metas = self.read_tree(d, False, self.root) if d.is_dir() else ([], {})
        with self.lock:
            keep = {str(p) for p in paths}
            for p in [p for p, f in self.files.items() if f.path.parent == d]:
                del self.files[p]
                if p not in keep:
                    self.results.pop(p, None)       # answers for images still there stay, unwritten or not
            for p in paths:
                self.files[str(p)] = images.ImageFile(p, metas.get(os.path.normpath(str(p)), {}))
            self.files = dict(sorted(self.files.items(), key=lambda kv: kv[1].path))

    @contextmanager
    def writing_files(self, total: int):
        """Keeps self.writing up to date for /api/write-progress while files are written (or restored).
        Yields step(phase): a progress callback for that phase, "checking" (reading what the files hold now),
        "writing", then "reading" (what they hold after)."""
        if self.writing["running"]:
            raise HTTPException(409, "Already writing")
        w = self.writing = {"running": True, "phase": "checking", "done": 0, "total": total}

        def step(phase: str, of: int | None = None):
            w.update(phase=phase, done=0, total=total if of is None else of)
            return lambda n: w.update(done=n)

        try:
            yield step
        finally:
            w["running"] = False

    def refresh(self, paths: list[str], on_progress=None) -> None:
        # with progress to show: smaller chunks, so the count moves while a few hundred files are read
        metas = self.exiftool().read(paths, on_progress, chunk_size=25 if on_progress else 100)
        with self.lock:
            for p in paths:
                if p in self.files:
                    self.files[p].meta = metas.get(os.path.normpath(p), {})

    def folders(self) -> list[dict]:
        if not self.root:
            return []
        counts: dict[Path, int] = {}
        for f in self.files.values():
            counts[f.path.parent] = counts.get(f.path.parent, 0) + 1
        # Folders between the root and an image folder show too, even without images of their own: otherwise
        # a nested folder is indented under whichever folder happens to come before it.
        dirs = {self.root}
        for d in counts:
            dirs.update(p for p in [d, *d.parents] if p == self.root or self.root in p.parents)
        dirs = sorted(dirs)
        defaults = defaults_from(config.load())
        out = []
        for d in dirs:
            r = brief.resolve(d, defaults)
            out.append({"path": str(d), "rel": rel(d, self.root), "depth": len(d.relative_to(self.root).parts),
                        "images": counts.get(d, 0),
                        "brief": "own" if r.own else ("inherited" if r.sources else "missing"),
                        **self.progress([f for f in self.files.values() if f.path.parent == d], r.digest)})
        return out

    def progress(self, files: list[images.ImageFile], brief_digest: str) -> dict:
        """Where a folder's images are in the workflow, for the step dots.

        written: caption and alt text both in the file (whoever wrote them); read from the files, so it's right
        after a restart. pending: the model has answered but nothing is written yet (this session only).
        stale: written by SMP with a brief that has changed since."""
        written = pending = stale = 0
        for f in files:
            done = bool(field_value(f.meta, "caption")) and bool(field_value(f.meta, "alt_text"))
            written += done
            res = self.results.get(str(f.path), {})
            if "ai" in res and not done:
                pending += 1
            wrote_with = f.meta.get("XMP-smp:BriefHash")
            if wrote_with and wrote_with != brief_digest:
                stale += 1
        return {"written": written, "pending": pending, "stale": stale}


S = Session()
PULL: dict = {}          # the model download, if one is running or has run


def rel(p: Path, root: Path) -> str:
    try:
        r = p.relative_to(root.parent)
    except ValueError:
        return str(p)
    return r.as_posix()


def thumb_url(path: str) -> str:
    return "/thumb?path=" + quote(path, safe="")


def defaults_from(s: dict) -> dict:
    return {k: s.get(k, "") for k in ("creator", "credit", "copyright", "language")}


def place_for(img: images.ImageFile):
    lat, lon = img.meta.get("Composite:GPSLatitude"), img.meta.get("Composite:GPSLongitude")
    if lat in (None, "") or lon in (None, ""):
        return None
    return geocoder().lookup(float(lat), float(lon))


def roots() -> list[str]:
    """Where browsing this computer's folders starts: its drives on Windows, else / and the home folder."""
    if os.name == "nt":
        drives = getattr(os, "listdrives", None)
        found = drives() if drives else [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]
        return [d for d in found if d[:1].upper() not in "AB"]       # no floppy drives
    return ["/", str(Path.home())]


def in_scope(path: str, folder: str | None, folders: list[str] | None = None) -> bool:
    """In this folder (not its subfolders), or in any of these folders; neither given: everything."""
    if folders:
        return Path(path).parent in {Path(f) for f in folders}
    if not folder:
        return True
    return Path(path).parent == Path(folder)


def to_do(img: images.ImageFile, brief_digest: str) -> bool:
    """Still needs the model: nothing generated or written yet, or written with a brief that has changed since."""
    if "ai" in S.results.get(str(img.path), {}):
        return False
    written = bool(field_value(img.meta, "caption")) and bool(field_value(img.meta, "alt_text"))
    wrote_with = img.meta.get("XMP-smp:BriefHash")
    return not written or bool(wrote_with and wrote_with != brief_digest)


# ---- generation job ------------------------------------------------------------------------------------------

def run_job(folder: str | None, backend_name: str | None, paths: list[str] | None = None,
            folders: list[str] | None = None, skip_done: bool = False) -> None:
    s = config.load()
    job = S.job
    try:
        be = vlm.backend(s, backend_name)
        job["message"] = f"Starting {be.model}..."
        be.ensure()
        if not geocoder().available():
            try:
                job["message"] = "Downloading place names (once)..."
                geocoder().download()
            except Exception as e:          # places stay empty; everything else still works
                log.warning("GeoNames download failed: %s", e)
        if paths:
            todo = [S.files[p] for p in paths if p in S.files]
        else:
            todo = [f for p, f in S.files.items() if in_scope(p, folder, folders)]
        defaults = defaults_from(s)
        briefs: dict[Path, brief.Resolved] = {}
        if skip_done:
            for img in todo:
                briefs.setdefault(img.path.parent, brief.resolve(img.path.parent, defaults))
            todo = [img for img in todo if to_do(img, briefs[img.path.parent].digest)]
        job.update(total=len(todo), done=0, cached=0, errors=0, message=f"Describing with {be.model}")
        for img in todo:
            if job["stop"]:
                job["message"] = "Stopped"
                break
            d = img.path.parent
            if d not in briefs:
                briefs[d] = brief.resolve(d, defaults)
            b = briefs[d]
            job.update(current=str(img.path), partial={})
            try:
                place = place_for(img)
                facts = images.facts(img, S.root, place.label() if place else "")
                ai, cached = vlm.describe(be, images.pixel_id(img), lambda px, p=img.path: images.jpeg_b64(p, px),
                                          facts, b.context, plan.own_text(img.meta), b.meta.get("language", "en"),
                                          on_partial=lambda fields: job.update(partial=fields))
                S.results[str(img.path)] = {"ai": ai, "model": be.model, "brief": b.digest}
                job["cached"] += int(cached)
            except Exception as e:
                log.exception("describe failed for %s", img.path)
                S.results[str(img.path)] = {"error": str(e)[:300]}
                job["errors"] += 1
                if isinstance(e, vlm.VLMError) and job["errors"] >= 3 and job["done"] == 0:
                    job["message"] = f"Stopped: {e}"
                    job["finished"].append(str(img.path))
                    break
            job["finished"].append(str(img.path))
            job.update(current="", partial={})
            job["done"] += 1
        else:
            job["message"] = "Done"
    except Exception as e:
        log.exception("job failed")
        job["message"] = f"Failed: {e}"
    finally:
        job.update(running=False, current="", partial={})


# ---- app -----------------------------------------------------------------------------------------------------

def create_app(lan: bool = False) -> FastAPI:
    """lan: listening on every network interface, so other computers can open the app too."""
    app = FastAPI(title="IVAR SMP", version=__version__)
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.middleware("http")
    async def fresh_page(request, call_next):
        # the browser checks back every time (a cheap 304 when nothing changed), so after an update the page never
        # runs an old app.js against the new index.html
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(STATIC / "smp-icon.ico")

    @app.get("/api/status")
    def status(request: Request):
        """Everything the Setup panel shows: tools, GPU, the local model, the Claude key and the network.

        network.here: the browser asking runs on this computer (else the page browses folders itself, see
        /api/browse, since the operating system's folder dialog would open on this computer instead)."""
        s = config.load()
        g = machine.gpu()
        rec = machine.recommended()
        out = {"version": __version__, "backend": s["backend"], "places": geocoder().available(),
               "gpu": {"name": g.name, "memory_gb": g.memory_gb, "kind": g.kind},
               "recommended": {"name": rec.name, "model": rec.tags[0], "approx_gb": rec.approx_gb},
               "local_useful": g.memory_gb >= machine.MIN_USEFUL_GB,
               "claude_model": s["claude_model"],
               "claude_key": bool(s.get("claude_api_key") or os.environ.get("ANTHROPIC_API_KEY")
                                  or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
               "claude_key_saved": bool(s.get("claude_api_key")),
               "folders": {"tools": str(config.tools_dir()), "models": s["ollama_models_dir"],
                           "data": str(config.data_dir())},
               "pull": dict(PULL),
               "network": {"on": lan, "here": network.is_this_computer(request.client and request.client.host),
                           "urls": [f"http://{ip}:{request.url.port or 80}/" for ip in network.lan_addresses()]
                           if lan else [],
                           "firewall": network.firewall_rule() if lan else None}}
        try:
            out["exiftool"] = ExifTool(s["exiftool"]).version()
        except (ExifToolError, OSError) as e:
            out["exiftool"], out["exiftool_error"] = "", str(e)
        be = vlm.OllamaBackend(s)
        running = be.alive()
        installed = be.installed() if running else machine.installed_models(s["ollama_models_dir"])
        model = s["ollama_model"] or machine.pick_model(installed)
        out["ollama"] = {"exe": s["ollama_exe"], "running": running, "model": model,
                         "approx_gb": machine.size_of(model),
                         "chosen": bool(s["ollama_model"]), "installed": installed,
                         "ready": model in installed or f"{model}:latest" in installed}
        out["ready"] = bool(out["exiftool"]) and (out["ollama"]["ready"] if s["backend"] == "ollama"
                                                   else out["claude_key"])
        return out

    @app.post("/api/model/pull")
    def pull_model(body: dict = Body(default={})):
        if PULL.get("running"):
            raise HTTPException(409, "Already downloading")
        s = config.load()
        be = vlm.OllamaBackend(s)
        be.model = body.get("model") or s["ollama_model"] or machine.recommended().tags[0]
        PULL.clear()
        PULL.update(running=True, model=be.model, status="Starting Ollama...", done=0, total=0, error="")

        def run():
            try:
                be.pull(lambda st, done, total: PULL.update(status=st, done=done, total=total))
                PULL["status"] = "Downloaded"
            except Exception as e:
                log.exception("model download failed")
                PULL["error"] = str(e)
            finally:
                PULL["running"] = False

        threading.Thread(target=run, daemon=True).start()
        return {"started": be.model}

    @app.post("/api/claude-key")
    def claude_key(body: dict = Body(...)):
        config.save({"claude_api_key": (body.get("key") or "").strip()})
        return {"saved": bool((body.get("key") or "").strip())}

    @app.get("/api/settings")
    def get_settings():
        s = config.load()
        s.pop("claude_api_key", None)        # never sent back to the page
        s["_explicit"] = sorted(config.stored())
        return s

    @app.post("/api/settings")
    def post_settings(changes: dict = Body(...)):
        changes.pop("claude_api_key", None)  # set through /api/claude-key only
        s = config.save(changes)
        s.pop("claude_api_key", None)
        return s

    @app.post("/api/pick-folder")
    def pick_folder(request: Request, body: dict = Body(default={})):
        """Opens the operating system's folder dialog on this computer; waits until the user closes it."""
        if not network.is_this_computer(request.client and request.client.host):
            raise HTTPException(409, "The folder dialog only opens on the computer SMP runs on")
        return {"path": picker.pick_folder(body.get("initial") or "")}

    @app.get("/api/browse")
    def browse(path: str = ""):
        """The folders in a folder on this computer, for choosing one from another computer's browser.
        No path: the drives (Windows) or / and the home folder, and the folders opened recently."""
        if not path:
            return {"path": "", "parent": "", "images": 0, "folders": [{"name": r, "path": r} for r in roots()],
                    "recent": [f for f in config.load().get("recent_folders", []) if os.path.isdir(f)]}
        d = Path(path).expanduser()
        if not d.is_dir():
            raise HTTPException(404, f"No such folder: {path}")
        d = d.resolve()
        folders, n = [], 0
        try:
            for e in os.scandir(d):
                try:
                    if e.name.startswith((".", "$")):
                        continue
                    if e.is_dir():
                        folders.append({"name": e.name, "path": e.path})
                    elif images.is_image(Path(e.path)):
                        n += 1
                except OSError:
                    continue
        except PermissionError as e:
            raise HTTPException(403, f"No access to {d}") from e
        folders.sort(key=lambda f: f["name"].lower())
        return {"path": str(d), "parent": str(d.parent) if d.parent != d else "", "images": n, "folders": folders}

    @app.post("/api/scan")
    def scan(body: dict = Body(...)):
        if S.job["running"]:
            raise HTTPException(409, "A job is running")
        if S.scanning["running"]:
            raise HTTPException(409, "Already scanning")
        S.scan(body["folder"], bool(body.get("recursive", True)))
        return {"root": str(S.root), "folders": S.folders(), "images": len(S.files)}

    @app.get("/api/scan-progress")
    def scan_progress(since: int = 0):
        """How the scan that's running (or ran last) is getting on, while /api/scan is still working.
        found: the folders looked through after the first `since` (the page has those already)."""
        sc = dict(S.scanning)
        found = sc.pop("found", [])
        return {**sc, "found": found[since:], "found_total": len(found)}

    @app.post("/api/rescan")
    def rescan(body: dict = Body(...)):
        if S.job["running"]:
            raise HTTPException(409, "A job is running")
        if S.scanning["running"]:
            raise HTTPException(409, "Already scanning")
        S.rescan_folder(body["folder"])
        return {"root": str(S.root), "folders": S.folders(), "images": len(S.files)}

    @app.get("/api/folders")
    def folders():
        return {"root": str(S.root) if S.root else "", "folders": S.folders()}

    @app.get("/api/images")
    def image_list(folder: str = ""):
        out = []
        for p, f in S.files.items():
            if folder and not in_scope(p, folder):
                continue
            out.append({"path": p, "name": f.path.name, "thumb": thumb_url(p),
                        "title": field_value(f.meta, "title"), "caption": field_value(f.meta, "caption"),
                        "status": "error" if "error" in S.results.get(p, {}) else
                        ("described" if p in S.results else "")})
        return out

    @app.get("/thumb")
    def thumb(path: str):
        f = S.files.get(path)
        if not f:
            raise HTTPException(404)
        try:
            return FileResponse(images.thumbnail(f), headers={"Cache-Control": "max-age=3600"})
        except Exception as e:
            raise HTTPException(500, f"No preview: {e}") from e

    @app.get("/full")
    def full(path: str):
        f = S.files.get(path)
        if not f:
            raise HTTPException(404)
        return Response(images.jpeg_bytes(f.path, 1800), media_type="image/jpeg")

    @app.get("/api/brief")
    def get_brief(folder: str):
        d = Path(folder)
        own = brief.load(d)
        s = config.load()
        parents = [{"folder": str(b.folder), "name": b.folder.name, "meta": b.meta, "body": b.body}
                   for b in brief.chain(d) if b.folder.resolve() != d.resolve()]
        resolved = brief.resolve(d, defaults_from(s))
        return {"folder": str(d), "name": d.name, "own": {"meta": own.meta, "body": own.body} if own else None,
                "parents": parents, "effective": resolved.meta, "fields": brief.META_FIELDS}

    @app.post("/api/brief")
    def post_brief(body: dict = Body(...)):
        folder = Path(body["folder"])
        old = brief.load(folder)
        # fields the form doesn't show (added to brief.md by hand) are kept
        extra = {k: v for k, v in (old.meta if old else {}).items() if k not in brief.META_FIELDS}
        b = brief.save(folder, {**extra, **(body.get("meta") or {})}, body.get("body") or "")
        return {"saved": str(b.path)}

    @app.post("/api/brief/draft")
    def draft(body: dict = Body(...)):
        d = Path(body["folder"])
        s = config.load()
        be = vlm.backend(s, body.get("backend"))
        try:
            be.ensure()
        except vlm.VLMError as e:
            raise HTTPException(503, str(e)) from e
        imgs = [f for p, f in S.files.items() if Path(p).parent == d] or \
               [f for p, f in S.files.items() if str(Path(p)).startswith(str(d))]
        if not imgs:
            raise HTTPException(400, "No images in this folder")
        step = max(1, len(imgs) // 6)
        sample = imgs[::step][:6]
        facts = []
        for f in sample:
            place = place_for(f)
            facts.append("; ".join(images.facts(f, S.root or d, place.label() if place else "")[1:]))
        captions = [c for c in (field_value(f.meta, "caption") for f in imgs) if c]
        captions = list(dict.fromkeys(captions))[:8]
        lang = brief.resolve(d, defaults_from(s)).meta.get("language", "en")
        try:
            text = vlm.draft_brief(be, rel(d, S.root) if S.root else str(d), facts, captions,
                                   [images.jpeg_b64(f.path, 768) for f in sample], lang)
        except vlm.VLMError as e:
            raise HTTPException(502, str(e)) from e
        return {"body": text}

    @app.post("/api/generate")
    def generate(body: dict = Body(default={})):
        if S.job["running"]:
            raise HTTPException(409, "Already running")
        if not S.files:
            raise HTTPException(400, "Scan a folder first")
        S.job.update(running=True, stop=False, done=0, total=0, errors=0, cached=0, message="Starting...",
                     current="", partial={}, finished=[])
        # "paths": just these images (a card's Generate button), else the ticked "folders", else the folder,
        # else everything. "skip_done": leave out images already generated or written (unless the brief changed).
        threading.Thread(target=run_job, args=(body.get("folder") or None, body.get("backend"), body.get("paths"),
                                               body.get("folders"), bool(body.get("skip_done"))),
                         daemon=True).start()
        return {"started": True}

    @app.post("/api/stop")
    def stop():
        S.job["stop"] = True
        return {"stopping": S.job["running"]}

    @app.get("/api/job")
    def job(since: int = 0):
        """The generate job. finished lists only the images done after the first `since`, so the page can ask
        several times a second without receiving the whole list each time."""
        out = {k: v for k, v in S.job.items() if k not in ("stop", "finished")}
        out["finished"] = S.job["finished"][since:]
        out["finished_total"] = len(S.job["finished"])
        return out

    @app.post("/api/preview")
    def preview(body: dict = Body(default={})):
        """Every image in scope: what its file holds now (editable) and the changes waiting to be written.
        {"path": ...} returns just that image, to refresh its card after writing it."""
        folder = body.get("folder") or None
        folders = body.get("folders") or None
        only = body.get("path")
        opts = {"replace_human": bool(body.get("replace_human")),
                "override_credits": bool(body.get("override_credits"))}
        defaults = defaults_from(config.load())
        briefs: dict[Path, brief.Resolved] = {}
        out = []
        for p, f in S.files.items():
            if (only and p != only) or (not only and not in_scope(p, folder, folders)):
                continue
            res = S.results.get(p, {})
            d = f.path.parent
            if d not in briefs:
                briefs[d] = brief.resolve(d, defaults)
            rows = plan.propose(f.meta, res.get("ai"), briefs[d].meta, place_for(f), **opts)
            current = {name: field_value(f.meta, name) for name in plan.EDITABLE}
            out.append({"path": p, "name": f.path.name, "rel": rel(f.path, S.root), "thumb": thumb_url(p),
                        "error": res.get("error"), "described": "ai" in res, "rows": plan.rows_json(rows),
                        "current": current,
                        "done": bool(current["caption"]) and bool(current["alt_text"])})
        return {"images": out}

    @app.post("/api/write")
    def write(body: dict = Body(...)):
        items = body.get("items") or []
        paths = [i["path"] for i in items if i["path"] in S.files and i.get("rows")]
        if not paths:
            return {"written": 0, "errors": {}}
        with S.writing_files(len(paths)) as step:
            S.refresh(paths, step("checking"))            # plan against what the files hold now
            defaults = defaults_from(config.load())
            plans = {}
            for i in items:
                p = i["path"]
                if p not in paths:
                    continue
                res = S.results.get(p, {})
                plans[p] = {"meta": S.files[p].meta, "rows": i["rows"], "model": res.get("model", ""),
                            "brief": res.get("brief") or brief.resolve(Path(p).parent, defaults).digest}
            result = plan.write(S.exiftool(), str(S.root), plans, step("writing"))
            S.refresh(paths, step("reading"))
        S.last_run = result
        return result

    @app.get("/api/write-progress")
    def write_progress():
        """How writing (or undoing) is getting on, while /api/write or /api/undo is still working."""
        return S.writing

    @app.post("/api/undo")
    def undo(body: dict = Body(...)):
        run_id = int(body["run_id"])
        restored = list(store.snapshots(run_id))
        with S.writing_files(len(restored)) as step:
            result = plan.undo(S.exiftool(), run_id, step("writing"))
            still_here = [p for p in restored if p in S.files]
            S.refresh(still_here, step("reading", len(still_here)))
        return result

    @app.get("/api/runs")
    def runs():
        return store.recent_runs()

    return app
