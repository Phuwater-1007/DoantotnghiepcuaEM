from __future__ import annotations

import hashlib
import hmac
import os

from vehicle_counting_system.domain.models.entities import User


class AuthService:
    _PBKDF2_ALGORITHM = "sha256"
    _PBKDF2_ITERATIONS = 120_000
    _SALT_BYTES = 16

    def __init__(self, db):
        self.db = db

    def hash_password(self, password: str) -> str:
        salt = os.urandom(self._SALT_BYTES).hex()
        digest = hashlib.pbkdf2_hmac(
            self._PBKDF2_ALGORITHM,
            password.encode("utf-8"),
            bytes.fromhex(salt),
            self._PBKDF2_ITERATIONS,
        ).hex()
        return f"pbkdf2_{self._PBKDF2_ALGORITHM}${self._PBKDF2_ITERATIONS}${salt}${digest}"

    def verify_password(self, password: str, stored_hash: str) -> bool:
        if stored_hash.startswith("pbkdf2_sha256$"):
            try:
                _, iterations, salt, expected_digest = stored_hash.split("$", 3)
                computed_digest = hashlib.pbkdf2_hmac(
                    self._PBKDF2_ALGORITHM,
                    password.encode("utf-8"),
                    bytes.fromhex(salt),
                    int(iterations),
                ).hex()
            except Exception:
                return False
            return hmac.compare_digest(computed_digest, expected_digest)

        legacy_digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy_digest, stored_hash)

    def authenticate(self, username: str, password: str) -> User | None:
        row = self.db.fetchone(
            """
            SELECT id, username, full_name, role, is_active, password_hash
            FROM users
            WHERE username = ?
            """,
            (username,),
        )
        if row is None:
            return None
        if not bool(row["is_active"]):
            return None
        if not self.verify_password(password, str(row["password_hash"])):
            return None
        return User(
            id=int(row["id"]),
            username=str(row["username"]),
            full_name=str(row["full_name"]),
            role=str(row["role"]),
            is_active=bool(row["is_active"]),
        )

    def get_user(self, user_id: int) -> User | None:
        row = self.db.fetchone(
            """
            SELECT id, username, full_name, role, is_active
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        if row is None:
            return None
        return User(
            id=int(row["id"]),
            username=str(row["username"]),
            full_name=str(row["full_name"]),
            role=str(row["role"]),
            is_active=bool(row["is_active"]),
        )

    def list_users(self) -> list[User]:
        rows = self.db.fetchall(
            """
            SELECT id, username, full_name, role, is_active
            FROM users
            ORDER BY id ASC
            """
        )
        return [
            User(
                id=int(row["id"]),
                username=str(row["username"]),
                full_name=str(row["full_name"]),
                role=str(row["role"]),
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    def create_user(self, username: str, password: str, full_name: str, role: str) -> None:
        normalized_role = role.strip().lower()
        if normalized_role not in {"admin", "user"}:
            raise ValueError("Role must be either 'admin' or 'user'.")

        cleaned_username = username.strip()
        cleaned_full_name = full_name.strip()
        if not cleaned_username:
            raise ValueError("Username is required.")
        if not cleaned_full_name:
            raise ValueError("Full name is required.")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")

        self.db.execute(
            """
            INSERT INTO users (username, password_hash, full_name, role)
            VALUES (?, ?, ?, ?)
            """,
            (cleaned_username, self.hash_password(password), cleaned_full_name, normalized_role),
        )

    def toggle_user_active(self, user_id: int) -> bool:
        """Toggle is_active for a user. Returns new is_active value."""
        user = self.get_user(user_id)
        if user is None:
            raise ValueError("Người dùng không tồn tại.")
        if user.username == "admin":
            raise ValueError("Không thể vô hiệu hóa tài khoản admin chính.")
        new_active = 0 if user.is_active else 1
        self.db.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (new_active, user_id),
        )
        return bool(new_active)

    def delete_user(self, user_id: int) -> None:
        """Delete a user account. Cannot delete the primary admin."""
        user = self.get_user(user_id)
        if user is None:
            raise ValueError("Người dùng không tồn tại.")
        if user.username == "admin":
            raise ValueError("Không thể xóa tài khoản admin chính.")
        self.db.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def reset_password(self, user_id: int, new_password: str) -> str:
        """Reset password for a user. Returns username."""
        user = self.get_user(user_id)
        if user is None:
            raise ValueError("Người dùng không tồn tại.")
        if len(new_password) < 8:
            raise ValueError("Mật khẩu mới phải có ít nhất 8 ký tự.")
        self.db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (self.hash_password(new_password), user_id),
        )
        return user.username
