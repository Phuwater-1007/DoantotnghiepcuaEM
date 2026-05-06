"""Service ghi chi tiết từng xe đếm được vào database.

Batch insert để giảm tải I/O cho SQLite trong quá trình
stream/phân tích real-time.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, List

from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)

# Flush mỗi N records hoặc mỗi T giây (tuỳ điều kiện nào đến trước).
# Batch=1 đảm bảo mất điện / crash chỉ mất tối đa 1 xe.
_BATCH_SIZE = 1
_FLUSH_INTERVAL_SECONDS = 1.0


@dataclass
class CountEvent:
    """Đại diện cho 1 xe vừa được đếm qua counting line."""
    track_id: int
    class_name: str
    confidence: float
    direction: str       # p1_to_p2 | p2_to_p1
    line_index: int
    anchor_x: float
    anchor_y: float
    timestamp: float = field(default_factory=time.time)


class CountingPersistenceService:
    """Ghi batch các CountEvent vào bảng vehicle_counts."""

    def __init__(self, db):
        self.db = db
        self._lock = threading.Lock()
        self._buffer: List[tuple] = []
        self._session_id: int | None = None
        self._source_id: int | None = None
        self._last_flush = time.time()

    def bind_session(self, session_id: int, source_id: int) -> None:
        """Gắn session hiện tại — gọi khi bắt đầu phiên phân tích/stream."""
        with self._lock:
            self._session_id = session_id
            self._source_id = source_id
            self._buffer.clear()
            self._last_flush = time.time()

    def record(self, event: CountEvent) -> None:
        """Ghi nhận 1 xe vừa đếm được. Auto-flush khi đủ batch."""
        with self._lock:
            if self._session_id is None:
                return
            self._buffer.append((
                self._session_id,
                self._source_id or 0,
                event.track_id,
                event.class_name,
                round(event.confidence, 4),
                event.direction,
                event.line_index,
                round(event.anchor_x, 1),
                round(event.anchor_y, 1),
            ))
            should_flush = (
                len(self._buffer) >= _BATCH_SIZE
                or (time.time() - self._last_flush) >= _FLUSH_INTERVAL_SECONDS
            )
        if should_flush:
            self.flush()

    def flush(self) -> None:
        """Ghi tất cả pending records vào DB."""
        with self._lock:
            if not self._buffer:
                return
            batch = list(self._buffer)
            self._buffer.clear()
            self._last_flush = time.time()

        try:
            # Use a single connection for the whole batch.
            with self.db.connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO vehicle_counts
                        (session_id, source_id, track_id, class_name, confidence,
                         direction, line_index, anchor_x, anchor_y)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
            logger.debug("Flushed %d vehicle_count records to DB", len(batch))
        except Exception:
            logger.exception("Failed to flush vehicle_counts batch (%d records)", len(batch))

    def unbind(self) -> None:
        """Kết thúc session — flush remaining và reset."""
        self.flush()
        with self._lock:
            self._session_id = None
            self._source_id = None

    # --- Query helpers (đọc lại từ DB) ---

    def get_counts_for_session(self, session_id: int, limit: int = 500) -> list[dict[str, Any]]:
        """Lấy danh sách xe đếm được trong 1 session."""
        rows = self.db.fetchall(
            """
            SELECT id, track_id, class_name, confidence, direction, line_index,
                   anchor_x, anchor_y, datetime(counted_at, '+7 hours') AS counted_at
            FROM vehicle_counts
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        return [
            {
                "id": int(row["id"]),
                "track_id": int(row["track_id"]),
                "class_name": str(row["class_name"]),
                "confidence": round(float(row["confidence"]), 2),
                "direction": str(row["direction"]),
                "line_index": int(row["line_index"]),
                "anchor_x": float(row["anchor_x"]) if row["anchor_x"] else 0,
                "anchor_y": float(row["anchor_y"]) if row["anchor_y"] else 0,
                "counted_at": str(row["counted_at"]),
            }
            for row in rows
        ]

    def get_total_counts(self) -> dict[str, Any]:
        """Tổng xe đếm được tất cả phiên."""
        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM vehicle_counts")
        total = int(row["cnt"]) if row else 0
        class_rows = self.db.fetchall(
            """
            SELECT class_name, COUNT(*) AS cnt
            FROM vehicle_counts
            GROUP BY class_name
            ORDER BY cnt DESC
            """
        )
        per_class = {str(r["class_name"]): int(r["cnt"]) for r in class_rows}
        return {"total": total, "per_class": per_class}

    def get_recent_counts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Lấy N xe gần nhất (tất cả session)."""
        rows = self.db.fetchall(
            """
            SELECT vc.id, vc.session_id, vc.track_id, vc.class_name, vc.confidence,
                   vc.direction, datetime(vc.counted_at, '+7 hours') AS counted_at, src.name AS source_name
            FROM vehicle_counts vc
            LEFT JOIN sources src ON src.id = vc.source_id
            ORDER BY vc.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [
            {
                "id": int(row["id"]),
                "session_id": int(row["session_id"]),
                "track_id": int(row["track_id"]),
                "class_name": str(row["class_name"]),
                "confidence": round(float(row["confidence"]), 2),
                "direction": str(row["direction"]),
                "counted_at": str(row["counted_at"]),
                "source_name": str(row["source_name"] or ""),
            }
            for row in rows
        ]

    def clear_all(self) -> int:
        """Xóa toàn bộ vehicle_counts (dùng cho nút Reset Admin)."""
        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM vehicle_counts")
        count = int(row["cnt"]) if row else 0
        self.db.execute("DELETE FROM vehicle_counts")
        try:
            self.db.execute("DELETE FROM sqlite_sequence WHERE name = 'vehicle_counts'")
        except Exception:
            pass
        return count
