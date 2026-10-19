from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class LocalStorage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recycle_bin (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bin_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def save_strategy(self, name: str, payload: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO strategy (name, payload)
                VALUES (?, ?)
                ON CONFLICT(name) DO UPDATE SET payload=excluded.payload
                """,
                (name, json.dumps(payload, ensure_ascii=False)),
            )

    def list_strategy(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT name, payload, created_at FROM strategy ORDER BY id DESC").fetchall()
        return [{"name": r[0], "payload": json.loads(r[1]), "created_at": r[2]} for r in rows]

    def add_recycle(self, bin_type: str, payload: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO recycle_bin (bin_type, payload) VALUES (?, ?)",
                (bin_type, json.dumps(payload, ensure_ascii=False)),
            )

    def list_recycle(self, bin_type: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if bin_type:
                rows = conn.execute(
                    "SELECT id, bin_type, payload, created_at FROM recycle_bin WHERE bin_type=? ORDER BY id DESC",
                    (bin_type,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT id, bin_type, payload, created_at FROM recycle_bin ORDER BY id DESC").fetchall()
        return [
            {"id": r[0], "bin_type": r[1], "payload": json.loads(r[2]), "created_at": r[3]}
            for r in rows
        ]

    def restore_recycle(self, bin_type: str, payload: dict[str, Any]) -> bool:
        with self._conn() as conn:
            rows = conn.execute("SELECT id,payload FROM recycle_bin WHERE bin_type=? ORDER BY id DESC", (bin_type,)).fetchall()
            for row in rows:
                if json.loads(row[1]) == payload:
                    conn.execute("DELETE FROM recycle_bin WHERE id=?", (row[0],))
                    return True
        return False
