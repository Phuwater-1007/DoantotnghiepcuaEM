from __future__ import annotations

import base64
import copy
import cv2
import json
import threading
import time
from pathlib import Path
from typing import Any

from vehicle_counting_system.ai_core.services.video_analysis_runner import analyze_video_source
from vehicle_counting_system.configs.paths import OUTPUT_CSV_DIR, OUTPUT_LOGS_DIR, OUTPUT_VIDEOS_DIR, PROJECT_ROOT
from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)


class MonitoringService:
    def __init__(self, db, source_service, report_service):
        self.db = db
        self.source_service = source_service
        self.report_service = report_service
        self._lock = threading.Lock()
        self._active_session_id: int | None = None
        self._stop_event: threading.Event | None = None
        self._worker: threading.Thread | None = None
        self._live_state: dict[str, Any] | None = None

    def list_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT
                sess.id,
                sess.source_id,
                sess.status,
                sess.started_at,
                sess.finished_at,
                sess.output_video_path,
                sess.summary_json,
                sess.error_message,
                src.name AS source_name,
                src.source_type AS source_type
            FROM analysis_sessions sess
            JOIN sources src ON src.id = sess.source_id
            ORDER BY sess.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        sessions: list[dict[str, Any]] = []
        for row in rows:
            sessions.append(
                {
                    "id": int(row["id"]),
                    "source_id": int(row["source_id"]),
                    "status": str(row["status"]),
                    "started_at": str(row["started_at"]),
                    "finished_at": row["finished_at"],
                    "output_video_path": row["output_video_path"],
                    "summary": json.loads(row["summary_json"] or "{}"),
                    "error_message": row["error_message"],
                    "source_name": str(row["source_name"]),
                    "source_type": str(row["source_type"]),
                }
            )
        return sessions

    def get_active_session_id(self) -> int | None:
        with self._lock:
            return self._active_session_id

    def get_live_state(self) -> dict[str, Any] | None:
        with self._lock:
            if self._live_state is None:
                return None
            return copy.deepcopy(self._live_state)

    def start_session(self, source_id: int, user_id: int) -> int:
        source = self.source_service.get_source(source_id)
        if source is None:
            raise ValueError("Không tìm thấy nguồn.")
        if not source.counting_config_path:
            raise ValueError("Video này chưa có ROI. Vui lòng chỉnh ROI trước khi chạy phân tích.")

        with self._lock:
            if self._active_session_id is not None:
                raise RuntimeError("Đã có phiên phân tích đang chạy.")

            session_id = self.db.execute_and_get_id(
                """
                INSERT INTO analysis_sessions (source_id, started_by, status, summary_json)
                VALUES (?, ?, ?, ?)
                """,
                (source_id, user_id, "queued", "{}"),
            )

            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._run_session,
                args=(session_id, source_id, stop_event),
                name=f"analysis-session-{session_id}",
                # Make it daemon so web shutdown doesn't hang the process.
                daemon=True,
            )
            self._active_session_id = session_id
            self._stop_event = stop_event
            self._worker = worker
            worker.start()
            return session_id

    def stop_active_session(self) -> None:
        with self._lock:
            if self._stop_event is not None:
                self._stop_event.set()
            worker = self._worker
        if worker is not None:
            # Avoid blocking shutdown too long in web demo mode.
            worker.join(timeout=5.0)

    def reset_runtime_state(self) -> None:
        """Lam sach du lieu phan tich tam de moi lan bat web la mot workspace gon."""
        self.stop_active_session()
        with self._lock:
            self._active_session_id = None
            self._stop_event = None
            self._worker = None
            self._live_state = None

        self.db.execute("DELETE FROM report_snapshots")
        self.db.execute("DELETE FROM analysis_sessions")
        self.db.execute("UPDATE sources SET is_active = 0, status = 'ready'")

        for directory in (OUTPUT_VIDEOS_DIR, OUTPUT_CSV_DIR, OUTPUT_LOGS_DIR):
            path = Path(directory)
            if not path.exists():
                continue
            for child in path.iterdir():
                if child.is_file():
                    try:
                        child.unlink()
                    except OSError:
                        logger.warning("Cannot delete runtime file: %s", child)

    def reset_sessions_only(self) -> None:
        """Reset session history so IDs start from 1 again (web demo convenience).

        Keeps input videos and does NOT delete output files.
        """
        self.stop_active_session()
        with self._lock:
            self._active_session_id = None
            self._stop_event = None
            self._worker = None
            self._live_state = None

        # Clear session/report tables
        self.db.execute("DELETE FROM report_snapshots")
        self.db.execute("DELETE FROM analysis_sessions")

        # Reset AUTOINCREMENT counters (SQLite) so IDs start fresh.
        try:
            self.db.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('analysis_sessions', 'report_snapshots')"
            )
        except Exception:
            # sqlite_sequence may not exist in some edge cases; safe to ignore.
            pass

    def _run_session(self, session_id: int, source_id: int, stop_event: threading.Event) -> None:
        source = self.source_service.get_source(source_id)
        if source is None:
            self._mark_failed(session_id, "Source not found.")
            return

        self.db.execute(
            "UPDATE analysis_sessions SET status = ? WHERE id = ?",
            ("running", session_id),
        )
        self._set_live_state(
            session_id=session_id,
            source_id=source_id,
            source_name=source.name,
            status="running",
            summary={"total": 0, "per_class": {}},
        )

        try:
            if source.source_type != "video":
                raise RuntimeError(
                    f"Loại nguồn '{source.source_type}' chưa được hỗ trợ. "
                    "Vui lòng dùng nguồn video file cho demo hiện tại."
                )

            from vehicle_counting_system.utils.video_utils import validate_video_source

            video_path = source.source_uri
            if video_path and not Path(video_path).is_absolute():
                video_path = str((PROJECT_ROOT / video_path).resolve())

            ok, err = validate_video_source(video_path)
            if not ok:
                raise RuntimeError(f"Video không hợp lệ: {err}")

            from vehicle_counting_system.application.services.source_config_service import get_source_config_path
            from vehicle_counting_system.configs.paths import CONFIG_DIR

            config_path = source.counting_config_path or get_source_config_path(source_id)
            if not config_path:
                norm_path = CONFIG_DIR / "counting_lines_normalized.json"
                config_path = str(norm_path) if norm_path.exists() else None

            last_frame_emit = 0.0

            def _progress_callback(frame, stats, frame_index: int, frames_processed: int) -> None:
                nonlocal last_frame_emit
                now = time.perf_counter()
                if now - last_frame_emit < 0.35:
                    return
                last_frame_emit = now
                summary = {
                    "total": int(stats.total) if stats is not None else 0,
                    "per_class": dict(stats.per_class) if stats is not None else {},
                    "frames_processed": frames_processed,
                }
                self._set_live_state(
                    session_id=session_id,
                    source_id=source_id,
                    source_name=source.name,
                    status="running",
                    summary=summary,
                    frame=frame,
                    frame_index=frame_index,
                )

            output_path = OUTPUT_VIDEOS_DIR / f"{Path(source.name).stem}_result.mp4"
            result = analyze_video_source(
                video_path,
                output_path=output_path,
                counting_lines_path=config_path,
                stop_event=stop_event,
                progress_callback=_progress_callback,
            )
            finished_status = result["status"]
            summary = {
                "total": result["total"],
                "per_class": result["per_class"],
                "frames_processed": result["frames_processed"],
                "elapsed_seconds": result["elapsed_seconds"],
            }
            self.db.execute(
                """
                UPDATE analysis_sessions
                SET status = ?, finished_at = CURRENT_TIMESTAMP, output_video_path = ?, summary_json = ?, error_message = NULL
                WHERE id = ?
                """,
                (
                    finished_status,
                    result["output_video_path"],
                    json.dumps(summary, ensure_ascii=False),
                    session_id,
                ),
            )
            session_row = self.db.fetchone(
                "SELECT started_at FROM analysis_sessions WHERE id = ?",
                (session_id,),
            )
            started_at = str(session_row["started_at"]) if session_row is not None else ""
            self.report_service.save_report_snapshot(
                session_id=session_id,
                started_at=started_at,
                total=int(result["total"]),
                per_class=dict(result["per_class"]),
            )
            self._set_live_state(
                session_id=session_id,
                source_id=source_id,
                source_name=source.name,
                status=finished_status,
                summary=summary,
                output_video_path=result["output_video_path"],
            )
            summary_for_file = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "total": result["total"],
                "per_class": result["per_class"],
            }
            try:
                summary_path = OUTPUT_VIDEOS_DIR / f"{Path(source.name).stem}_summary.json"
                with open(summary_path, "w", encoding="utf-8") as f:
                    json.dump(summary_for_file, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        except Exception as exc:
            logger.exception("Analysis session failed: %s", exc)
            self._mark_failed(session_id, str(exc))
        finally:
            with self._lock:
                self._active_session_id = None
                self._stop_event = None
                self._worker = None

    def _mark_failed(self, session_id: int, message: str) -> None:
        self.db.execute(
            """
            UPDATE analysis_sessions
            SET status = ?, finished_at = CURRENT_TIMESTAMP, error_message = ?
            WHERE id = ?
            """,
            ("failed", message, session_id),
        )
        with self._lock:
            if self._live_state and self._live_state.get("session_id") == session_id:
                self._live_state["status"] = "failed"
                self._live_state["error_message"] = message

    def _set_live_state(
        self,
        *,
        session_id: int,
        source_id: int,
        source_name: str,
        status: str,
        summary: dict[str, Any],
        frame=None,
        frame_index: int | None = None,
        output_video_path: str | None = None,
    ) -> None:
        image_data = None
        if frame is not None:
            try:
                ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok:
                    image_data = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
            except Exception:
                image_data = None

        with self._lock:
            existing = self._live_state or {}
            live_state = {
                "session_id": session_id,
                "source_id": source_id,
                "source_name": source_name,
                "status": status,
                "summary": summary,
                "frame_index": frame_index if frame_index is not None else existing.get("frame_index", 0),
                "output_video_path": output_video_path or existing.get("output_video_path"),
                "image_data": image_data or existing.get("image_data"),
                "error_message": existing.get("error_message"),
                "updated_at": time.time(),
            }
            self._live_state = live_state
