# ===== file: core/pipeline.py =====
"""High-level pipeline orchestrator that reads video frames and applies
FrameProcessor. Handles input/output paths and simple control loop."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import gc
import threading
import time
import cv2

from vehicle_counting_system.configs.settings import settings
from vehicle_counting_system.core.frame_processor import FrameProcessor
from vehicle_counting_system.core.hardware_manager import empty_gpu_cache_if_needed
from vehicle_counting_system.core.shutdown_manager import run_cleanup_step
from vehicle_counting_system.detectors.yolo_detector import YOLODetector
from vehicle_counting_system.services.export_service import ExportService
from vehicle_counting_system.services.video_writer import VideoWriter
from vehicle_counting_system.trackers.bytetrack_tracker import ByteTrackTracker
from vehicle_counting_system.utils.file_utils import ensure_dir
from vehicle_counting_system.utils.logger import get_logger


class ProcessingState(str, Enum):
    idle = "idle"
    running = "running"
    paused = "paused"  # reserved for future UI
    stopping = "stopping"
    finished = "finished"
    closed = "closed"


@dataclass(frozen=True)
class EndOfVideo:
    mode: str  # "stop" | "hold_last_frame"


class Pipeline:
    def __init__(
        self,
        input_source,
        output_path: str | None = None,
        *,
        counting_lines_path: str | None = None,
        export_csv: bool = True,
        window_name: str = "Vehicle Counting",
    ):
        self.logger = get_logger(__name__)
        self.input_source = input_source
        self.output_path = output_path
        self.window_name = window_name
        self.counting_lines_path = counting_lines_path
        self.processor = None
        self.exporter = ExportService() if export_csv else None
        self.skip_frames = max(1, settings.skip_frames)

        if output_path:
            ensure_dir(output_path)
            self.writer = None
        else:
            self.writer = None

        self._cap: cv2.VideoCapture | None = None
        self._stop_event = threading.Event()
        self._cleanup_once = False
        self.state: ProcessingState = ProcessingState.idle
        self._last_frame = None
        self._window_created = False
        self._stop_reason = "not_started"
        mode = (settings.end_of_video_mode or "stop").lower()
        if mode not in {"stop", "hold_last_frame"}:
            mode = "stop"
        self._end_of_video = EndOfVideo(mode=mode)

    def request_stop(self, reason: str) -> None:
        # Idempotent: can be called multiple times (e.g. close event + EOF).
        if self.state in {ProcessingState.stopping, ProcessingState.finished, ProcessingState.closed}:
            return
        self._stop_reason = reason
        self.logger.info("Stop requested: %s", reason)
        self.state = ProcessingState.stopping
        self._stop_event.set()

    def stop_processing(self) -> None:
        self.request_stop("stop_processing called")

    def shutdown_processing(self) -> None:
        self.request_stop("shutdown_processing called")

    def close(self, reason: str = "pipeline.close called") -> None:
        self.request_stop(reason)
        self.cleanup_resources()

    def cleanup_resources(self) -> None:
        # Cleanup must only run once (avoid double-release + cv2 errors).
        if self._cleanup_once:
            return
        self._cleanup_once = True
        self._stop_event.set()
        self.logger.info("Cleanup started. state=%s reason=%s", self.state, self._stop_reason)

        cap, self._cap = self._cap, None
        if cap is not None:
            run_cleanup_step("release VideoCapture", cap.release, timeout=1.5)

        writer, self.writer = self.writer, None
        if writer is not None:
            run_cleanup_step("release VideoWriter", writer.release, timeout=2.5)

        def _destroy_windows() -> None:
            try:
                # Prefer destroying only our window (avoid killing other OpenCV windows).
                cv2.destroyWindow(self.window_name)
            except Exception:
                cv2.destroyAllWindows()

        run_cleanup_step("destroy OpenCV windows", _destroy_windows, timeout=1.5)
        self._window_created = False

        def _flush_highgui_events() -> None:
            # Flush pending HighGUI events on Windows so the process does not linger
            # after the user closes the display window.
            for _ in range(5):
                try:
                    cv2.waitKey(1)
                except Exception:
                    break
                time.sleep(0.01)

        run_cleanup_step("flush OpenCV events", _flush_highgui_events, timeout=1.0)
        if self.processor is not None:
            run_cleanup_step("close FrameProcessor", self.processor.close, timeout=4.0)
        run_cleanup_step("clear GPU cache", empty_gpu_cache_if_needed, timeout=2.0)
        gc.collect()
        self.logger.info("Cleanup finished.")

    def _window_closed(self) -> bool:
        if not self._window_created:
            return False
        try:
            return cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1
        except Exception:
            return True

    def _open_capture(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.input_source)
        if not cap.isOpened():
            raise IOError(f"Cannot open source: {self.input_source}")
        self._cap = cap
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        detector = YOLODetector()
        tracker = ByteTrackTracker()
        self.processor = FrameProcessor(
            detector=detector,
            tracker=tracker,
            counting_lines_path=self.counting_lines_path,
            frame_size=(width, height),
        )
        return cap

    def _compute_frame_delay(self, cap: cv2.VideoCapture) -> tuple[float, int]:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 1e-6:
            fps = 25.0
        delay_ms = max(1, min(10, int(1000 / fps)))
        return fps, delay_ms

    def _open_writer(self, cap: cv2.VideoCapture, fps: float) -> None:
        if not self.output_path:
            self.writer = None
            return

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        writer = VideoWriter(
            path=str(self.output_path),
            fourcc="mp4v",
            fps=fps,
            frame_size=(width, height),
        )
        if not writer.is_open:
            writer.release()
            raise IOError(f"Cannot open output video writer: {self.output_path}")
        self.writer = writer

    def _open_window(self) -> None:
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        self._window_created = True
        self.logger.info("OpenCV window created.")

    def _read_next_frame(self) -> tuple[bool, object | None]:
        if self._cap is None:
            raise RuntimeError("Video capture is not initialized.")
        return self._cap.read()

    def _process_frame(self, frame, frame_idx: int):
        if self.processor is None:
            return frame
        if frame_idx % self.skip_frames == 0:
            return self.processor.process(frame)
        return frame

    def _present_frame(self, frame) -> bool:
        try:
            if self.writer:
                self.writer.write(frame)
            cv2.imshow(self.window_name, frame)
            return True
        except Exception:
            self.request_stop("imshow failed or window already closed")
            return False

    def _poll_ui_events(self, delay_ms: int) -> bool:
        if not self._window_created:
            return self._stop_event.is_set()
        try:
            key = cv2.waitKey(delay_ms) & 0xFF
        except Exception:
            self.request_stop("waitKey failed")
            return True
        if key == ord("q"):
            self.request_stop("keyboard quit")
            return True
        if self._window_closed():
            self.request_stop("window close detected")
            return True
        return False

    def _export_results(self) -> None:
        if self.exporter and self.processor is not None and self.processor.last_stats is not None:
            self.exporter.export_summary_csv(self.processor.last_stats)
            self.exporter.export_summary_json(self.processor.last_stats)

    def _handle_end_of_video(self, last_frame) -> None:
        # Ensure no more inference/tracking is running after EOF.
        self.state = ProcessingState.finished
        self._stop_event.set()
        self._stop_reason = "end_of_video"
        self.logger.info("End of video reached. mode=%s", self._end_of_video.mode)

        if self._end_of_video.mode == "hold_last_frame" and last_frame is not None:
            # Freeze on last frame, keep UI responsive, wait for user to close.
            try:
                cv2.imshow(self.window_name, last_frame)
            except Exception:
                return

            while not self._stop_event.is_set():
                if self._poll_ui_events(10):
                    break

    def run(self):
        if self.state == ProcessingState.running:
            raise RuntimeError("Pipeline is already running.")

        # Reset run-scoped state so this Pipeline can be reused.
        self._stop_event.clear()
        self._cleanup_once = False
        self._last_frame = None
        self._stop_reason = "running"
        if self.processor is not None:
            self.processor.reset()
        self.state = ProcessingState.running
        self.logger.info("Pipeline run started. source=%s output=%s", self.input_source, self.output_path)

        cap = self._open_capture()
        fps, delay_ms = self._compute_frame_delay(cap)
        self._open_writer(cap, fps)
        self._open_window()

        frame_idx = 0
        try:
            while True:
                if self._stop_event.is_set():
                    break

                # Pump window events before the next inference step so a close click
                # is observed immediately instead of processing more frames headlessly.
                if self._poll_ui_events(1):
                    break

                ret, frame = self._read_next_frame()
                if not ret:
                    # EOF or read failure: handle as "finished" (mode-dependent).
                    self._handle_end_of_video(self._last_frame)
                    break

                processed = self._process_frame(frame, frame_idx)
                self._last_frame = processed

                if not self._present_frame(processed):
                    break

                if self._poll_ui_events(delay_ms):
                    break

                frame_idx += 1
        finally:
            # Decide end state before cleanup.
            if self.state == ProcessingState.running:
                # Exited loop without EOF handler => user closed window (no stop requested).
                self.state = ProcessingState.closed if not self._stop_event.is_set() else ProcessingState.stopping

            self.cleanup_resources()

            if self.state == ProcessingState.stopping:
                self.state = ProcessingState.finished

            self.logger.info("Pipeline run finished. final_state=%s reason=%s", self.state, self._stop_reason)
            self._export_results()
