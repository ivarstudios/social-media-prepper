"""Local SQLite store: the vision model's cached answers and an undo record of every write."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from smp.config import data_dir

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, response TEXT NOT NULL, model TEXT, created REAL);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, folder TEXT, created REAL, files INTEGER,
                                 undone REAL);
CREATE TABLE IF NOT EXISTS snapshots (run_id INTEGER, path TEXT, before TEXT, PRIMARY KEY (run_id, path));
"""


def db(path: Path | None = None) -> sqlite3.Connection:
    global _conn
    if _conn is None or path is not None:
        _conn = sqlite3.connect(str(path or data_dir() / "smp.sqlite"), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
    return _conn


def cache_get(key: str) -> dict | None:
    with _lock:
        row = db().execute("SELECT response FROM cache WHERE key=?", (key,)).fetchone()
    return json.loads(row["response"]) if row else None


def cache_put(key: str, response: dict, model: str) -> None:
    with _lock:
        db().execute("INSERT OR REPLACE INTO cache VALUES (?,?,?,?)",
                     (key, json.dumps(response, ensure_ascii=False), model, time.time()))
        db().commit()


def start_run(folder: str, files: int) -> int:
    with _lock:
        cur = db().execute("INSERT INTO runs(folder, created, files) VALUES (?,?,?)", (folder, time.time(), files))
        db().commit()
        return int(cur.lastrowid)


def snapshot(run_id: int, path: str, before: dict) -> None:
    with _lock:
        db().execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?)",
                     (run_id, path, json.dumps(before, ensure_ascii=False)))
        db().commit()


def snapshots(run_id: int) -> dict[str, dict]:
    with _lock:
        rows = db().execute("SELECT path, before FROM snapshots WHERE run_id=?", (run_id,)).fetchall()
    return {r["path"]: json.loads(r["before"]) for r in rows}


def mark_undone(run_id: int) -> None:
    with _lock:
        db().execute("UPDATE runs SET undone=? WHERE id=?", (time.time(), run_id))
        db().commit()


def recent_runs(limit: int = 20) -> list[dict]:
    with _lock:
        rows = db().execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
