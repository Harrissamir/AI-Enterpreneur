"""SQLite storage for leads, session state and daily token usage."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                persona TEXT NOT NULL,
                session_id TEXT NOT NULL,
                name TEXT, email TEXT, company TEXT, country TEXT,
                need TEXT, details TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                persona TEXT NOT NULL,
                created_at TEXT NOT NULL,
                turns INTEGER NOT NULL DEFAULT 0,
                lead_captured INTEGER NOT NULL DEFAULT 0,
                role_brief TEXT
            );
            CREATE TABLE IF NOT EXISTS usage (
                day TEXT PRIMARY KEY,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        self._db.commit()

    # --- sessions -------------------------------------------------------
    def session(self, session_id: str, persona: str) -> dict:
        with self._lock:
            row = self._db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if row is None:
                self._db.execute(
                    "INSERT INTO sessions(session_id, persona, created_at) VALUES (?,?,?)",
                    (session_id, persona, _now()),
                )
                self._db.commit()
                return {"session_id": session_id, "persona": persona, "turns": 0,
                        "lead_captured": False, "role_brief": None}
            return {**dict(row), "lead_captured": bool(row["lead_captured"])}

    def bump_turn(self, session_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE sessions SET turns = turns + 1 WHERE session_id=?", (session_id,))
            self._db.commit()

    def set_role_brief(self, session_id: str, brief: str) -> None:
        with self._lock:
            self._db.execute("UPDATE sessions SET role_brief=? WHERE session_id=?", (brief, session_id))
            self._db.commit()

    # --- leads ----------------------------------------------------------
    def add_lead(self, persona: str, session_id: str, lead: dict) -> int:
        details = {k: v for k, v in lead.items()
                   if k not in {"name", "email", "company", "country", "need"}}
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO leads(created_at, persona, session_id, name, email, company, country, need, details)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (_now(), persona, session_id, lead.get("name"), lead.get("email"), lead.get("company"),
                 lead.get("country"), lead.get("need"), json.dumps(details, ensure_ascii=False)),
            )
            self._db.execute("UPDATE sessions SET lead_captured=1 WHERE session_id=?", (session_id,))
            self._db.commit()
            return int(cur.lastrowid)

    def leads(self, persona: str | None = None, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM leads"
        args: tuple = ()
        if persona:
            sql += " WHERE persona=?"
            args = (persona,)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, (*args, limit)).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["details"] = json.loads(item["details"] or "{}")
            out.append(item)
        return out

    # --- usage ----------------------------------------------------------
    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO usage(day, input_tokens, output_tokens) VALUES (?,?,?) "
                "ON CONFLICT(day) DO UPDATE SET input_tokens=input_tokens+excluded.input_tokens, "
                "output_tokens=output_tokens+excluded.output_tokens",
                (_today(), input_tokens, output_tokens),
            )
            self._db.commit()

    def tokens_today(self) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT input_tokens + output_tokens AS t FROM usage WHERE day=?", (_today(),)
            ).fetchone()
        return int(row["t"]) if row else 0
