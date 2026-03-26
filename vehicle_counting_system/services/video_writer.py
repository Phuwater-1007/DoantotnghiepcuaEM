from __future__ import annotations

"""
Thin wrapper around cv2.VideoWriter to ensure resources are released cleanly.
"""

from pathlib import Path

import cv2

from vehicle_counting_system.utils.file_utils import ensure_dir


class VideoWriter:
    def __init__(self, path: str, fourcc: str, fps: float, frame_size: tuple[int, int]):
        self.path = Path(path)
        ensure_dir(self.path)
        self._writer = cv2.VideoWriter(
            str(self.path),
            cv2.VideoWriter_fourcc(*fourcc),
            fps,
            frame_size,
        )

    @property
    def is_open(self) -> bool:
        return self._writer is not None and self._writer.isOpened()

    def write(self, frame) -> None:
        if self.is_open:
            self._writer.write(frame)

    def release(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None

    def __del__(self):
        # Đảm bảo được gọi ngay cả khi người dùng quên release().
        self.release()

