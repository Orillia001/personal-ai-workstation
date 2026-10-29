"""Durable state for the local split-pane workbench."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


STATE_KEY = "layout-prototype"
MAX_STATE_BYTES = 4 * 1024 * 1024


class StateConflict(Exception):
    """A different workbench tab saved a newer revision."""


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS workbench_layout_state(
            key TEXT PRIMARY KEY,
            revision INTEGER NOT NULL,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    db.commit()


def load(db: sqlite3.Connection) -> dict:
    row = db.execute(
        "SELECT revision,state_json,updated_at FROM workbench_layout_state WHERE key=?",
        (STATE_KEY,),
    ).fetchone()
    if row is None:
        return {"revision": 0, "updated_at": None, "state": None}
    return {"revision": row[0], "updated_at": row[2], "state": json.loads(row[1])}


def save(db: sqlite3.Connection, state: dict, revision: int) -> dict:
    if type(revision) is not int or revision < 0:
        raise ValueError("界面状态版本无效")
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("界面状态格式无效")
    if not isinstance(state.get("boards"), list) or not isinstance(state.get("selection"), dict):
        raise ValueError("界面状态内容不完整")
    encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_STATE_BYTES:
        raise ValueError("界面状态超过 4 MiB 上限")
    updated_at = datetime.now(timezone.utc).isoformat()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT revision FROM workbench_layout_state WHERE key=?", (STATE_KEY,)
        ).fetchone()
        current = row[0] if row else 0
        if revision != current:
            raise StateConflict(f"其他页面已保存更新版本（当前版本 {current}）")
        next_revision = current + 1
        db.execute(
            """INSERT INTO workbench_layout_state(key,revision,state_json,updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET
                 revision=excluded.revision,state_json=excluded.state_json,
                 updated_at=excluded.updated_at""",
            (STATE_KEY, next_revision, encoded, updated_at),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"revision": next_revision, "updated_at": updated_at}
