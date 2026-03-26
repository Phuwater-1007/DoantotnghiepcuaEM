"""Tests for stability and security fixes (daemon, media, SQLite, validation, dashboard)."""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from vehicle_counting_system.application.services.dashboard_service import DashboardService
from vehicle_counting_system.application.services.source_service import (
    SourceService,
    validate_source_paths,
)
from vehicle_counting_system.infrastructure.persistence.sqlite_db import SQLiteDatabase
from vehicle_counting_system.models.tracked_object import TrackedObject
from vehicle_counting_system.presentation.web.dependencies import to_media_url


class TestValidateSourcePaths(unittest.TestCase):
    def test_valid_video_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "test.mp4"
            video.write_bytes(b"fake mp4")
            config = Path(tmp) / "counting.json"
            config.write_text("{}")
            uri, cfg = validate_source_paths(str(video), str(config))
            self.assertTrue(Path(uri).is_absolute())
            self.assertIsNotNone(cfg)

    def test_missing_video_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nonexistent.mp4"
            with self.assertRaises(ValueError) as ctx:
                validate_source_paths(str(missing), None)
            self.assertIn("not found", str(ctx.exception))

    def test_optional_config_empty_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "test.mp4"
            video.write_bytes(b"x")
            uri, cfg = validate_source_paths(str(video), None)
            self.assertIsNone(cfg)

    def test_config_provided_but_missing_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "test.mp4"
            video.write_bytes(b"x")
            with self.assertRaises(ValueError) as ctx:
                validate_source_paths(str(video), str(Path(tmp) / "missing.json"))
            self.assertIn("not found", str(ctx.exception))


class TestActivateSourceAtomic(unittest.TestCase):
    def test_activate_single_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = SQLiteDatabase(Path(tmp) / "test.db")
            db.init_schema()
            db.execute(
                "INSERT INTO sources (name, source_type, source_uri, is_active) VALUES (?,?,?,?)",
                ("A", "video", "/a.mp4", 0),
            )
            db.execute(
                "INSERT INTO sources (name, source_type, source_uri, is_active) VALUES (?,?,?,?)",
                ("B", "video", "/b.mp4", 0),
            )
            svc = SourceService(db)
            svc.activate_source(1)
            row_a = db.fetchone("SELECT is_active FROM sources WHERE id=1")
            row_b = db.fetchone("SELECT is_active FROM sources WHERE id=2")
            self.assertEqual(row_a["is_active"], 1)
            self.assertEqual(row_b["is_active"], 0)


class TestCompletedSessionsToday(unittest.TestCase):
    @patch("vehicle_counting_system.application.services.dashboard_service.date")
    def test_counts_by_finished_at(self, mock_date):
        mock_date.today.return_value = date(2026, 3, 12)
        with tempfile.TemporaryDirectory() as tmp:
            db = SQLiteDatabase(Path(tmp) / "test.db")
            db.init_schema()
            db.execute(
                "INSERT INTO users (username, password_hash, full_name, role) VALUES (?,?,?,?)",
                ("u", "h", "U", "user"),
            )
            db.execute(
                "INSERT INTO sources (name, source_type, source_uri, is_active) VALUES (?,?,?,?)",
                ("S", "video", "/s.mp4", 1),
            )
            db.execute(
                """
                INSERT INTO analysis_sessions (source_id, started_by, status, started_at, finished_at)
                VALUES (1, 1, 'completed', '2026-03-11 10:00:00', '2026-03-12 02:00:00')
                """
            )
            db.execute(
                """
                INSERT INTO analysis_sessions (source_id, started_by, status, started_at, finished_at)
                VALUES (1, 1, 'stopped', '2026-03-11 23:00:00', '2026-03-12 00:05:00')
                """
            )
            db.execute(
                """
                INSERT INTO analysis_sessions (source_id, started_by, status, started_at, finished_at)
                VALUES (1, 1, 'completed', '2026-03-10 10:00:00', '2026-03-10 11:00:00')
                """
            )
            svc = SourceService(db)
            dash = DashboardService(db, svc)
            data = dash.get_dashboard_data()
            self.assertEqual(data["completed_sessions_today"], 2)


class TestTrackedObjectHistoryCap(unittest.TestCase):
    def test_history_capped(self):
        obj = TrackedObject(
            track_id=1,
            class_id=0,
            class_name="car",
            bbox=(0, 0, 10, 10),
            history=[],
        )
        for _ in range(200):
            obj.update((0, 0, 10, 10))
        self.assertLessEqual(len(obj.history), 128)


class TestToMediaUrl(unittest.TestCase):
    def test_output_video_under_output_dir_returns_filename(self):
        from vehicle_counting_system.configs.paths import OUTPUT_VIDEOS_DIR

        path = str(OUTPUT_VIDEOS_DIR / "session_5.mp4")
        url = to_media_url(path)
        self.assertEqual(url, "/media/session_5.mp4")

    def test_path_outside_output_dir_returns_none(self):
        url = to_media_url("/tmp/other.mp4")
        self.assertIsNone(url)

    def test_none_returns_none(self):
        self.assertIsNone(to_media_url(None))
