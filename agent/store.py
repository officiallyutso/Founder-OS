"""Agent persistence layer.

Adds the self-evolving agent's own tables to the existing SQLite database
(`data/founder_os.db`): reminders, goals, lessons, skills, approvals, and a
full action audit log. Tables are created idempotently on import.
"""
import json
import sqlite3
from datetime import datetime
from typing import Optional

from memory.sql_store import get_conn  # reuse the same DB connection helper


def init_agent_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            due_at TIMESTAMP NOT NULL,
            repeat TEXT,                       -- null | 'daily' | 'weekly' | 'monthly'
            status TEXT DEFAULT 'pending',     -- pending | done | cancelled
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            detail TEXT,
            status TEXT DEFAULT 'active',      -- active | done | paused | dropped
            priority INTEGER DEFAULT 3,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            situation TEXT,
            lesson TEXT NOT NULL,
            tags TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            when_to_use TEXT,
            steps TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,
            tool_name TEXT NOT NULL,
            args_json TEXT,
            summary TEXT,
            status TEXT DEFAULT 'pending',     -- pending | approved | rejected | executed | failed
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            decided_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT,                        -- 'agent' | 'user' | 'heartbeat'
            tool_name TEXT,
            args_json TEXT,
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal TEXT NOT NULL,
            rationale TEXT,
            status TEXT DEFAULT 'open',        -- open | done | abandoned
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS subtasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER REFERENCES plans(id),
            seq INTEGER,
            description TEXT NOT NULL,
            depends_on TEXT,                   -- comma-separated subtask seqs
            status TEXT DEFAULT 'pending',     -- pending | done | skipped
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grp TEXT NOT NULL,                 -- decision family, e.g. 'email_subject_style'
            variant TEXT NOT NULL,             -- the approach tried
            trials INTEGER DEFAULT 0,
            successes INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(grp, variant)
        );

        CREATE TABLE IF NOT EXISTS monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,               -- search topic to watch
            seen_urls TEXT DEFAULT '',         -- newline-joined URLs already reported
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS usage_daily (
            day TEXT PRIMARY KEY,              -- YYYY-MM-DD
            llm_calls INTEGER DEFAULT 0,
            tool_calls INTEGER DEFAULT 0
        );
        """
    )
    conn.commit()
    conn.close()


# ── REMINDERS ─────────────────────────────────────────────────────────────────

def add_reminder(text: str, due_at: str, repeat: Optional[str] = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO reminders (text, due_at, repeat) VALUES (?, ?, ?)",
        (text, due_at, repeat),
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_pending_reminders() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM reminders WHERE status = 'pending' ORDER BY due_at ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_due_reminders(now_iso: Optional[str] = None) -> list:
    now_iso = now_iso or datetime.now().isoformat()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? ORDER BY due_at ASC",
        (now_iso,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_reminder_status(reminder_id: int, status: str):
    conn = get_conn()
    conn.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
    conn.commit()
    conn.close()


def reschedule_reminder(reminder_id: int, new_due_at: str):
    conn = get_conn()
    conn.execute("UPDATE reminders SET due_at = ? WHERE id = ?", (new_due_at, reminder_id))
    conn.commit()
    conn.close()


# ── GOALS ─────────────────────────────────────────────────────────────────────

def add_goal(title: str, detail: str = "", priority: int = 3) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO goals (title, detail, priority) VALUES (?, ?, ?)",
        (title, detail, priority),
    )
    conn.commit()
    gid = cur.lastrowid
    conn.close()
    return gid


def list_goals(status: str = "active") -> list:
    conn = get_conn()
    if status == "all":
        rows = conn.execute("SELECT * FROM goals ORDER BY priority ASC, updated_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM goals WHERE status = ? ORDER BY priority ASC, updated_at DESC",
            (status,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_goal(goal_id: int, **kwargs):
    if not kwargs:
        return
    kwargs["updated_at"] = datetime.now().isoformat()
    conn = get_conn()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    conn.execute(f"UPDATE goals SET {sets} WHERE id = ?", (*kwargs.values(), goal_id))
    conn.commit()
    conn.close()


# ── LESSONS ───────────────────────────────────────────────────────────────────

def add_lesson(lesson: str, situation: str = "", tags: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO lessons (situation, lesson, tags) VALUES (?, ?, ?)",
        (situation, lesson, tags),
    )
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid


def recent_lessons(limit: int = 10) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM lessons ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── SKILLS ────────────────────────────────────────────────────────────────────

def upsert_skill(name: str, when_to_use: str, steps: str) -> int:
    conn = get_conn()
    existing = conn.execute("SELECT id FROM skills WHERE name = ?", (name,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE skills SET when_to_use = ?, steps = ?, updated_at = ? WHERE id = ?",
            (when_to_use, steps, datetime.now().isoformat(), existing["id"]),
        )
        sid = existing["id"]
    else:
        cur = conn.execute(
            "INSERT INTO skills (name, when_to_use, steps) VALUES (?, ?, ?)",
            (name, when_to_use, steps),
        )
        sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def list_skills() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM skills ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── APPROVALS ─────────────────────────────────────────────────────────────────

def create_approval(tool_name: str, args: dict, summary: str, kind: str = "action") -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO approvals (kind, tool_name, args_json, summary) VALUES (?, ?, ?, ?)",
        (kind, tool_name, json.dumps(args), summary),
    )
    conn.commit()
    aid = cur.lastrowid
    conn.close()
    return aid


def get_approval(approval_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_pending_approvals() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_approval_status(approval_id: int, status: str, result: str = None):
    conn = get_conn()
    conn.execute(
        "UPDATE approvals SET status = ?, result = ?, decided_at = ? WHERE id = ?",
        (status, result, datetime.now().isoformat(), approval_id),
    )
    conn.commit()
    conn.close()


# ── PLANS / SUBTASKS ──────────────────────────────────────────────────────────

def create_plan(goal: str, rationale: str, steps: list) -> int:
    """Persist a plan and its ordered subtasks. `steps` is a list of dicts or strings."""
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO plans (goal, rationale) VALUES (?, ?)", (goal, rationale)
    )
    plan_id = cur.lastrowid
    for i, step in enumerate(steps):
        if isinstance(step, dict):
            desc = step.get("description") or step.get("step") or str(step)
            depends = ",".join(str(d) for d in (step.get("depends_on") or []))
        else:
            desc, depends = str(step), ""
        conn.execute(
            "INSERT INTO subtasks (plan_id, seq, description, depends_on) VALUES (?, ?, ?, ?)",
            (plan_id, i, desc, depends),
        )
    conn.commit()
    conn.close()
    return plan_id


def get_plan(plan_id: int) -> Optional[dict]:
    conn = get_conn()
    p = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if not p:
        conn.close()
        return None
    subs = conn.execute(
        "SELECT * FROM subtasks WHERE plan_id = ? ORDER BY seq ASC", (plan_id,)
    ).fetchall()
    conn.close()
    return {**dict(p), "subtasks": [dict(s) for s in subs]}


def list_open_plans() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM plans WHERE status = 'open' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_subtask(subtask_id: int, status: str, result: str = None):
    conn = get_conn()
    conn.execute(
        "UPDATE subtasks SET status = ?, result = ? WHERE id = ?",
        (status, result, subtask_id),
    )
    conn.commit()
    conn.close()


def set_plan_status(plan_id: int, status: str):
    conn = get_conn()
    conn.execute(
        "UPDATE plans SET status = ?, updated_at = ? WHERE id = ?",
        (status, datetime.now().isoformat(), plan_id),
    )
    conn.commit()
    conn.close()


# ── STRATEGIES (A/B optimizer) ────────────────────────────────────────────────

def record_strategy(grp: str, variant: str, success: bool):
    conn = get_conn()
    conn.execute(
        """INSERT INTO strategies (grp, variant, trials, successes, updated_at)
           VALUES (?, ?, 1, ?, ?)
           ON CONFLICT(grp, variant) DO UPDATE SET
             trials = trials + 1,
             successes = successes + ?,
             updated_at = ?""",
        (grp, variant, 1 if success else 0, datetime.now().isoformat(),
         1 if success else 0, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def strategy_leaderboard(grp: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM strategies WHERE grp = ? ORDER BY (CAST(successes AS REAL)/MAX(trials,1)) DESC, trials DESC",
        (grp,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def all_strategies(limit: int = 20) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM strategies ORDER BY trials DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── MONITORS ──────────────────────────────────────────────────────────────────

def add_monitor(topic: str) -> int:
    conn = get_conn()
    cur = conn.execute("INSERT INTO monitors (topic) VALUES (?)", (topic,))
    conn.commit()
    mid = cur.lastrowid
    conn.close()
    return mid


def list_monitors(active_only: bool = True) -> list:
    conn = get_conn()
    if active_only:
        rows = conn.execute("SELECT * FROM monitors WHERE active = 1 ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM monitors ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def deactivate_monitor(monitor_id: int):
    conn = get_conn()
    conn.execute("UPDATE monitors SET active = 0 WHERE id = ?", (monitor_id,))
    conn.commit()
    conn.close()


def mark_monitor_seen(monitor_id: int, urls: list):
    conn = get_conn()
    row = conn.execute("SELECT seen_urls FROM monitors WHERE id = ?", (monitor_id,)).fetchone()
    existing = (row["seen_urls"] if row else "") or ""
    merged = "\n".join(filter(None, existing.split("\n") + list(urls)))
    conn.execute("UPDATE monitors SET seen_urls = ? WHERE id = ?", (merged, monitor_id))
    conn.commit()
    conn.close()


# ── USAGE / BUDGET ────────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def incr_usage(llm: int = 0, tools: int = 0):
    day = _today()
    conn = get_conn()
    conn.execute(
        """INSERT INTO usage_daily (day, llm_calls, tool_calls) VALUES (?, ?, ?)
           ON CONFLICT(day) DO UPDATE SET
             llm_calls = llm_calls + ?, tool_calls = tool_calls + ?""",
        (day, llm, tools, llm, tools),
    )
    conn.commit()
    conn.close()


def usage_today() -> dict:
    day = _today()
    conn = get_conn()
    row = conn.execute("SELECT * FROM usage_daily WHERE day = ?", (day,)).fetchone()
    conn.close()
    return dict(row) if row else {"day": day, "llm_calls": 0, "tool_calls": 0}


# ── ACTION LOG ────────────────────────────────────────────────────────────────

def log_action(actor: str, tool_name: str, args: dict, result: str):
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO action_log (actor, tool_name, args_json, result) VALUES (?, ?, ?, ?)",
            (actor, tool_name, json.dumps(args, default=str)[:4000], str(result)[:4000]),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# Initialize on import.
init_agent_db()
