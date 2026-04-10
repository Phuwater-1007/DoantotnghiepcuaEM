from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from vehicle_counting_system.ai_core.services.video_analysis_runner import _get_shared_yolo_detector
from vehicle_counting_system.configs.paths import PROJECT_ROOT
from vehicle_counting_system.core.frame_processor import FrameProcessor
from vehicle_counting_system.presentation.web.dependencies import get_container, get_current_user
from vehicle_counting_system.trackers.bytetrack_tracker import ByteTrackTracker
from vehicle_counting_system.utils.logger import get_logger
from vehicle_counting_system.utils.video_utils import get_video_info

logger = get_logger(__name__)

# Grace period: keep processing alive this many seconds after last client disconnects
_GRACE_PERIOD_SECONDS = 300  # 5 minutes – keep stream alive while user browses other pages


class _StreamSession:
    """Holds state for a single MJPEG stream with background processing.

    When the stream stops, it saves results to DB (analysis_sessions + report_snapshots)
    so the Dashboard shows correct data even after the stream ends.
    """

    def __init__(
        self,
        source_id: int,
        video_path: str,
        config_path: str | None,
        frame_size: tuple[int, int],
        *,
        db=None,
        report_service=None,
        source_name: str = "",
    ):
        self.source_id = source_id
        self.video_path = video_path
        self.config_path = config_path
        self.frame_size = frame_size

        # DB persistence (for saving results when stream ends)
        self.db = db
        self.report_service = report_service
        self.source_name = source_name
        self.started_at = datetime.now()

        # Lifecycle control
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

        # Stats
        self.last_stats: dict[str, Any] = {"total": 0, "per_class": {}}

        # Frame buffer — shared between processing thread and MJPEG clients
        self.latest_frame: bytes | None = None
        self.frame_seq = 0  # Incremented each new frame
        self.frame_ready = threading.Event()

        # Client tracking
        self.active_clients = 0
        self.no_client_since: float | None = None  # timestamp when last client left

        # Background processing thread
        self.processing_thread: threading.Thread | None = None
        self.fps: float = 25.0

    def add_client(self):
        with self.lock:
            self.active_clients += 1
            self.no_client_since = None

    def remove_client(self):
        with self.lock:
            self.active_clients -= 1
            if self.active_clients <= 0:
                self.active_clients = 0
                self.no_client_since = time.time()

    @property
    def has_clients(self) -> bool:
        with self.lock:
            return self.active_clients > 0

    @property
    def grace_expired(self) -> bool:
        with self.lock:
            if self.active_clients > 0:
                return False
            if self.no_client_since is None:
                return False
            return (time.time() - self.no_client_since) > _GRACE_PERIOD_SECONDS


# Global registry – at most one stream per source.
_active_streams: dict[int, _StreamSession] = {}
_registry_lock = threading.Lock()


def _get_session(source_id: int) -> _StreamSession | None:
    with _registry_lock:
        return _active_streams.get(source_id)


def _stop_stream(source_id: int) -> None:
    with _registry_lock:
        session = _active_streams.pop(source_id, None)
    if session is not None:
        session.stop_event.set()
        # Wait for processing thread to finish (max 3s)
        if session.processing_thread and session.processing_thread.is_alive():
            session.processing_thread.join(timeout=3.0)


def _stop_all_streams() -> None:
    with _registry_lock:
        ids = list(_active_streams.keys())
    for sid in ids:
        _stop_stream(sid)


def _process_video(session: _StreamSession) -> None:
    """Background thread: reads video, runs YOLO detection, stores frames in buffer."""
    detector = _get_shared_yolo_detector()
    processor = FrameProcessor(
        detector=detector,
        tracker=ByteTrackTracker(),
        counting_lines_path=session.config_path,
        frame_size=session.frame_size,
    )

    cap = cv2.VideoCapture(session.video_path)
    if not cap.isOpened():
        logger.error("Cannot open video for stream: %s", session.video_path)
        with _registry_lock:
            _active_streams.pop(session.source_id, None)
        return

    session.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_delay = 1.0 / session.fps

    logger.info("Stream processing started for source %s (fps=%.1f)", session.source_id, session.fps)

    try:
        while not session.stop_event.is_set():
            # Check grace period — stop if no clients for too long
            if session.grace_expired:
                logger.info("Stream %s: grace period expired, stopping", session.source_id)
                break

            t_start = time.perf_counter()

            ok, frame = cap.read()
            if not ok:
                # Loop back to start (simulate continuous camera)
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                processor.reset()
                processor.tracker = ByteTrackTracker()
                ok, frame = cap.read()
                if not ok:
                    break

            processed = processor.process(frame)

            # Update live stats
            stats = processor.last_stats
            if stats is not None:
                with session.lock:
                    session.last_stats = {
                        "total": int(stats.total),
                        "per_class": dict(stats.per_class),
                    }

            # Encode frame and store in shared buffer
            _, buf = cv2.imencode(
                ".jpg", processed,
                [int(cv2.IMWRITE_JPEG_QUALITY), 75],
            )
            frame_bytes = buf.tobytes()

            with session.lock:
                session.latest_frame = frame_bytes
                session.frame_seq += 1
            session.frame_ready.set()

            # Pace to roughly match original video FPS
            elapsed = time.perf_counter() - t_start
            sleep_time = frame_delay - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except Exception:
        logger.exception("Stream processing error for source %s", session.source_id)
    finally:
        cap.release()
        processor.reset()
        logger.info("Stream processing stopped for source %s", session.source_id)

        # --- Save results to DB ---
        _save_stream_results_to_db(session)

        # Remove from registry
        with _registry_lock:
            _active_streams.pop(session.source_id, None)
        # Wake up any waiting clients so they can exit cleanly
        session.frame_ready.set()


def _save_stream_results_to_db(session: _StreamSession) -> None:
    """Persist final stream stats as an analysis_session + report_snapshot."""
    if session.db is None:
        return

    with session.lock:
        final_stats = dict(session.last_stats)

    total = final_stats.get("total", 0)
    per_class = final_stats.get("per_class", {})

    # Don't save empty sessions (0 vehicles detected)
    if total == 0:
        return

    try:
        summary = json.dumps(
            {"total": total, "per_class": per_class},
            ensure_ascii=False,
        )

        session_id = session.db.execute_and_get_id(
            """
            INSERT INTO analysis_sessions (source_id, started_by, status, started_at, finished_at, summary_json)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            """,
            (
                session.source_id,
                1,  # system user
                "completed",
                session.started_at.strftime("%Y-%m-%d %H:%M:%S"),
                summary,
            ),
        )

        # Save report snapshot for dashboard stats
        if session.report_service and session_id:
            session_row = session.db.fetchone(
                """SELECT datetime(finished_at, 'localtime') AS finished_at
                   FROM analysis_sessions WHERE id = ?""",
                (session_id,),
            )
            finished_at = str(session_row["finished_at"]) if session_row and session_row["finished_at"] else ""
            session.report_service.save_report_snapshot(
                session_id=session_id,
                finished_at=finished_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                total=total,
                per_class=per_class,
            )

        logger.info(
            "Stream results saved to DB: session #%s, source %s, total=%d",
            session_id, session.source_id, total,
        )
    except Exception:
        logger.exception("Failed to save stream results to DB for source %s", session.source_id)


def _ensure_stream(
    source_id: int,
    video_path: str,
    config_path: str | None,
    frame_size: tuple[int, int],
    *,
    db=None,
    report_service=None,
    source_name: str = "",
) -> _StreamSession:
    """Get existing stream or create a new one. Never restarts a running stream."""
    existing = _get_session(source_id)
    if existing is not None and not existing.stop_event.is_set():
        # Stream already running — just reuse it
        return existing

    # Create new session
    session = _StreamSession(
        source_id=source_id,
        video_path=video_path,
        config_path=config_path,
        frame_size=frame_size,
        db=db,
        report_service=report_service,
        source_name=source_name,
    )

    with _registry_lock:
        # Double-check another thread didn't create one
        if source_id in _active_streams:
            old = _active_streams[source_id]
            if not old.stop_event.is_set():
                return old
            old.stop_event.set()
        _active_streams[source_id] = session

    # Start background processing
    t = threading.Thread(
        target=_process_video,
        args=(session,),
        name=f"stream-{source_id}",
        daemon=True,
    )
    session.processing_thread = t
    t.start()

    return session


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["stream"])

    def _require_auth(request: Request):
        user = get_current_user(request)
        if user is None:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        return None

    # -----------------------------------------------------------------
    # Global stats for ALL active streams (used by Dashboard)
    # Must be registered BEFORE /stream/{source_id} to avoid path conflict
    # -----------------------------------------------------------------
    @router.get("/stream/active-stats")
    def all_active_stream_stats(request: Request):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err

        streams = []
        with _registry_lock:
            snapshot = list(_active_streams.items())

        for source_id, session in snapshot:
            with session.lock:
                stats = dict(session.last_stats)
            streams.append({
                "source_id": source_id,
                "total": stats.get("total", 0),
                "per_class": stats.get("per_class", {}),
            })

        agg_total = 0
        agg_per_class: dict[str, int] = {}
        for s in streams:
            agg_total += s["total"]
            for k, v in s["per_class"].items():
                agg_per_class[k] = agg_per_class.get(k, 0) + v

        return {
            "has_active_stream": len(streams) > 0,
            "stream_count": len(streams),
            "total": agg_total,
            "per_class": agg_per_class,
            "streams": streams,
        }

    # -----------------------------------------------------------------
    # MJPEG stream endpoint
    # Background processing keeps running even when client disconnects.
    # Reconnecting reuses the existing stream seamlessly.
    # -----------------------------------------------------------------
    @router.get("/stream/{source_id}")
    def stream_video(request: Request, source_id: int):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err

        container = get_container(request)
        source = container.source_service.get_source(source_id)
        if not source:
            return JSONResponse(status_code=404, content={"error": "Source not found"})

        video_path = source.source_uri
        if video_path and not Path(video_path).is_absolute():
            video_path = str((PROJECT_ROOT / video_path).resolve())

        info = get_video_info(video_path)
        if info is None:
            return JSONResponse(status_code=400, content={"error": "Cannot read video"})

        config_path = source.counting_config_path

        # Get or create stream — will NOT restart if already running
        session = _ensure_stream(
            source_id, video_path, config_path, info.frame_size,
            db=container.db,
            report_service=container.report_service,
            source_name=source.name,
        )

        def generate():
            session.add_client()
            last_seq = 0

            try:
                while not session.stop_event.is_set():
                    # Wait for a new frame (timeout 2s to check stop_event)
                    session.frame_ready.wait(timeout=2.0)
                    session.frame_ready.clear()

                    with session.lock:
                        frame_bytes = session.latest_frame
                        current_seq = session.frame_seq

                    if frame_bytes is None:
                        continue

                    # Skip if we already sent this frame
                    if current_seq == last_seq:
                        continue
                    last_seq = current_seq

                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" +
                        frame_bytes +
                        b"\r\n"
                    )

            except GeneratorExit:
                pass
            except Exception:
                logger.exception("MJPEG client error for source %s", source_id)
            finally:
                session.remove_client()

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    # -----------------------------------------------------------------
    # Real-time stats for the active stream
    # -----------------------------------------------------------------
    @router.get("/stream/{source_id}/stats")
    def stream_stats(request: Request, source_id: int):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err

        session = _get_session(source_id)
        if session is None:
            return {"streaming": False, "total": 0, "per_class": {}}

        with session.lock:
            stats = dict(session.last_stats)

        return {"streaming": True, **stats}

    # -----------------------------------------------------------------
    # Stop a stream
    # -----------------------------------------------------------------
    @router.post("/stream/{source_id}/stop")
    def stop_stream(request: Request, source_id: int):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err

        _stop_stream(source_id)
        return {"ok": True}

    return router
