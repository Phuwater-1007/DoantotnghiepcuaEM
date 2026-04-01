from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from vehicle_counting_system.configs.paths import APP_DB_PATH, INPUT_VIDEOS_DIR
from vehicle_counting_system.utils.file_utils import ensure_dir


class SQLiteDatabase:
    def __init__(self, db_path: str | Path = APP_DB_PATH):
        self.db_path = Path(db_path)
        ensure_dir(self.db_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        with self.connect() as conn:
            conn.execute(query, params)

    def execute_and_get_id(self, query: str, params: tuple[Any, ...] = ()) -> int:
        with self.connect() as conn:
            cursor = conn.execute(query, params)
            return int(cursor.lastrowid)

    def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(query, params).fetchone()

    def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(query, params).fetchall()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'ready',
                    notes TEXT NOT NULL DEFAULT '',
                    counting_config_path TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS analysis_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL,
                    started_by INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT,
                    output_video_path TEXT,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    error_message TEXT,
                    FOREIGN KEY(source_id) REFERENCES sources(id),
                    FOREIGN KEY(started_by) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS report_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER UNIQUE NOT NULL,
                    report_date TEXT NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0,
                    per_class_json TEXT NOT NULL DEFAULT '{}',
                    peak_hour_label TEXT NOT NULL DEFAULT 'N/A',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES analysis_sessions(id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_uri ON sources(source_uri);

                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    ip_address TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );
                """
            )

    def seed_defaults(self, auth_service) -> None:
        import os
        admin_pass = os.getenv("DEFAULT_ADMIN_PASSWORD")
        is_demo = os.getenv("DEMO_MODE", "0").strip() == "1"
        if not admin_pass and is_demo:
            admin_pass = "admin123"

        if admin_pass:
            admin = self.fetchone("SELECT id FROM users WHERE username = ?", ("admin",))
            if admin is None:
                self.execute(
                    """
                    INSERT INTO users (username, password_hash, full_name, role)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("admin", auth_service.hash_password(admin_pass), "System Admin", "admin"),
                )

        if is_demo:
            demo_user = self.fetchone("SELECT id FROM users WHERE username = ?", ("demo",))
            if demo_user is None:
                self.execute(
                    """
                    INSERT INTO users (username, password_hash, full_name, role)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("demo", auth_service.hash_password("demo123"), "Demo Operator", "user"),
                )

            demo_source = self.fetchone("SELECT id FROM sources WHERE name = ?", ("Demo Video",))
            if demo_source is None:
                default_video = INPUT_VIDEOS_DIR / "test.mp4"
                self.execute(
                    """
                    INSERT INTO sources (name, source_type, source_uri, is_active, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "Demo Video",
                        "video",
                        str(default_video),
                        1,
                        "ready",
                        "Default thesis demo source",
                    ),
                )

    def recover_stale_sessions(self) -> int:
        """Mark any 'running' or 'queued' sessions as 'failed' (server restarted)."""
        stale = self.fetchall(
            "SELECT id FROM analysis_sessions WHERE status IN ('running', 'queued')"
        )
        if not stale:
            return 0
        self.execute(
            """
            UPDATE analysis_sessions
            SET status = 'failed',
                finished_at = CURRENT_TIMESTAMP,
                error_message = 'Server restarted – phiên bị gián đoạn.'
            WHERE status IN ('running', 'queued')
            """
        )
        return len(stale)

    def fix_report_timezone_data(self) -> int:
        """Recalculate report_date and peak_hour_label using localtime conversion.

        Fixes data that was previously saved using raw UTC timestamps.
        Safe to run multiple times (idempotent).
        """
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE report_snapshots
                SET report_date = date(datetime(
                        (SELECT sess.finished_at FROM analysis_sessions sess WHERE sess.id = report_snapshots.session_id),
                        'localtime'
                    )),
                    peak_hour_label = substr(datetime(
                        (SELECT sess.finished_at FROM analysis_sessions sess WHERE sess.id = report_snapshots.session_id),
                        'localtime'
                    ), 12, 2) || ':00'
                WHERE EXISTS (SELECT 1 FROM analysis_sessions sess WHERE sess.id = report_snapshots.session_id AND sess.finished_at IS NOT NULL)
                """
            )
            return cursor.rowcount

