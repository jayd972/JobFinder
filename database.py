"""SQLite database layer for JobFinder MVP."""

import sqlite3
import os
import uuid
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "jobfinder.db")


def get_db():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            company_id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            workday_url TEXT NOT NULL,
            note TEXT,
            preferred_keywords TEXT,
            last_run_status TEXT,
            last_run_time TEXT
        );

        CREATE TABLE IF NOT EXISTS jobs (
            job_key TEXT PRIMARY KEY,
            company_id TEXT NOT NULL,
            title TEXT NOT NULL,
            locations_text TEXT,
            country_guess TEXT,
            posted_label TEXT,
            job_url TEXT,
            jd_text TEXT,
            match_score REAL,
            matched_keywords TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            run_id TEXT,
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            total_companies INTEGER DEFAULT 0,
            total_jobs_found INTEGER DEFAULT 0,
            total_jobs_returned INTEGER DEFAULT 0,
            error_log TEXT,
            progress_detail TEXT
        );

        CREATE TABLE IF NOT EXISTS resume (
            user_id TEXT PRIMARY KEY DEFAULT 'default',
            resume_text TEXT,
            resume_sections TEXT,
            skills_list TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);
        CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);
    """)
    conn.commit()
    conn.close()


# ── Company Operations ──────────────────────────────────────────────

def upsert_companies(companies):
    """Insert or update companies. Returns count inserted."""
    conn = get_db()
    count = 0
    for c in companies:
        cid = c.get("company_id") or str(uuid.uuid4())[:8]
        conn.execute("""
            INSERT INTO companies (company_id, company_name, workday_url, note, preferred_keywords)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(company_id) DO UPDATE SET
                company_name=excluded.company_name,
                workday_url=excluded.workday_url,
                note=excluded.note,
                preferred_keywords=excluded.preferred_keywords
        """, (cid, c["company_name"], c["workday_url"], c.get("note"), c.get("preferred_keywords")))
        count += 1
    conn.commit()
    conn.close()
    return count


def get_all_companies():
    """Get all companies."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM companies ORDER BY company_name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_companies():
    """Remove all companies."""
    conn = get_db()
    conn.execute("DELETE FROM jobs")  # Clear dependent jobs first
    conn.execute("DELETE FROM companies")
    conn.commit()
    conn.close()


def update_company_run_status(company_id, status):
    """Update company last run status."""
    conn = get_db()
    conn.execute(
        "UPDATE companies SET last_run_status=?, last_run_time=? WHERE company_id=?",
        (status, datetime.utcnow().isoformat(), company_id),
    )
    conn.commit()
    conn.close()


# ── Job Operations ──────────────────────────────────────────────────

def upsert_job(job):
    """Insert or update a job. Returns True if new."""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    existing = conn.execute("SELECT job_key FROM jobs WHERE job_key=?", (job["job_key"],)).fetchone()
    if existing:
        conn.execute("""
            UPDATE jobs SET last_seen=?, posted_label=?, match_score=?, matched_keywords=?, run_id=?
            WHERE job_key=?
        """, (now, job.get("posted_label"), job.get("match_score"), job.get("matched_keywords"),
              job.get("run_id"), job["job_key"]))
        conn.commit()
        conn.close()
        return False
    else:
        conn.execute("""
            INSERT INTO jobs (job_key, company_id, title, locations_text, country_guess,
                posted_label, job_url, jd_text, match_score, matched_keywords, first_seen, last_seen, run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job["job_key"], job["company_id"], job["title"], job.get("locations_text"),
            job.get("country_guess"), job.get("posted_label"), job.get("job_url"),
            job.get("jd_text"), job.get("match_score"), job.get("matched_keywords"),
            now, now, job.get("run_id"),
        ))
        conn.commit()
        conn.close()
        return True


def upsert_jobs_batch(jobs):
    """Insert or update multiple jobs in a single transaction. Much faster than calling upsert_job() in a loop."""
    if not jobs:
        return
    conn = get_db()
    now = datetime.utcnow().isoformat()
    try:
        for job in jobs:
            existing = conn.execute("SELECT job_key FROM jobs WHERE job_key=?", (job["job_key"],)).fetchone()
            if existing:
                conn.execute("""
                    UPDATE jobs SET last_seen=?, posted_label=?, match_score=?, matched_keywords=?, run_id=?
                    WHERE job_key=?
                """, (now, job.get("posted_label"), job.get("match_score"), job.get("matched_keywords"),
                      job.get("run_id"), job["job_key"]))
            else:
                conn.execute("""
                    INSERT INTO jobs (job_key, company_id, title, locations_text, country_guess,
                        posted_label, job_url, jd_text, match_score, matched_keywords, first_seen, last_seen, run_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job["job_key"], job["company_id"], job["title"], job.get("locations_text"),
                    job.get("country_guess"), job.get("posted_label"), job.get("job_url"),
                    job.get("jd_text"), job.get("match_score"), job.get("matched_keywords"),
                    now, now, job.get("run_id"),
                ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def get_results(run_id=None, company=None, keyword=None, min_score=None, location=None):
    """Query jobs with optional filters."""
    conn = get_db()
    query = """
        SELECT j.*, c.company_name
        FROM jobs j JOIN companies c ON j.company_id = c.company_id
        WHERE 1=1
    """
    params = []
    if run_id:
        query += " AND j.run_id = ?"
        params.append(run_id)
    if company:
        query += " AND c.company_name LIKE ?"
        params.append(f"%{company}%")
    if keyword:
        query += " AND (j.title LIKE ? OR j.jd_text LIKE ?)"
        params.append(f"%{keyword}%")
        params.append(f"%{keyword}%")
    if min_score is not None:
        query += " AND j.match_score >= ?"
        params.append(float(min_score))
    if location:
        query += " AND j.locations_text LIKE ?"
        params.append(f"%{location}%")
    query += " ORDER BY j.match_score DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Run Operations ──────────────────────────────────────────────────

def create_run():
    """Create a new run record."""
    conn = get_db()
    run_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO runs (run_id, started_at, status) VALUES (?, ?, 'running')",
        (run_id, now),
    )
    conn.commit()
    conn.close()
    return run_id


def update_run(run_id, **kwargs):
    """Update run fields."""
    conn = get_db()
    sets = []
    params = []
    for k, v in kwargs.items():
        sets.append(f"{k}=?")
        params.append(v)
    params.append(run_id)
    conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE run_id=?", params)
    conn.commit()
    conn.close()


def get_run(run_id):
    """Get a run record."""
    conn = get_db()
    row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_run():
    """Get the most recent run."""
    conn = get_db()
    row = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


# ── Resume Operations ───────────────────────────────────────────────

def save_resume(text, sections=None, skills=None):
    """Save or update the user's resume."""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO resume (user_id, resume_text, resume_sections, skills_list, updated_at)
        VALUES ('default', ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            resume_text=excluded.resume_text,
            resume_sections=excluded.resume_sections,
            skills_list=excluded.skills_list,
            updated_at=excluded.updated_at
    """, (text, json.dumps(sections) if sections else None,
          json.dumps(skills) if skills else None, now))
    conn.commit()
    conn.close()


def get_resume():
    """Get the stored resume."""
    conn = get_db()
    row = conn.execute("SELECT * FROM resume WHERE user_id='default'").fetchone()
    conn.close()
    if row:
        r = dict(row)
        r["resume_sections"] = json.loads(r["resume_sections"]) if r["resume_sections"] else {}
        r["skills_list"] = json.loads(r["skills_list"]) if r["skills_list"] else []
        return r
    return None


# ── Settings Operations ─────────────────────────────────────────────

def get_setting(key, default=None):
    """Get a setting value by key."""
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    if row:
        return row["value"]
    return default


def save_setting(key, value):
    """Save or update a setting."""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
    """, (key, value, now))
    conn.commit()
    conn.close()


# Initialize DB on import
init_db()
