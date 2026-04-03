"""MJPEG streaming endpoint – stream video file with YOLO bbox overlay."""

from __future__ import annotations

import threading
import time
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


class _StreamSession:
    """Holds state for a single MJPEG stream."""

    def __init__(self, source_id: int, video_path: str, config_path: str | None, frame_size: tuple[int, int]):
        self.source_id = source_id
        self.video_path = video_path
        self.config_path = config_path
        self.frame_size = frame_size
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.last_stats: dict[str, Any] = {"total": 0, "per_class": {}}
        self.active_clients = 0


# Global registry – at most one stream per source.
_active_streams: dict[int, _StreamSession] = {}
_registry_lock = threading.Lock()


def _stop_stream(source_id: int) -> None:
    with _registry_lock:
        session = _active_streams.pop(source_id, None)
    if session is not None:
        session.stop_event.set()


def _stop_all_streams() -> None:
    with _registry_lock:
        ids = list(_active_streams.keys())
    for sid in ids:
        _stop_stream(sid)


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["stream"])

    def _require_auth(request: Request):
        user = get_current_user(request)
        if user is None:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        return None

    # -----------------------------------------------------------------
    # MJPEG stream endpoint
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

        # Stop any existing stream for this source.
        _stop_stream(source_id)

        session = _StreamSession(
            source_id=source_id,
            video_path=video_path,
            config_path=config_path,
            frame_size=info.frame_size,
        )
        with _registry_lock:
            _active_streams[source_id] = session

        def generate():
            detector = _get_shared_yolo_detector()
            processor = FrameProcessor(
                detector=detector,
                tracker=ByteTrackTracker(),
                counting_lines_path=session.config_path,
                frame_size=session.frame_size,
            )

            cap = cv2.VideoCapture(session.video_path)
            if not cap.isOpened():
                return

            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            frame_delay = 1.0 / fps

            with session.lock:
                session.active_clients += 1

            try:
                while not session.stop_event.is_set():
                    t_start = time.perf_counter()

                    ok, frame = cap.read()
                    if not ok:
                        # Loop back to start (simulate continuous camera)
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        processor.reset()
                        # Reset tracker for new loop
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

                    _, buf = cv2.imencode(
                        ".jpg", processed,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 75],
                    )
                    frame_bytes = buf.tobytes()

                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" +
                        frame_bytes +
                        b"\r\n"
                    )

                    # Pace to roughly match original video FPS.
                    elapsed = time.perf_counter() - t_start
                    sleep_time = frame_delay - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)

            except GeneratorExit:
                pass
            except Exception:
                logger.exception("Stream error for source %s", source_id)
            finally:
                cap.release()
                # Don't close detector (it's shared).
                processor.reset()
                with session.lock:
                    session.active_clients -= 1
                # Clean up if no more clients.
                if session.active_clients <= 0:
                    with _registry_lock:
                        _active_streams.pop(source_id, None)

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

        with _registry_lock:
            session = _active_streams.get(source_id)

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
