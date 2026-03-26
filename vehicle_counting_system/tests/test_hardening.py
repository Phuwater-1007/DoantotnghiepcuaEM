import os
import unittest
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from vehicle_counting_system.infrastructure.persistence.sqlite_db import SQLiteDatabase
from vehicle_counting_system.application.services.auth_service import AuthService
from vehicle_counting_system.application.services.source_service import SourceService
from vehicle_counting_system.application.services.report_service import ReportService
from vehicle_counting_system.application.services.dashboard_service import DashboardService
from vehicle_counting_system.application.services.monitoring_service import MonitoringService
from vehicle_counting_system.application.bootstrap import AppContainer
from vehicle_counting_system.presentation.web.app import create_app
import vehicle_counting_system.configs.paths as paths

class TestHardeningIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DEMO_MODE"] = "1"
        os.environ["DEFAULT_ADMIN_PASSWORD"] = "testpass"
        os.environ["WEB_SESSION_SECRET"] = "secret"
        
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        
        # Override paths for this test run
        self.orig_db_path = paths.APP_DB_PATH
        self.orig_input_dir = paths.INPUT_VIDEOS_DIR
        paths.APP_DB_PATH = self.tmp_path / "test.db"
        paths.INPUT_VIDEOS_DIR = self.tmp_path / "inputs"
        paths.INPUT_VIDEOS_DIR.mkdir()

        # Build custom container
        self.db = SQLiteDatabase(paths.APP_DB_PATH)
        self.auth = AuthService(self.db)
        self.source = SourceService(self.db)
        self.report = ReportService(self.db)
        self.dashboard = DashboardService(self.db, self.source)
        self.monitoring = MonitoringService(self.db, self.source, self.report)

        self.db.init_schema()
        self.db.seed_defaults(self.auth)
        
        self.container = AppContainer(
            db=self.db,
            auth_service=self.auth,
            source_service=self.source,
            dashboard_service=self.dashboard,
            report_service=self.report,
            monitoring_service=self.monitoring,
        )
        
        self.app = create_app()
        self.app.state.container = self.container
        self.client = TestClient(self.app)

    def tearDown(self):
        paths.APP_DB_PATH = self.orig_db_path
        paths.INPUT_VIDEOS_DIR = self.orig_input_dir
        self.tmp.cleanup()

    def _login(self):
        # GET login page to get CSRF token
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        # Very simple extraction of the hidden csrf_token field
        token = ""
        if 'name="csrf_token"' in html:
            parts = html.split('name="csrf_token" value="')
            if len(parts) > 1:
                token = parts[1].split('"')[0]
                
        resp = self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass", "csrf_token": token},
            follow_redirects=False,
        )
        if resp.status_code not in (200, 303, 302):
            print(f"LOGIN FAILED. Status: {resp.status_code}, Body: {resp.text}, Token used: {token}")
        self.assertTrue(resp.status_code in (200, 303, 302))

    def test_5_4_logout_post_and_csrf(self):
        # GET /logout should fail (405 Method Not Allowed)
        resp = self.client.get("/logout", follow_redirects=False)
        self.assertEqual(resp.status_code, 405)
        
        # test CSRF token is required for POST /users
        resp = self.client.post("/users", data={"username": "test", "password": "x", "full_name": "x", "role": "user"})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("CSRF", resp.json().get("error", ""))

    def test_5_3_roi_validation_rejects(self):
        self._login()
        self.db.execute("INSERT INTO sources (name, source_type, source_uri) VALUES ('test_roi', 'video', 'test.mp4')")
        source_id = self.db.fetchone("SELECT id FROM sources ORDER BY id DESC")["id"]
        
        # Invalid ROI (<3 points)
        payload = {
            "width": 100, "height": 100,
            "roi": [[0,0], [10,10]],
            "line": {"start": [0,0], "end": [10,10]}
        }
        resp = self.client.post(f"/api/sources/{source_id}/config", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("ít nhất 3 điểm", resp.json().get("error", ""))
        
        # Invalid line (same start/end)
        payload = {
            "width": 100, "height": 100,
            "roi": [[0,0], [10,0], [10,10], [0,10]],
            "line": {"start": [5,5], "end": [5,5]}
        }
        resp = self.client.post(f"/api/sources/{source_id}/config", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("trùng nhau", resp.json().get("error", ""))

    def test_5_1_upload_duplicate_filename(self):
        self._login()
        fake_video = b"test video content"
        resp1 = self.client.post(
            "/api/sources/upload",
            files={"file": ("video.mp4", fake_video, "video/mp4")}
        )
        self.assertTrue(resp1.json().get("ok"))
        p1 = resp1.json()["path"]
        
        # Upload 2 with same name
        resp2 = self.client.post(
            "/api/sources/upload",
            files={"file": ("video.mp4", fake_video, "video/mp4")}
        )
        self.assertTrue(resp2.json().get("ok"))
        p2 = resp2.json()["path"]
        
        self.assertNotEqual(p1, p2)
        self.assertTrue("video_1.mp4" in p2)

    def test_5_2_and_5_5_session_lifecycle(self):
        self.db.execute("INSERT INTO sources (name, source_type, source_uri) VALUES ('test', 'video', 'test.mp4')")
        source_id = self.db.fetchone("SELECT id FROM sources ORDER BY id DESC")["id"]
        
        self.db.execute("INSERT INTO analysis_sessions (source_id, started_by, status) VALUES (?, 1, 'running')", (source_id,))
        session_id = self.db.fetchone("SELECT id FROM analysis_sessions ORDER BY id DESC")["id"]
        
        # Call recover_stale_sessions manually
        count = self.db.recover_stale_sessions()
        self.assertEqual(count, 1)
        status = self.db.fetchone("SELECT status FROM analysis_sessions WHERE id=?", (session_id,))["status"]
        self.assertEqual(status, "failed")
        
        # Assert no reports for failed sessions
        reports_failed = self.db.fetchall("SELECT * FROM report_snapshots WHERE session_id=?", (session_id,))
        self.assertEqual(len(reports_failed), 0)
        
        # Make a completed session and verify report can be saved
        self.db.execute("INSERT INTO analysis_sessions (source_id, started_by, status, finished_at) VALUES (?, 1, 'completed', '2023-01-01 12:00:00')", (source_id,))
        session_id_2 = self.db.fetchone("SELECT id FROM analysis_sessions ORDER BY id DESC")["id"]
        self.report.save_report_snapshot(session_id_2, "2023-01-01 12:00:00", 5, {"car": 5})
        
        reports_completed = self.db.fetchall("SELECT * FROM report_snapshots WHERE session_id=?", (session_id_2,))
        self.assertEqual(len(reports_completed), 1)

if __name__ == "__main__":
    unittest.main()
