from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    text TEXT NOT NULL,
                    task TEXT NOT NULL,
                    executor TEXT NOT NULL,
                    agent_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    result_markdown TEXT,
                    error TEXT,
                    returncode INTEGER
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                );
                """
            )

    def create_job(self, workspace: str, sender: str, text: str, task: str, executor: str = "codex") -> dict[str, Any]:
        now = utc_now()
        job_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, status, workspace, sender, text, task, executor, created_at, updated_at)
                VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, workspace, sender, text, task, executor, now, now),
            )
        return self.get_job(job_id) or {"id": job_id}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def claim_next_job(self, agent_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if not row:
                conn.commit()
                return None
            conn.execute(
                """
                UPDATE jobs
                SET status = 'running', agent_id = ?, started_at = ?, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (agent_id, now, now, row["id"]),
            )
            conn.execute(
                "INSERT INTO job_events (job_id, event_type, message, created_at) VALUES (?, 'claimed', ?, ?)",
                (row["id"], f"agent {agent_id} claimed job", now),
            )
            conn.commit()
        return self.get_job(str(row["id"]))

    def add_event(self, job_id: str, event_type: str, message: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                return None
            conn.execute(
                "INSERT INTO job_events (job_id, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                (job_id, event_type, message, now),
            )
            conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (now, job_id))
        return self.get_job(job_id)

    def complete_job(self, job_id: str, ok: bool, result_markdown: str, returncode: int | None = None, error: str = "") -> dict[str, Any] | None:
        now = utc_now()
        status = "succeeded" if ok else "failed"
        with self.connect() as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                return None
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, completed_at = ?, updated_at = ?, result_markdown = ?, error = ?, returncode = ?
                WHERE id = ?
                """,
                (status, now, now, result_markdown, error, returncode, job_id),
            )
            conn.execute(
                "INSERT INTO job_events (job_id, event_type, message, created_at) VALUES (?, 'complete', ?, ?)",
                (job_id, status, now),
            )
        return self.get_job(job_id)

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM job_events WHERE job_id = ? ORDER BY id ASC", (job_id,)
            ).fetchall()
        return [dict(row) for row in rows]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
