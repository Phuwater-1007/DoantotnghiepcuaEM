from __future__ import annotations

import base64
import copy
import cv2
import os
import json
import threading
import time
from pathlib import Path
from typing import Any

from vehicle_counting_system.ai_core.services.video_analysis_runner import analyze_video_source
from vehicle_counting_system.configs.paths import OUTPUT_CSV_DIR, OUTPUT_LOGS_DIR, OUTPUT_VIDEOS_DIR, PROJECT_ROOT
from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)
VN_SQLITE_TZ_MOD = "+7 hours"


class MonitoringService:
    def __init__(self, db, source_service, report_service, counting_persistence_service=None, lpr_persistence_service=None):
        self.db = db
        self.source_service = source_service
        self.report_service = report_service
        self.counting_persistence_service = counting_persistence_service
        self.lpr_persistence_service = lpr_persistence_service
        self._lock = threading.Lock()
        self._active_session_id: int | None = None
        self._stop_event: threading.Event | None = None
        self._worker: threading.Thread | None = None
        self._live_state: dict[str, Any] | None = None
        # Queue for multi-headless analysis
        self._queue: list[dict[str, Any]] = []  # [{source_id, user_id, queued_at}]

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

    def start_session(
        self,
        source_id: int,
        user_id: int,
        analysis_mode: str = "line",
        min_track_frames: int = 5,
    ) -> int:
        source = self.source_service.get_source(source_id)
        if source is None:
            raise ValueError("Không tìm thấy nguồn.")
        analysis_mode = "panorama" if analysis_mode == "panorama" else "line"
        if analysis_mode == "line" and not source.counting_config_path:
            raise ValueError("Video này chưa có ROI. Vui lòng chỉnh ROI trước khi chạy phân tích.")

        with self._lock:
            if self._active_session_id is not None:
                raise RuntimeError("Đã có phiên phân tích đang chạy. Dùng queue_session() để xếp hàng.")

            return self._start_session_locked(
                source_id, user_id, analysis_mode, min_track_frames
            )

    def _start_session_locked(
        self,
        source_id: int,
        user_id: int,
        analysis_mode: str = "line",
        min_track_frames: int = 5,
    ) -> int:
        """Internal: start a session (must be called with self._lock held or no active session)."""
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
            args=(session_id, source_id, stop_event, analysis_mode, min_track_frames),
            name=f"analysis-session-{session_id}",
            daemon=True,
        )
        self._active_session_id = session_id
        self._stop_event = stop_event
        self._worker = worker
        worker.start()
        return session_id

    # ------------------------------------------------------------------
    # Queue management for multi-headless analysis
    # ------------------------------------------------------------------

    def queue_session(self, source_id: int, user_id: int) -> dict[str, Any]:
        """Add a source to the analysis queue. If no session running, start immediately."""
        source = self.source_service.get_source(source_id)
        if source is None:
            raise ValueError("Không tìm thấy nguồn.")
        if not source.counting_config_path:
            raise ValueError("Video này chưa có ROI.")

        with self._lock:
            # Check if already queued
            for item in self._queue:
                if item["source_id"] == source_id:
                    return {"action": "already_queued", "source_id": source_id}

            # If nothing running, start immediately
            if self._active_session_id is None:
                session_id = self._start_session_locked(source_id, user_id)
                return {"action": "started", "session_id": session_id, "source_id": source_id}

            # If the same source is already running, skip
            if self._active_session_id is not None:
                active_source = self._get_active_source_id()
                if active_source == source_id:
                    return {"action": "already_running", "source_id": source_id}

            # Queue it
            self._queue.append({
                "source_id": source_id,
                "user_id": user_id,
                "queued_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "source_name": source.name,
            })
            return {
                "action": "queued",
                "source_id": source_id,
                "position": len(self._queue),
                "source_name": source.name,
            }

    def get_queue(self) -> list[dict[str, Any]]:
        """Return current queue + active session info."""
        with self._lock:
            return {
                "active_session_id": self._active_session_id,
                "active_live_state": copy.deepcopy(self._live_state) if self._live_state else None,
                "queue": list(self._queue),
            }

    def remove_from_queue(self, source_id: int) -> bool:
        """Remove a queued item by source_id."""
        with self._lock:
            before = len(self._queue)
            self._queue = [q for q in self._queue if q["source_id"] != source_id]
            return len(self._queue) < before

    def _get_active_source_id(self) -> int | None:
        """Get source_id of currently running session (must hold lock)."""
        if self._live_state:
            return self._live_state.get("source_id")
        return None

    def _process_next_in_queue(self) -> None:
        """Auto-start the next queued session if any."""
        with self._lock:
            if self._active_session_id is not None:
                return  # Something is still running
            if not self._queue:
                return  # Nothing queued
            next_item = self._queue.pop(0)

        logger.info("Queue: auto-starting next session for source %s", next_item["source_id"])
        try:
            with self._lock:
                self._start_session_locked(next_item["source_id"], next_item["user_id"])
        except Exception:
            logger.exception("Queue: failed to auto-start source %s", next_item["source_id"])
            # Try the next one
            self._process_next_in_queue()

    def stop_active_session(self) -> None:
        with self._lock:
            if self._stop_event is not None:
                self._stop_event.set()
            worker = self._worker
        if worker is None:
            return

        # Avoid blocking shutdown too long in web demo mode.
        # You can tune it via env vars:
        # - `WEB_STOP_SESSION_NO_JOIN=1` => don't wait at all
        # - `WEB_STOP_SESSION_JOIN_TIMEOUT` => seconds (float)
        no_join = os.getenv("WEB_STOP_SESSION_NO_JOIN", "").strip() not in ("", "0", "false", "False")
        if no_join:
            return

        join_timeout = float(os.getenv("WEB_STOP_SESSION_JOIN_TIMEOUT", "1.0"))
        if join_timeout <= 0:
            return

        worker.join(timeout=join_timeout)

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
        self.db.execute("DELETE FROM license_plate_events")
        if self.lpr_persistence_service is not None:
            try:
                self.lpr_persistence_service.clear_all()
            except Exception:
                pass
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
            self.db.execute("DELETE FROM license_plate_events")
            if self.lpr_persistence_service is not None:
                self.lpr_persistence_service.clear_all()
        except Exception:
            pass
        try:
            self.db.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('analysis_sessions', 'report_snapshots', 'license_plate_events')"
            )
        except Exception:
            # sqlite_sequence may not exist in some edge cases; safe to ignore.
            pass

    def _run_session(
        self,
        session_id: int,
        source_id: int,
        stop_event: threading.Event,
        analysis_mode: str = "line",
        min_track_frames: int = 5,
    ) -> None:
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
            if video_path:
                if video_path.startswith(("rtsp://", "http://", "https://")):
                    pass
                elif not Path(video_path).is_absolute():
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

            # Bind counting/LPR persistence cho phiên này.
            if self.counting_persistence_service is not None:
                self.counting_persistence_service.bind_session(session_id, source_id)
            if self.lpr_persistence_service is not None:
                self.lpr_persistence_service.bind_session(session_id, source_id)

            output_path = OUTPUT_VIDEOS_DIR / f"session_{session_id}_result.mp4"
            result = analyze_video_source(
                video_path,
                output_path=output_path,
                counting_lines_path=config_path,
                stop_event=stop_event,
                progress_callback=_progress_callback,
                counting_persistence_callback=(
                    self.counting_persistence_service.record
                    if self.counting_persistence_service else None
                ),
                lpr_persistence_callback=(
                    self.lpr_persistence_service.record
                    if self.lpr_persistence_service else None
                ),
                session_id=session_id,
                analysis_mode=analysis_mode,
                min_track_frames=min_track_frames,
            )
            finished_status = result["status"]
            summary = {
                "total": result["total"],
                "per_class": result["per_class"],
                "frames_processed": result["frames_processed"],
                "elapsed_seconds": result["elapsed_seconds"],
                "analysis_mode": result["analysis_mode"],
                "min_track_frames": result["min_track_frames"],
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
            # Only save report snapshot for completed sessions (not stopped/failed)
            if finished_status == "completed":
                session_row = self.db.fetchone(
                    """SELECT datetime(started_at, ?) AS started_at,
                              datetime(finished_at, ?) AS finished_at
                       FROM analysis_sessions WHERE id = ?""",
                    (VN_SQLITE_TZ_MOD, VN_SQLITE_TZ_MOD, session_id),
                )
                finished_at = str(session_row["finished_at"]) if session_row and session_row["finished_at"] else ""
                started_at = str(session_row["started_at"]) if session_row is not None else ""
                self.report_service.save_report_snapshot(
                    session_id=session_id,
                    finished_at=finished_at or started_at,
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
                "session_id": session_id,
                "total": result["total"],
                "per_class": result["per_class"],
            }
            try:
                summary_path = OUTPUT_VIDEOS_DIR / f"session_{session_id}_summary.json"
                with open(summary_path, "w", encoding="utf-8") as f:
                    json.dump(summary_for_file, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        except Exception as exc:
            logger.exception("Analysis session failed: %s", exc)
            self._mark_failed(session_id, str(exc))
            # Flush & unbind counting/LPR persistence.
            if self.counting_persistence_service is not None:
                try:
                    self.counting_persistence_service.unbind()
                except Exception:
                    pass
            if self.lpr_persistence_service is not None:
                try:
                    self.lpr_persistence_service.unbind()
                except Exception:
                    pass
            with self._lock:
                self._active_session_id = None
                self._stop_event = None
                self._worker = None
            # Auto-start next queued session
            self._process_next_in_queue()

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
