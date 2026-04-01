from __future__ import annotations

import time
from pathlib import Path
from threading import Event
from threading import Lock
from typing import Callable

import cv2

from vehicle_counting_system.configs.paths import OUTPUT_VIDEOS_DIR
from vehicle_counting_system.configs.settings import settings
from vehicle_counting_system.core.frame_processor import FrameProcessor
from vehicle_counting_system.core.hardware_manager import empty_gpu_cache_if_needed
from vehicle_counting_system.detectors.yolo_detector import YOLODetector
from vehicle_counting_system.services.video_writer import VideoWriter
from vehicle_counting_system.trackers.bytetrack_tracker import ByteTrackTracker
from vehicle_counting_system.utils.file_utils import ensure_dir
from vehicle_counting_system.utils.logger import get_logger
from vehicle_counting_system.utils.video_utils import get_video_info, validate_video_source

logger = get_logger(__name__)

_SHARED_YOLO_DETECTOR = None
_SHARED_YOLO_LOCK = Lock()


def _get_shared_yolo_detector() -> YOLODetector:
    """
    Reuse a single YOLO model instance across analysis sessions.

    Without this, each session constructs YOLODetector and reloads weights,
    which can cause VRAM/RAM pressure and instability on repeated runs.
    """
    global _SHARED_YOLO_DETECTOR
    if _SHARED_YOLO_DETECTOR is not None:
        return _SHARED_YOLO_DETECTOR
    with _SHARED_YOLO_LOCK:
        if _SHARED_YOLO_DETECTOR is None:
            _SHARED_YOLO_DETECTOR = YOLODetector(shared=True)
    return _SHARED_YOLO_DETECTOR


def get_ai_config() -> dict:
    """Read current YOLO config."""
    det = _get_shared_yolo_detector()
    return {
        "conf_threshold": getattr(det, "conf_thres", 0.5),
        "min_box_area": getattr(det, "min_box_area", 100.0)
    }


def update_ai_config(conf_thres: float | None = None, min_box_area: float | None = None) -> None:
    """Update active YOLO parameters."""
    det = _get_shared_yolo_detector()
    det.update_params(conf_thres=conf_thres, min_box_area=min_box_area)


def analyze_video_source(
    source_uri: str,
    *,
    output_path: str | Path,
    counting_lines_path: str | None = None,
    stop_event: Event | None = None,
    vid_stride: int | None = None,
    progress_callback: Callable[[object, object | None, int, int], None] | None = None,
) -> dict:
    """
    Phân tích video: detect -> track -> count -> ghi output.
    Pattern tham khảo: supervision VideoSink, get_video_frames_generator.
    """
    output_path = Path(output_path)
    ensure_dir(output_path)

    ok, msg = validate_video_source(source_uri)
    if not ok:
        raise IOError(msg)

    info = get_video_info(source_uri)
    if info is None:
        raise IOError(f"Không đọc được metadata video: {source_uri}")

    stride = vid_stride if vid_stride is not None else getattr(settings, "vid_stride", 1)
    stride = max(1, int(stride))

    # Reuse YOLO model between sessions to reduce startup time/VRAM churn.
    _shared_detector = _get_shared_yolo_detector()
    processor = FrameProcessor(
        detector=_shared_detector,
        tracker=ByteTrackTracker(),
        counting_lines_path=counting_lines_path,
        frame_size=info.frame_size,
    )
    writer = VideoWriter(str(output_path), "mp4v", info.fps, info.frame_size)
    if not writer.is_open:
        processor.close()
        raise IOError(f"Không tạo được file output: {output_path}")

    cap = cv2.VideoCapture(source_uri)
    if not cap.isOpened():
        writer.release()
        processor.close()
        raise IOError(f"Không mở được video: {source_uri}")

    started_at = time.time()
    frames_processed = 0
    frame_index = 0
    status = "completed"
    last_processed = None
    last_stats_snapshot: dict | None = None

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                status = "stopped"
                break

            ok, frame = cap.read()
            if not ok:
                break

            if frame_index % stride == 0:
                last_processed = processor.process(frame)
                frames_processed += 1
                # Snapshot stats at each processed frame so the final summary is consistent.
                stats = processor.last_stats
                if stats is not None:
                    try:
                        last_stats_snapshot = {
                            "total": int(stats.total),
                            "per_class": dict(stats.per_class),
                        }
                    except Exception:
                        pass
                if progress_callback is not None and last_processed is not None:
                    progress_callback(last_processed, processor.last_stats, frame_index, frames_processed)

            if last_processed is not None:
                writer.write(last_processed)

            frame_index += 1
    finally:
        try:
            cap.release()
        except Exception:
            pass
        try:
            writer.release()
        except Exception:
            pass
        try:
            processor.close()
        except Exception:
            pass
        empty_gpu_cache_if_needed()

    stats = processor.last_stats
    if last_stats_snapshot is not None:
        total = int(last_stats_snapshot.get("total", 0) or 0)
        per_class = dict(last_stats_snapshot.get("per_class", {}) or {})
    else:
        total = int(stats.total) if stats is not None else 0
        per_class = dict(stats.per_class) if stats is not None else {}

    elapsed = max(0.001, time.time() - started_at)
    logger.info(
        "Headless analysis finished. source=%s status=%s frames=%s elapsed=%.2fs total=%s",
        source_uri,
        status,
        frames_processed,
        elapsed,
        total,
    )
    return {
        "status": status,
        "frames_processed": frames_processed,
        "elapsed_seconds": round(elapsed, 2),
        "output_video_path": str(output_path),
        "total": total,
        "per_class": per_class,
    }


def default_output_path(session_id: int) -> Path:
    return OUTPUT_VIDEOS_DIR / f"session_{session_id}.mp4"
