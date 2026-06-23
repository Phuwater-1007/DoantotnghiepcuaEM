"""Service lưu trữ thông tin nhận diện biển số xe (LPR) vào database.

Hỗ trợ cơ chế ghi nhận realtime:
- Lần đầu nhận diện được: INSERT sự kiện.
- Các frame tiếp theo nếu nhận diện được biển số tốt hơn (độ tin cậy cao hơn): UPDATE bản ghi cũ.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LPREvent:
    """Đại diện cho 1 sự kiện nhận diện biển số xe."""
    track_id: int
    vehicle_class: str
    license_plate: str
    confidence: float
    vehicle_image_path: str | None = None
    plate_image_path: str | None = None
    timestamp: float = field(default_factory=time.time)


class LPRPersistenceService:
    """Ghi nhận và cập nhật realtime các LPREvent vào bảng license_plate_events."""

    def __init__(self, db):
        self.db = db
        self._lock = threading.Lock()
        self._session_id: int | None = None
        self._source_id: int | None = None

    def bind_session(self, session_id: int, source_id: int) -> None:
        """Gắn session hiện tại — gọi khi bắt đầu phân tích."""
        with self._lock:
            self._session_id = session_id
            self._source_id = source_id
            logger.info("Bound LPRPersistenceService to session_id=%d, source_id=%d", session_id, source_id)

    def record(self, event: LPREvent) -> None:
        """Ghi nhận hoặc cập nhật biển số xe.
        
        Nếu track_id chưa tồn tại trong session: INSERT.
        Nếu đã tồn tại và confidence mới cao hơn: UPDATE.
        """
        with self._lock:
            session_id = self._session_id
            source_id = self._source_id

        if session_id is None:
            return

        try:
            # Kiểm tra xem xe này đã có bản ghi nào trong session này chưa
            row = self.db.fetchone(
                """
                SELECT id, confidence, license_plate 
                FROM license_plate_events 
                WHERE session_id = ? AND track_id = ?
                """,
                (session_id, event.track_id)
            )

            if row:
                old_id = int(row["id"])
                old_conf = float(row["confidence"])
                
                # Điều kiện cập nhật: Độ tin cậy cao hơn, hoặc kết quả trước đó quá ngắn/rác
                # (Ví dụ: biển số Việt Nam thường từ 7 ký tự trở lên)
                is_better = event.confidence > old_conf
                is_longer = len(event.license_plate) > len(row["license_plate"]) and event.confidence > 0.4
                
                if is_better or is_longer:
                    self.db.execute(
                        """
                        UPDATE license_plate_events
                        SET license_plate = ?,
                            confidence = ?,
                            vehicle_image_path = ?,
                            plate_image_path = ?
                        WHERE id = ?
                        """,
                        (
                            event.license_plate,
                            round(event.confidence, 4),
                            event.vehicle_image_path,
                            event.plate_image_path,
                            old_id
                        )
                    )
                    logger.debug(
                        "Updated LPR record for track_id=%d: %s (conf: %.2f -> %.2f)",
                        event.track_id, event.license_plate, old_conf, event.confidence
                    )
            else:
                # Chưa có thì INSERT mới
                self.db.execute(
                    """
                    INSERT INTO license_plate_events
                        (session_id, source_id, track_id, vehicle_class, license_plate, 
                         confidence, vehicle_image_path, plate_image_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        source_id or 0,
                        event.track_id,
                        event.vehicle_class,
                        event.license_plate,
                        round(event.confidence, 4),
                        event.vehicle_image_path,
                        event.plate_image_path
                    )
                )
                logger.debug("Inserted new LPR record for track_id=%d: %s", event.track_id, event.license_plate)
        except Exception:
            logger.exception("Failed to write/update LPR event for track_id=%d", event.track_id)

    def unbind(self) -> None:
        """Hủy gắn kết session."""
        with self._lock:
            self._session_id = None
            self._source_id = None

    def get_events_for_session(self, session_id: int, limit: int = 100) -> list[dict[str, Any]]:
        """Lấy danh sách biển số xe của một session."""
        rows = self.db.fetchall(
            """
            SELECT id, track_id, vehicle_class, license_plate, confidence,
                   vehicle_image_path, plate_image_path, datetime(created_at, '+7 hours') AS created_at
            FROM license_plate_events
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit)
        )
        return [
            {
                "id": int(row["id"]),
                "track_id": int(row["track_id"]),
                "vehicle_class": str(row["vehicle_class"]),
                "license_plate": str(row["license_plate"]),
                "confidence": round(float(row["confidence"]), 2),
                "vehicle_image_path": row["vehicle_image_path"],
                "plate_image_path": row["plate_image_path"],
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def clear_all(self) -> int:
        """Xóa toàn bộ dữ liệu biển số xe (phục vụ nút Reset của Admin)."""
        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM license_plate_events")
        count = int(row["cnt"]) if row else 0
        self.db.execute("DELETE FROM license_plate_events")
        try:
            self.db.execute("DELETE FROM sqlite_sequence WHERE name = 'license_plate_events'")
        except Exception:
            pass
        logger.info("Cleared all %d LPR records from database", count)
        return count
