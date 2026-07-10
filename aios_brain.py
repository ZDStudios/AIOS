#!/usr/bin/env python3
"""
AIOS Brain — the durable state layer for The AI OS.

One SQLite file (`.aios/aios.db`) backs four subsystems that used to be scattered
JSON blobs (or didn't exist at all):

  memory   Persistent cross-session memory with full-text search (FTS5), so the
           Active Memory sub-agent can pull *relevant* context on every turn
           instead of dumping the whole file into the system prompt.
  tasks    Task Brain — one scheduler for cron jobs, subagent prompts, and
           background CLI processes. Survives restarts; every run is recorded.
  flows    TaskFlow — durable multi-step flows with state + revision tracking.
           A flow that dies mid-run resumes from its last committed step.
  skills   The self-improving loop's ledger of skills the system taught itself.
  audit    Every shell command an agent ran, because full-control mode is on.

Pure standard library. Safe to import from threads: one connection, one lock,
WAL journal.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("AIOS_ROOT", Path(__file__).resolve().parent))


def _db_path() -> Path:
    """Profile-aware: `AIOS_PROFILE=work` gives an isolated brain (Hermes-style profiles)."""
    profile = os.environ.get("AIOS_PROFILE", "").strip()
    base = ROOT / ".aios"
    if profile and profile != "default":
        base = base / "profiles" / re.sub(r"[^A-Za-z0-9_.-]", "_", profile)
    base.mkdir(parents=True, exist_ok=True)
    return base / "aios.db"


_conn: sqlite3.Connection | None = None
_lock = threading.RLock()
HAS_FTS = False


def db() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(str(_db_path()), check_same_thread=False, timeout=15)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _init(_conn)
        return _conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
  id INTEGER PRIMARY KEY, text TEXT NOT NULL, kind TEXT DEFAULT 'fact',
  source TEXT DEFAULT '', ts REAL NOT NULL);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'agent',
  target TEXT DEFAULT 'brain', prompt TEXT DEFAULT '', command TEXT DEFAULT '',
  cron TEXT DEFAULT '', every_minutes INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1,
  last_run REAL DEFAULT 0, last_status TEXT DEFAULT '', last_output TEXT DEFAULT '',
  created REAL NOT NULL);

CREATE TABLE IF NOT EXISTS task_runs (
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, started REAL, finished REAL,
  status TEXT, output TEXT);
CREATE INDEX IF NOT EXISTS idx_runs_task ON task_runs(task_id, started DESC);

CREATE TABLE IF NOT EXISTS flows (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, spec TEXT NOT NULL,
  status TEXT DEFAULT 'pending', cursor INTEGER DEFAULT 0, revision INTEGER DEFAULT 0,
  state TEXT DEFAULT '{}', error TEXT DEFAULT '', created REAL, updated REAL);

CREATE TABLE IF NOT EXISTS flow_revisions (
  id INTEGER PRIMARY KEY, flow_id INTEGER NOT NULL, revision INTEGER NOT NULL,
  cursor INTEGER, status TEXT, state TEXT, note TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS idx_frev ON flow_revisions(flow_id, revision DESC);

CREATE TABLE IF NOT EXISTS skills_learned (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, path TEXT, task TEXT, uses INTEGER DEFAULT 0,
  ts REAL);

CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, ts REAL, actor TEXT, action TEXT, detail TEXT, ok INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts DESC);
"""


def _init(c: sqlite3.Connection):
    global HAS_FTS
    c.executescript(SCHEMA)
    try:
        c.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
          text, content='memory', content_rowid='id', tokenize='porter unicode61');
        CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memory BEGIN
          INSERT INTO memory_fts(rowid, text) VALUES (new.id, new.text); END;
        CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memory BEGIN
          INSERT INTO memory_fts(memory_fts, rowid, text) VALUES('delete', old.id, old.text); END;
        CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON memory BEGIN
          INSERT INTO memory_fts(memory_fts, rowid, text) VALUES('delete', old.id, old.text);
          INSERT INTO memory_fts(rowid, text) VALUES (new.id, new.text); END;
        """)
        HAS_FTS = True
    except sqlite3.OperationalError:
        HAS_FTS = False  # sqlite built without FTS5 — mem_search falls back to LIKE
    c.commit()


# --------------------------------------------------------------------------- #
# Memory (Active Memory reads this on every turn)                              #
# --------------------------------------------------------------------------- #
def mem_add(text: str, kind: str = "fact", source: str = "") -> int:
    text = (text or "").strip()
    if not text:
        return 0
    with _lock:
        c = db()
        dup = c.execute("SELECT id FROM memory WHERE text=?", (text,)).fetchone()
        if dup:
            return dup["id"]
        cur = c.execute("INSERT INTO memory(text,kind,source,ts) VALUES(?,?,?,?)",
                        (text, kind, source, time.time()))
        c.commit()
        return cur.lastrowid


_FTS_SAFE = re.compile(r"[A-Za-z0-9_]{2,}")


def mem_search(query: str, k: int = 6) -> list[dict]:
    """Relevance search. Free — no LLM call. This is what makes Active Memory cheap."""
    with _lock:
        c = db()
        terms = _FTS_SAFE.findall(query or "")
        if not terms:
            return []
        if HAS_FTS:
            # OR the terms so a partial topic match still recalls; bm25 ranks.
            expr = " OR ".join(terms[:12])
            try:
                rows = c.execute(
                    "SELECT m.id, m.text, m.kind, m.ts, bm25(memory_fts) AS score "
                    "FROM memory_fts JOIN memory m ON m.id = memory_fts.rowid "
                    "WHERE memory_fts MATCH ? ORDER BY score LIMIT ?", (expr, k)).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass
        like = " OR ".join(["text LIKE ?"] * min(len(terms), 6))
        args = [f"%{t}%" for t in terms[:6]] + [k]
        rows = c.execute(f"SELECT id,text,kind,ts FROM memory WHERE {like} "
                         f"ORDER BY ts DESC LIMIT ?", args).fetchall()
        return [dict(r) for r in rows]


def mem_all(limit: int = 200) -> list[dict]:
    with _lock:
        rows = db().execute("SELECT id,text,kind,source,ts FROM memory ORDER BY ts DESC LIMIT ?",
                            (limit,)).fetchall()
        return [dict(r) for r in rows]


def mem_delete(mid: int):
    with _lock:
        c = db()
        c.execute("DELETE FROM memory WHERE id=?", (mid,))
        c.commit()


def mem_count() -> int:
    with _lock:
        return db().execute("SELECT COUNT(*) n FROM memory").fetchone()["n"]


# --------------------------------------------------------------------------- #
# Audit — full-control mode means we record what the agents actually did       #
# --------------------------------------------------------------------------- #
def audit(actor: str, action: str, detail: str = "", ok: bool = True):
    with _lock:
        c = db()
        c.execute("INSERT INTO audit(ts,actor,action,detail,ok) VALUES(?,?,?,?,?)",
                  (time.time(), actor, action, str(detail)[:4000], 1 if ok else 0))
        c.commit()


def audit_tail(n: int = 100) -> list[dict]:
    with _lock:
        rows = db().execute("SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (n,)).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Task Brain — cron + interval + agent prompts + background CLI, one scheduler #
# --------------------------------------------------------------------------- #
def _field_match(expr: str, val: int, lo: int, hi: int) -> bool:
    expr = expr.strip()
    if expr in ("*", "?"):
        return True
    for part in expr.split(","):
        step = 1
        if "/" in part:
            part, _, s = part.partition("/")
            if not s.isdigit() or int(s) == 0:
                return False
            step = int(s)
        if part in ("*", ""):
            start, end = lo, hi
        elif "-" in part.lstrip("-"):
            a, _, b = part.partition("-")
            if not (a.strip().isdigit() and b.strip().isdigit()):
                return False
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
        else:
            return False
        if start <= val <= end and (val - start) % step == 0:
            return True
    return False


def cron_match(expr: str, when: datetime | None = None) -> bool:
    """Minimal 5-field cron: minute hour day-of-month month day-of-week (0/7=Sun)."""
    parts = (expr or "").split()
    if len(parts) != 5:
        return False
    t = when or datetime.now()
    dow = t.weekday()  # Mon=0
    cron_dow = (dow + 1) % 7  # cron: Sun=0
    checks = [
        _field_match(parts[0], t.minute, 0, 59),
        _field_match(parts[1], t.hour, 0, 23),
        _field_match(parts[2], t.day, 1, 31),
        _field_match(parts[3], t.month, 1, 12),
        _field_match(parts[4].replace("7", "0"), cron_dow, 0, 6),
    ]
    return all(checks)


def task_add(name: str, kind: str = "agent", target: str = "brain", prompt: str = "",
             command: str = "", cron: str = "", every_minutes: int = 0, enabled: bool = True) -> int:
    with _lock:
        c = db()
        cur = c.execute(
            "INSERT INTO tasks(name,kind,target,prompt,command,cron,every_minutes,enabled,created) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (name, kind, target, prompt, command, cron, int(every_minutes or 0),
             1 if enabled else 0, time.time()))
        c.commit()
        return cur.lastrowid


def task_list() -> list[dict]:
    with _lock:
        rows = db().execute("SELECT * FROM tasks ORDER BY created DESC").fetchall()
        return [dict(r) for r in rows]


def task_get(tid: int) -> dict | None:
    with _lock:
        r = db().execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        return dict(r) if r else None


def task_update(tid: int, **fields):
    allowed = {"name", "kind", "target", "prompt", "command", "cron", "every_minutes",
               "enabled", "last_run", "last_status", "last_output"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    with _lock:
        c = db()
        c.execute(f"UPDATE tasks SET {','.join(k + '=?' for k in sets)} WHERE id=?",
                  (*sets.values(), tid))
        c.commit()


def task_delete(tid: int):
    with _lock:
        c = db()
        c.execute("DELETE FROM tasks WHERE id=?", (tid,))
        c.execute("DELETE FROM task_runs WHERE task_id=?", (tid,))
        c.commit()


def task_due(t: dict, now: float | None = None) -> bool:
    if not t.get("enabled"):
        return False
    now = now or time.time()
    if t.get("cron"):
        # Fire at most once per minute-slot.
        if now - (t.get("last_run") or 0) < 60:
            return False
        return cron_match(t["cron"])
    every = int(t.get("every_minutes") or 0)
    if every <= 0:
        return False
    return now - (t.get("last_run") or 0) >= every * 60


def run_add(task_id: int, started: float, status: str, output: str) -> int:
    with _lock:
        c = db()
        cur = c.execute("INSERT INTO task_runs(task_id,started,finished,status,output) "
                        "VALUES(?,?,?,?,?)", (task_id, started, time.time(), status, output[:8000]))
        c.commit()
        return cur.lastrowid


def runs_for(task_id: int, n: int = 20) -> list[dict]:
    with _lock:
        rows = db().execute("SELECT * FROM task_runs WHERE task_id=? ORDER BY started DESC LIMIT ?",
                            (task_id, n)).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# TaskFlow — durable multi-step flows with state + revision tracking           #
# --------------------------------------------------------------------------- #
def flow_create(name: str, steps: list[dict]) -> int:
    """steps: [{"agent": "opencode", "prompt": "..."} , ...] — each step's output is
    fed to the next as `input`. State is committed after every step, so a restart
    resumes at the cursor instead of replaying work."""
    now = time.time()
    with _lock:
        c = db()
        cur = c.execute("INSERT INTO flows(name,spec,status,cursor,revision,state,created,updated) "
                        "VALUES(?,?,'pending',0,0,'{}',?,?)",
                        (name, json.dumps(steps), now, now))
        c.commit()
        fid = cur.lastrowid
    flow_commit(fid, cursor=0, status="pending", state={}, note="created")
    return fid


def flow_get(fid: int) -> dict | None:
    with _lock:
        r = db().execute("SELECT * FROM flows WHERE id=?", (fid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["spec"] = json.loads(d["spec"] or "[]")
    d["state"] = json.loads(d["state"] or "{}")
    return d


def flow_list() -> list[dict]:
    with _lock:
        rows = db().execute("SELECT id,name,status,cursor,revision,error,created,updated "
                            "FROM flows ORDER BY created DESC").fetchall()
        return [dict(r) for r in rows]


def flow_commit(fid: int, *, cursor: int, status: str, state: dict, note: str = "",
                error: str = "") -> int:
    """Atomically advance a flow and snapshot the new state as a revision."""
    with _lock:
        c = db()
        row = c.execute("SELECT revision FROM flows WHERE id=?", (fid,)).fetchone()
        rev = (row["revision"] if row else 0) + 1
        st = json.dumps(state)
        c.execute("UPDATE flows SET cursor=?,status=?,state=?,revision=?,updated=?,error=? "
                  "WHERE id=?", (cursor, status, st, rev, time.time(), error, fid))
        c.execute("INSERT INTO flow_revisions(flow_id,revision,cursor,status,state,note,ts) "
                  "VALUES(?,?,?,?,?,?,?)", (fid, rev, cursor, status, st, note, time.time()))
        c.commit()
        return rev


def flow_revisions(fid: int, n: int = 50) -> list[dict]:
    with _lock:
        rows = db().execute("SELECT revision,cursor,status,note,ts FROM flow_revisions "
                            "WHERE flow_id=? ORDER BY revision DESC LIMIT ?", (fid, n)).fetchall()
        return [dict(r) for r in rows]


def flow_resumable() -> list[int]:
    """Flows that were mid-flight when the process died."""
    with _lock:
        rows = db().execute("SELECT id FROM flows WHERE status IN ('pending','running')").fetchall()
        return [r["id"] for r in rows]


def flow_delete(fid: int):
    with _lock:
        c = db()
        c.execute("DELETE FROM flows WHERE id=?", (fid,))
        c.execute("DELETE FROM flow_revisions WHERE flow_id=?", (fid,))
        c.commit()


# --------------------------------------------------------------------------- #
# Self-improving skill loop ledger                                             #
# --------------------------------------------------------------------------- #
def skill_add(name: str, path: str, task: str = "") -> int:
    with _lock:
        c = db()
        c.execute("INSERT OR REPLACE INTO skills_learned(name,path,task,ts) VALUES(?,?,?,?)",
                  (name, path, task[:500], time.time()))
        c.commit()
        return c.execute("SELECT id FROM skills_learned WHERE name=?", (name,)).fetchone()["id"]


def skill_list() -> list[dict]:
    with _lock:
        rows = db().execute("SELECT * FROM skills_learned ORDER BY ts DESC").fetchall()
        return [dict(r) for r in rows]


def stats() -> dict:
    with _lock:
        c = db()
        q = lambda s: c.execute(s).fetchone()[0]  # noqa: E731
        return {
            "memory": q("SELECT COUNT(*) FROM memory"),
            "tasks": q("SELECT COUNT(*) FROM tasks"),
            "task_runs": q("SELECT COUNT(*) FROM task_runs"),
            "flows": q("SELECT COUNT(*) FROM flows"),
            "skills_learned": q("SELECT COUNT(*) FROM skills_learned"),
            "audit": q("SELECT COUNT(*) FROM audit"),
            "fts5": HAS_FTS,
            "db": str(_db_path()),
        }


if __name__ == "__main__":
    import sys
    db()
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        print(json.dumps(stats(), indent=2))
    else:
        print(json.dumps(stats(), indent=2))
