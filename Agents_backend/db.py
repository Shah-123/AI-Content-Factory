"""
db.py — SQLite persistence layer for the web API.
Manages the `web_jobs` table that tracks all blog generation jobs
submitted through the web interface.
"""

import sqlite3
import json
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Database lives in a data/ subdirectory to avoid uvicorn reload loops
_DATA_DIR = Path(__file__).parent / "data"
_DATA_DIR.mkdir(exist_ok=True)
DB_PATH = _DATA_DIR / "web_jobs.db"


# ============================================================================
# SCHEMA
# ============================================================================

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS web_jobs (
    id                   TEXT PRIMARY KEY,
    topic                TEXT NOT NULL,
    tone                 TEXT DEFAULT 'professional',
    sections             INTEGER DEFAULT 3,
    status               TEXT DEFAULT 'pending',
    created_at           TEXT,
    completed_at         TEXT,
    blog_folder          TEXT,
    qa_score             REAL,
    qa_verdict           TEXT,
    blog_evaluator_score REAL,
    blog_file            TEXT,
    blog_html_file       TEXT,
    podcast_file         TEXT,
    video_file           TEXT,
    plan_json            TEXT,
    error_message        TEXT,
    word_count           INTEGER,
    final_content        TEXT,
    social_linkedin      TEXT,
    social_twitter       TEXT,
    generate_podcast     INTEGER DEFAULT 0,
    generate_video       INTEGER DEFAULT 0,
    generate_campaign    INTEGER DEFAULT 0
);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with _get_conn() as conn:
        conn.execute(_CREATE_TABLE)
        conn.commit()


# ============================================================================
# CRUD
# ============================================================================

def create_job(topic: str, tone: str = "professional", sections: int = 3,
               generate_podcast: bool = False, generate_video: bool = False,
               generate_campaign: bool = False) -> dict:
    """Insert a new job row and return the job dict."""
    job_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO web_jobs
               (id, topic, tone, sections, status, created_at,
                generate_podcast, generate_video, generate_campaign)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (job_id, topic, tone, sections, "pending", created_at,
             int(generate_podcast), int(generate_video), int(generate_campaign))
        )
        conn.commit()
    return get_job(job_id)


def get_job(job_id: str) -> Optional[dict]:
    """Fetch a single job by id."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM web_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(limit: int = 50) -> list[dict]:
    """List jobs sorted newest-first."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM web_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_job(job_id: str, **fields) -> Optional[dict]:
    """Update arbitrary fields on a job."""
    if not fields:
        return get_job(job_id)
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    with _get_conn() as conn:
        conn.execute(
            f"UPDATE web_jobs SET {set_clause} WHERE id = ?", values
        )
        conn.commit()
    return get_job(job_id)


def set_job_running(job_id: str, blog_folder: str):
    update_job(job_id, status="running", blog_folder=blog_folder)


def set_job_awaiting_approval(job_id: str, plan_json: str):
    update_job(job_id, status="awaiting_approval", plan_json=plan_json)


def set_job_completed(job_id: str, **result_fields):
    update_job(
        job_id,
        status="completed",
        completed_at=datetime.utcnow().isoformat(),
        **result_fields,
    )


def set_job_failed(job_id: str, error: str):
    update_job(
        job_id,
        status="failed",
        completed_at=datetime.utcnow().isoformat(),
        error_message=str(error)[:2000],
    )


# ============================================================================
# HELPER
# ============================================================================

def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # Parse plan JSON if present
    if d.get("plan_json"):
        try:
            d["plan"] = json.loads(d["plan_json"])
        except Exception:
            d["plan"] = None
    else:
        d["plan"] = None
    # Expose boolean-style flags as booleans
    for flag in ("generate_podcast", "generate_video", "generate_campaign"):
        if flag in d:
            d[flag] = bool(d[flag])
    return d


# Auto-init on import
init_db()
