import sqlite3
from datetime import datetime
from typing import Any

from .config import DB_PATH


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                system_prompt TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL,
                score INTEGER NOT NULL,
                tp INTEGER NOT NULL,
                fp INTEGER NOT NULL,
                fn INTEGER NOT NULL,
                tn INTEGER NOT NULL,
                deleted_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in con.execute("PRAGMA table_info(scores)").fetchall()}
        if "system_prompt" not in columns:
            con.execute("ALTER TABLE scores ADD COLUMN system_prompt TEXT NOT NULL DEFAULT ''")
        con.commit()


def save_score(username: str, system_prompt: str, prompt: str, result: dict[str, Any]) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO scores(username, system_prompt, prompt, score, tp, fp, fn, tn, deleted_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                system_prompt,
                prompt,
                result["score"],
                result["tp"],
                result["fp"],
                result["fn"],
                result["tn"],
                result["deleted_count"],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        con.commit()


def leaderboard_rows() -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT username, score, tp, fp, fn, tn, deleted_count, created_at
            FROM scores
            ORDER BY score DESC, fn ASC, fp ASC, created_at ASC
            LIMIT 20
            """
        ).fetchall()
    return [dict(row) for row in rows]
