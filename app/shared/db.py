"""SQLite store for jobs, transcripts, summaries, and downloads."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


_TABLES = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    platform TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    title TEXT,
    duration REAL,
    uploader TEXT,
    download_type TEXT,
    quality TEXT,
    extra TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    language TEXT,
    source TEXT,
    text TEXT NOT NULL,
    segments TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    eli5 TEXT,
    detailed TEXT,
    key_points TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    type TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER,
    created_at TEXT NOT NULL
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
"""


class JobStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        with self._conn() as conn:
            conn.executescript(_TABLES)
            conn.executescript(_INDEXES)

    def _connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = self._connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self._conn() as conn:
            yield conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ── jobs ─────────────────────────────────────────────────

    def create(self, job_id: str, url: str, **kwargs) -> None:
        now = utcnow()
        with self._write() as conn:
            conn.execute(
                """INSERT INTO jobs (id, url, platform, status, stage, download_type, quality,
                    title, duration, uploader, created_at, updated_at, extra)
                   VALUES (?, ?, ?, 'queued', 'queued', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id, url, kwargs.get("platform"),
                    kwargs.get("download_type", "merged"),
                    kwargs.get("quality", "best"),
                    kwargs.get("title"), kwargs.get("duration"),
                    kwargs.get("uploader"), now, now,
                    json.dumps({k: v for k, v in kwargs.items() if k not in (
                        "platform", "download_type", "quality", "title", "duration", "uploader"
                    )}),
                ),
            )

    def update(self, job_id: str, **fields: Any) -> Optional[dict[str, Any]]:
        if not fields:
            return self.get(job_id)
        fields["updated_at"] = utcnow()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._write() as conn:
            conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))
        return self.get(job_id)

    def update_extra(self, job_id: str, **kv: Any) -> Optional[dict[str, Any]]:
        """Merge keys into the job's `extra` JSON column instead of clobbering it."""
        with self._write() as conn:
            row = conn.execute("SELECT extra FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            try:
                extra = json.loads(row["extra"] or "{}")
            except json.JSONDecodeError:
                extra = {}
            extra.update(kv)
            conn.execute(
                "UPDATE jobs SET extra = ?, updated_at = ? WHERE id = ?",
                (json.dumps(extra), utcnow(), job_id),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
        return int(row["n"])

    def delete(self, job_id: str) -> None:
        """Remove a job and all of its dependent rows."""
        with self._write() as conn:
            conn.execute("DELETE FROM downloads WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM transcripts WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM summaries WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    # ── transcripts ──────────────────────────────────────────

    def save_transcript(
        self, job_id: str, language: str, source: str, text: str, segments: list[dict]
    ) -> None:
        with self._write() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO transcripts
                   (job_id, language, source, text, segments, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (job_id, language, source, text, json.dumps(segments), utcnow()),
            )

    def get_transcript(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM transcripts WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row:
            d = dict(row)
            d["segments"] = json.loads(d["segments"])
            return d
        return None

    # ── summaries ────────────────────────────────────────────

    def save_summary(
        self, job_id: str, eli5: str, detailed: str, key_points: list[str]
    ) -> None:
        with self._write() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO summaries
                   (job_id, eli5, detailed, key_points, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (job_id, eli5, detailed, json.dumps(key_points), utcnow()),
            )

    def get_summary(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM summaries WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row:
            d = dict(row)
            d["key_points"] = json.loads(d["key_points"])
            return d
        return None

    # ── downloads ────────────────────────────────────────────

    def save_download(self, job_id: str, dtype: str, path: str, size: int) -> None:
        with self._write() as conn:
            conn.execute(
                "INSERT INTO downloads (job_id, type, path, size, created_at) VALUES (?, ?, ?, ?, ?)",
                (job_id, dtype, path, size, utcnow()),
            )

    def get_downloads(self, job_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM downloads WHERE job_id = ? ORDER BY created_at",
                (job_id,),
            ).fetchall()
        return [dict(r) for r in rows]