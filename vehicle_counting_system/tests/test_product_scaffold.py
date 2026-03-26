import hashlib
import tempfile
import unittest
from pathlib import Path

from vehicle_counting_system.application.services.auth_service import AuthService
from vehicle_counting_system.infrastructure.persistence.sqlite_db import SQLiteDatabase


class TestProductScaffold(unittest.TestCase):
    def test_database_bootstrap_seeds_default_users(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = SQLiteDatabase(Path(tmp_dir) / "app.db")
            auth = AuthService(db)
            db.init_schema()
            db.seed_defaults(auth)

            admin = auth.authenticate("admin", "admin123")
            demo = auth.authenticate("demo", "demo123")

            self.assertIsNotNone(admin)
            self.assertIsNotNone(demo)
            self.assertEqual(admin.role, "admin")
            self.assertEqual(demo.role, "user")

    def test_auth_service_supports_legacy_sha256_hashes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = SQLiteDatabase(Path(tmp_dir) / "app.db")
            auth = AuthService(db)
            db.init_schema()
            db.execute(
                """
                INSERT INTO users (username, password_hash, full_name, role)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "legacy",
                    hashlib.sha256("s3cret123".encode("utf-8")).hexdigest(),
                    "Legacy User",
                    "user",
                ),
            )

            user = auth.authenticate("legacy", "s3cret123")

            self.assertIsNotNone(user)
            self.assertEqual(user.username, "legacy")


if __name__ == "__main__":
    unittest.main()
