from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

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
_GRACE_PERIOD_SECONDS = 300  # 5 minutes

# --- Fix #2: Maximum FPS for live stream processing to avoid GPU overload ---
_STREAM_MAX_FPS: float = float(os.getenv("STREAM_MAX_FPS", "15"))

# --- Fix #4: RTSP transport protocol (tcp = stable, udp = low-latency) ---
_RTSP_TRANSPORT: str = os.getenv("STREAM_RTSP_TRANSPORT", "tcp").lower()

# --- Lag fix: Resize MJPEG output frames to this width (px) before encoding.
#     YOLO still runs at native resolution; only the browser-bound JPEG is smaller.
#     0 = disabled (send full resolution). Default 1280 is a good balance.
_STREAM_OUTPUT_WIDTH: int = int(os.getenv("STREAM_OUTPUT_WIDTH", "1280"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_live_stream(uri: str) -> bool:
    """Return True if the URI is a live network stream (RTSP, RTMP, HTTP stream)."""
    lower = (uri or "").lower()
    return lower.startswith(("rtsp://", "rtmp://", "http://", "https://"))


def _open_capture(uri: str) -> cv2.VideoCapture:
    """
    Fix #4: Open VideoCapture with optimal settings for the stream type.

    For RTSP we configure FFMPEG options to minimize connection latency and
    set OpenCV's internal buffer to 1 frame so we always get fresh data.
    """
    if _is_live_stream(uri):
        # Apply FFMPEG options BEFORE opening the capture.
        # These reduce initial handshake time and buffer buildup significantly.
        opts = (
            f"rtsp_transport;{_RTSP_TRANSPORT}"
            "|buffer_size;65536"
            "|max_delay;200000"
            "|stimeout;5000000"
            "|fflags;nobuffer"
        )
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = opts
        cap = cv2.VideoCapture(uri, cv2.CAP_FFMPEG)
        # Minimize OpenCV's internal ring-buffer (keeps only the newest frame)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    else:
        cap = cv2.VideoCapture(uri)
    return cap


def _resize_for_output(frame):
    """
    Resize a processed frame to STREAM_OUTPUT_WIDTH before JPEG encoding.

    YOLO inference and bbox drawing happen at native resolution.
    Only the browser-bound JPEG payload is scaled down, which:
      - Dramatically reduces bytes-per-frame (1920→1280 ≈ 2× smaller JPEG)
      - Lowers CPU time for imencode
      - Reduces network transfer time to the browser
    """
    if _STREAM_OUTPUT_WIDTH <= 0:
        return frame
    h, w = frame.shape[:2]
    if w <= _STREAM_OUTPUT_WIDTH:
        return frame
    new_h = int(h * _STREAM_OUTPUT_WIDTH / w)
    return cv2.resize(frame, (_STREAM_OUTPUT_WIDTH, new_h), interpolation=cv2.INTER_LINEAR)


# ---------------------------------------------------------------------------
# Fix #1: _LatestFrameBuffer — core mechanism to prevent RTSP frame buildup
# ---------------------------------------------------------------------------

class _LatestFrameBuffer:
    """
    Thread-safe single-slot frame buffer.

    The RTSP reader thread writes frames as fast as they arrive (dropping any
    unread frame). The processor thread always reads the LATEST frame — it
    never processes a stale frame that has been sitting in a queue.

    This eliminates the root cause of RAM growth and eventual crash when YOLO
    inference is slower than the camera's frame rate.
    """

    def __init__(self) -> None:
        self._frame = None
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._closed = False

    def put(self, frame) -> None:
        """Store the latest frame, silently discarding any previous unread one."""
        with self._lock:
            self._frame = frame
        self._event.set()

    def get(self, timeout: float = 2.0):
        """
        Block until a new frame is available, then return it immediately.
        Returns None on timeout or after close().
        """
        if not self._event.wait(timeout=timeout):
            return None
        self._event.clear()
        with self._lock:
            return self._frame

    def close(self) -> None:
        """Signal any waiting get() calls to wake up and return."""
        self._closed = True
        self._event.set()


# ---------------------------------------------------------------------------
# Stream session
# ---------------------------------------------------------------------------

class _StreamSession:
    """Holds state for a single MJPEG stream with background processing."""

    def __init__(
        self,
        source_id: int,
        video_path: str,
        config_path: str | None,
        frame_size: tuple[int, int],
        *,
        db=None,
        report_service=None,
        counting_persistence=None,
        source_name: str = "",
    ):
        self.source_id = source_id
        self.video_path = video_path
        self.config_path = config_path
        self.frame_size = frame_size
        self.is_live = _is_live_stream(video_path)

        # DB persistence
        self.db = db
        self.report_service = report_service
        self.counting_persistence = counting_persistence
        self.source_name = source_name
        self.started_at = datetime.now()
        self.db_session_id: int | None = None  # ID phíen trong analysis_sessions

        # Lifecycle
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

        # Stats
        self.last_stats: dict[str, Any] = {"total": 0, "per_class": {}}

        # --- Fix #3: threading.Condition for proper multi-client broadcast ---
        # All MJPEG clients are woken simultaneously (notify_all) instead of
        # the old threading.Event which had a race: one client could clear the
        # event before another client had a chance to react.
        self._frame_cv = threading.Condition(self.lock)

        # Encoded JPEG frame shared between processor and all MJPEG clients
        self.latest_frame: bytes | None = None
        self.frame_seq: int = 0

        # Client tracking
        self.active_clients: int = 0
        self.no_client_since: float | None = None

        # Background threads
        self.processing_thread: Optional[threading.Thread] = None
        self.fps: float = 25.0

        # --- Fix #1: RTSP uses a dedicated reader thread + LatestFrameBuffer ---
        self._raw_buffer: Optional[_LatestFrameBuffer] = None
        self._reader_thread: Optional[threading.Thread] = None

        # Vehicle class filter: None = count all allowed classes from settings.
        # Updated live via POST /api/stream/{source_id}/set-classes.
        self.active_classes: set | None = None

    # ------------------------------------------------------------------

    def add_client(self) -> None:
        with self.lock:
            self.active_clients += 1
            self.no_client_since = None

    def remove_client(self) -> None:
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


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------

_active_streams: dict[int, _StreamSession] = {}
_registry_lock = threading.Lock()


def _get_session(source_id: int) -> _StreamSession | None:
    with _registry_lock:
        return _active_streams.get(source_id)


def _stop_stream(source_id: int) -> None:
    with _registry_lock:
        session = _active_streams.pop(source_id, None)
    if session is None:
        return
    session.stop_event.set()
    # Unblock the raw frame buffer so the reader thread exits cleanly
    if session._raw_buffer is not None:
        session._raw_buffer.close()
    # Wake all waiting MJPEG clients so they can exit
    with session._frame_cv:
        session._frame_cv.notify_all()
    if session.processing_thread and session.processing_thread.is_alive():
        session.processing_thread.join(timeout=3.0)


def _stop_all_streams() -> None:
    with _registry_lock:
        ids = list(_active_streams.keys())
    for sid in ids:
        _stop_stream(sid)


# ---------------------------------------------------------------------------
# Fix #1: Dedicated RTSP reader thread
# ---------------------------------------------------------------------------

def _rtsp_reader_thread(session: _StreamSession, cap: cv2.VideoCapture) -> None:
    """
    Fix #1 + #4: Continuously drain the RTSP stream, keeping only the latest
    frame in _LatestFrameBuffer.

    Running this in a dedicated thread ensures the OpenCV/FFMPEG internal buffer
    never grows — frames are always consumed at the camera's native rate, and
    only the most recent one is handed to the (slower) YOLO processor.
    """
    logger.info(
        "RTSP reader started for source %s (transport=%s)", session.source_id, _RTSP_TRANSPORT
    )
    buf = session._raw_buffer
    consecutive_fails = 0
    max_consecutive_fails = 30  # roughly 3 s at 10 fps before giving up

    try:
        while not session.stop_event.is_set():
            ok, frame = cap.read()
            if not ok:
                consecutive_fails += 1
                logger.debug(
                    "RTSP reader: read failure #%d for source %s",
                    consecutive_fails, session.source_id,
                )
                if consecutive_fails >= max_consecutive_fails:
                    logger.warning(
                        "RTSP reader: too many failures for source %s — stopping stream",
                        session.source_id,
                    )
                    session.stop_event.set()
                    break
                time.sleep(0.1)
                continue
            consecutive_fails = 0
            buf.put(frame)  # Always overwrites; never blocks
    except Exception:
        logger.exception("RTSP reader thread error for source %s", session.source_id)
        session.stop_event.set()
    finally:
        try:
            cap.release()
        except Exception:
            pass
        buf.close()
        logger.info("RTSP reader stopped for source %s", session.source_id)


# ---------------------------------------------------------------------------
# Processing routines
# ---------------------------------------------------------------------------

def _process_live_stream(session: _StreamSession, processor: FrameProcessor) -> None:
    """
    Fix #1 + #2 + #3: Process live RTSP stream at a controlled rate.

    • Always takes the LATEST frame from _LatestFrameBuffer (never a stale one).
    • Rate-limited to STREAM_MAX_FPS so the GPU is never overloaded.
    • Broadcasts each encoded JPEG to all waiting MJPEG clients via Condition.
    """
    buf = session._raw_buffer
    # Fix #2: minimum time between consecutive processed frames
    min_interval = 1.0 / max(_STREAM_MAX_FPS, 1.0)

    logger.info(
        "Live processor started for source %s (max_fps=%.1f, interval=%.0fms)",
        session.source_id, _STREAM_MAX_FPS, min_interval * 1000,
    )

    while not session.stop_event.is_set():
        if session.grace_expired:
            logger.info("Stream %s: grace period expired, stopping", session.source_id)
            break

        t_start = time.perf_counter()

        # Block until the reader delivers a new frame (timeout 2 s)
        frame = buf.get(timeout=2.0)
        if frame is None:
            if session.stop_event.is_set():
                break
            # Timeout — loop and check stop_event again
            continue

        # Apply per-session class filter (set by UI toggle, None = count all)
        if session.active_classes is not None:
            processor.set_active_classes(session.active_classes)

        # YOLO + overlay (Fix #5: if inference lock is busy we've already
        # moved on to the latest frame, so no stale-frame accumulation)
        processed = processor.process(frame)

        # Update live stats
        raw_stats = processor.last_stats
        if raw_stats is not None:
            elapsed_sec = (datetime.now() - session.started_at).total_seconds()
            dir_data = raw_stats.per_direction
            # Chỉ tính flow rate sau tối thiểu 60 giây để tránh số liệu sai lệch
            if elapsed_sec >= 60 and raw_stats.total > 0:
                elapsed_min = elapsed_sec / 60.0
                flow_rate = int(round(raw_stats.total / elapsed_min * 60))
            else:
                flow_rate = None  # Chưa đủ thời gian quan sát
            with session.lock:
                session.last_stats = {
                    "total": int(raw_stats.total),
                    "per_class": dict(raw_stats.per_class),
                    "flow_rate_vph": flow_rate,
                    "elapsed_sec": int(elapsed_sec),
                    "directions": {
                        "di":  {"total": dir_data.get("p1_to_p2", {"total": 0, "per_class": {}})["total"],
                                "per_class": dir_data.get("p1_to_p2", {"total": 0, "per_class": {}})["per_class"]},
                        "ve":  {"total": dir_data.get("p2_to_p1", {"total": 0, "per_class": {}})["total"],
                                "per_class": dir_data.get("p2_to_p1", {"total": 0, "per_class": {}})["per_class"]},
                    },
                }

        # Resize before encoding: reduces JPEG size → less lag in browser
        output_frame = _resize_for_output(processed)

        # Encode JPEG
        _, jpeg_buf = cv2.imencode(
            ".jpg", output_frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 75],
        )
        frame_bytes = jpeg_buf.tobytes()

        # Fix #3: Condition.notify_all() — all MJPEG clients wake simultaneously
        with session._frame_cv:
            session.latest_frame = frame_bytes
            session.frame_seq += 1
            session._frame_cv.notify_all()

        # Fix #2: Rate limiting — sleep the remaining time to hit target FPS
        elapsed = time.perf_counter() - t_start
        sleep_time = min_interval - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


def _process_video_file(
    session: _StreamSession,
    processor: FrameProcessor,
    cap: cv2.VideoCapture,
) -> None:
    """Process a local video file (original paced-playback logic)."""
    frame_delay = 1.0 / max(session.fps, 1.0)

    try:
        while not session.stop_event.is_set():
            if session.grace_expired:
                logger.info("Stream %s: grace period expired, stopping", session.source_id)
                break

            t_start = time.perf_counter()

            ok, frame = cap.read()
            if not ok:
                logger.info("Stream %s: video finished, saving results", session.source_id)
                break

            # Apply per-session class filter
            if session.active_classes is not None:
                processor.set_active_classes(session.active_classes)

            processed = processor.process(frame)

            raw_stats = processor.last_stats
            if raw_stats is not None:
                elapsed_sec = (datetime.now() - session.started_at).total_seconds()
                dir_data = raw_stats.per_direction
                if elapsed_sec >= 60 and raw_stats.total > 0:
                    elapsed_min = elapsed_sec / 60.0
                    flow_rate = int(round(raw_stats.total / elapsed_min * 60))
                else:
                    flow_rate = None
                with session.lock:
                    session.last_stats = {
                        "total": int(raw_stats.total),
                        "per_class": dict(raw_stats.per_class),
                        "flow_rate_vph": flow_rate,
                        "elapsed_sec": int(elapsed_sec),
                        "directions": {
                            "di":  {"total": dir_data.get("p1_to_p2", {"total": 0, "per_class": {}})["total"],
                                    "per_class": dir_data.get("p1_to_p2", {"total": 0, "per_class": {}})["per_class"]},
                            "ve":  {"total": dir_data.get("p2_to_p1", {"total": 0, "per_class": {}})["total"],
                                    "per_class": dir_data.get("p2_to_p1", {"total": 0, "per_class": {}})["per_class"]},
                        },
                    }

            # Resize before encoding: keeps video files smooth too
            output_frame = _resize_for_output(processed)

            _, jpeg_buf = cv2.imencode(
                ".jpg", output_frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), 75],
            )
            frame_bytes = jpeg_buf.tobytes()

            # Fix #3: same Condition broadcast for video files too
            with session._frame_cv:
                session.latest_frame = frame_bytes
                session.frame_seq += 1
                session._frame_cv.notify_all()

            elapsed = time.perf_counter() - t_start
            sleep_time = frame_delay - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
    finally:
        try:
            cap.release()
        except Exception:
            pass


def _process_video(session: _StreamSession) -> None:
    """
    Background orchestrator thread: sets up detector/processor then delegates
    to the appropriate processing routine based on stream type.
    """
    detector = _get_shared_yolo_detector()

    # Tạo session trong DB ngay khi stream bắt đầu (để vehicle_counts có session_id).
    if session.db is not None:
        try:
            session_id = session.db.execute_and_get_id(
                """
                INSERT INTO analysis_sessions (source_id, started_by, status, summary_json)
                VALUES (?, ?, ?, ?)
                """,
                (session.source_id, 1, "running", "{}"),
            )
            session.db_session_id = session_id
            # Bind persistence service to this session.
            if session.counting_persistence is not None:
                session.counting_persistence.bind_session(session_id, session.source_id)
            logger.info("Stream DB session created: #%s for source %s", session_id, session.source_id)
        except Exception:
            logger.exception("Failed to create DB session for stream %s", session.source_id)

    # Wire counting persistence callback.
    persistence_cb = None
    if session.counting_persistence is not None:
        persistence_cb = session.counting_persistence.record

    processor = FrameProcessor(
        detector=detector,
        tracker=ByteTrackTracker(),
        counting_lines_path=session.config_path,
        frame_size=session.frame_size,
        counting_persistence_callback=persistence_cb,
    )

    # Fix #4: Open with RTSP-optimised settings
    cap = _open_capture(session.video_path)
    if not cap.isOpened():
        logger.error("Cannot open video for stream: %s", session.video_path)
        with _registry_lock:
            _active_streams.pop(session.source_id, None)
        return

    # Detect actual FPS; clamp to a sane range (RTSP often returns 0 or 90000)
    raw_fps = cap.get(cv2.CAP_PROP_FPS)
    if raw_fps and 1.0 < raw_fps < 120.0:
        session.fps = float(raw_fps)
    else:
        session.fps = 25.0

    logger.info(
        "Stream started: source=%s fps=%.1f live=%s max_process_fps=%.1f",
        session.source_id, session.fps, session.is_live, _STREAM_MAX_FPS,
    )

    try:
        if session.is_live:
            # Fix #1: spin up the RTSP reader thread first
            session._raw_buffer = _LatestFrameBuffer()
            reader = threading.Thread(
                target=_rtsp_reader_thread,
                args=(session, cap),
                name=f"rtsp-reader-{session.source_id}",
                daemon=True,
            )
            session._reader_thread = reader
            reader.start()
            cap = None  # Reader thread now owns (and will release) the capture

            _process_live_stream(session, processor)
        else:
            _process_video_file(session, processor, cap)
            cap = None  # Released inside _process_video_file

    except Exception:
        logger.exception("Stream processing error for source %s", session.source_id)
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

        logger.info("Stream stopped: source=%s", session.source_id)

        # Persist results to DB
        _save_stream_results_to_db(session)

        processor.reset()

        with _registry_lock:
            _active_streams.pop(session.source_id, None)

        # Final broadcast: wake any still-waiting MJPEG clients
        with session._frame_cv:
            session._frame_cv.notify_all()


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def _save_stream_results_to_db(session: _StreamSession) -> None:
    """Persist final stream stats — update the session created at start."""
    # Flush & unbind counting persistence service.
    if session.counting_persistence is not None:
        try:
            session.counting_persistence.unbind()
        except Exception:
            logger.exception("Failed to unbind counting persistence for source %s", session.source_id)

    if session.db is None:
        return

    with session.lock:
        final_stats = dict(session.last_stats)

    total = final_stats.get("total", 0)
    per_class = final_stats.get("per_class", {})
    summary = json.dumps({"total": total, "per_class": per_class}, ensure_ascii=False)

    session_id = session.db_session_id

    try:
        if session_id is not None:
            # Update session đã tạo lúc bắt đầu stream.
            finished_status = "completed" if total > 0 else "stopped"
            session.db.execute(
                """
                UPDATE analysis_sessions
                SET status = ?, finished_at = CURRENT_TIMESTAMP, summary_json = ?
                WHERE id = ?
                """,
                (finished_status, summary, session_id),
            )
        else:
            # Fallback: tạo mới nếu chưa có (cho tương thích ngược).
            if total == 0:
                return
            session_id = session.db.execute_and_get_id(
                """
                INSERT INTO analysis_sessions (source_id, started_by, status, started_at, finished_at, summary_json)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (
                    session.source_id,
                    1,
                    "completed",
                    session.started_at.strftime("%Y-%m-%d %H:%M:%S"),
                    summary,
                ),
            )

        if session.report_service and session_id and total > 0:
            VN_TZ = "+7 hours"
            session_row = session.db.fetchone(
                "SELECT datetime(finished_at, ?) AS finished_at FROM analysis_sessions WHERE id = ?",
                (VN_TZ, session_id),
            )
            finished_at = (
                str(session_row["finished_at"])
                if session_row and session_row["finished_at"]
                else ""
            )
            session.report_service.save_report_snapshot(
                session_id=session_id,
                finished_at=finished_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                total=total,
                per_class=per_class,
            )

        logger.info(
            "Stream results saved: session=#%s source=%s total=%d",
            session_id, session.source_id, total,
        )
    except Exception:
        logger.exception("Failed to save stream results for source %s", session.source_id)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _ensure_stream(
    source_id: int,
    video_path: str,
    config_path: str | None,
    frame_size: tuple[int, int],
    *,
    db=None,
    report_service=None,
    counting_persistence=None,
    source_name: str = "",
) -> _StreamSession:
    """Get existing stream or create a new one. Never restarts a running stream."""
    existing = _get_session(source_id)
    if existing is not None and not existing.stop_event.is_set():
        return existing

    session = _StreamSession(
        source_id=source_id,
        video_path=video_path,
        config_path=config_path,
        frame_size=frame_size,
        db=db,
        report_service=report_service,
        counting_persistence=counting_persistence,
        source_name=source_name,
    )

    with _registry_lock:
        if source_id in _active_streams:
            old = _active_streams[source_id]
            if not old.stop_event.is_set():
                return old
            old.stop_event.set()
        _active_streams[source_id] = session

    t = threading.Thread(
        target=_process_video,
        args=(session,),
        name=f"stream-{source_id}",
        daemon=True,
    )
    session.processing_thread = t
    t.start()

    return session


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------

def build_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["stream"])

    def _require_auth(request: Request):
        user = get_current_user(request)
        if user is None:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        return None

    # ------------------------------------------------------------------
    # Global stats for ALL active streams (used by Dashboard)
    # Must be registered BEFORE /stream/{source_id} to avoid path conflict
    # ------------------------------------------------------------------
    @router.get("/stream/active-stats")
    def all_active_stream_stats(request: Request):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err

        with _registry_lock:
            snapshot = list(_active_streams.items())

        streams = []
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

    # ------------------------------------------------------------------
    # Main MJPEG stream endpoint
    # ------------------------------------------------------------------
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
        if video_path:
            if not _is_live_stream(video_path) and not Path(video_path).is_absolute():
                video_path = str((PROJECT_ROOT / video_path).resolve())

        # Fix #4: For RTSP we call get_video_info() once here (in the route handler)
        # and pass the frame_size directly to the session — this avoids a second
        # expensive RTSP handshake inside _process_video().
        info = get_video_info(video_path)
        if info is None:
            return JSONResponse(status_code=400, content={"error": "Cannot read video source"})

        config_path = source.counting_config_path

        session = _ensure_stream(
            source_id, video_path, config_path, info.frame_size,
            db=container.db,
            report_service=container.report_service,
            counting_persistence=container.counting_persistence_service,
            source_name=source.name,
        )

        def generate():
            session.add_client()
            last_seq = -1

            try:
                while not session.stop_event.is_set():
                    # Fix #3: Wait until ANY client's Condition is notified.
                    # All clients wake simultaneously — no race with clear().
                    with session._frame_cv:
                        # Wait up to 2 s for a new frame
                        session._frame_cv.wait(timeout=2.0)
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
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + frame_bytes
                        + b"\r\n"
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

    # ------------------------------------------------------------------
    # RAW MJPEG endpoint (no AI processing) — instant preview
    # ------------------------------------------------------------------
    @router.get("/stream/{source_id}/raw")
    def stream_video_raw(request: Request, source_id: int):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err

        container = get_container(request)
        source = container.source_service.get_source(source_id)
        if not source:
            return JSONResponse(status_code=404, content={"error": "Source not found"})

        def generate_raw():
            # Fix #4: use _open_capture for correct RTSP settings
            cap = _open_capture(source.source_uri)
            if not cap.isOpened():
                return
            try:
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    _, buf = cv2.imencode(
                        ".jpg", frame,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 60],
                    )
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + buf.tobytes()
                        + b"\r\n"
                    )
            except GeneratorExit:
                pass
            finally:
                cap.release()

        return StreamingResponse(
            generate_raw(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    # ------------------------------------------------------------------
    # Real-time stats for the active stream
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Stop a stream
    # ------------------------------------------------------------------
    @router.post("/stream/{source_id}/stop")
    def stop_stream(request: Request, source_id: int):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err

        _stop_stream(source_id)
        return {"ok": True}

    # ------------------------------------------------------------------
    # Update vehicle class filter for a running stream
    # ------------------------------------------------------------------
    @router.post("/stream/{source_id}/set-classes")
    async def set_stream_classes(request: Request, source_id: int):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err

        session = _get_session(source_id)
        if session is None:
            return JSONResponse(status_code=404, content={"error": "Stream not active"})

        try:
            body = await request.json()
        except Exception:
            body = {}

        classes = body.get("classes", None)
        if not classes:
            # Empty list or None → reset to count all
            session.active_classes = None
        else:
            session.active_classes = set(str(c).lower() for c in classes)

        return {
            "ok": True,
            "active_classes": sorted(session.active_classes) if session.active_classes else None
        }

    return router
