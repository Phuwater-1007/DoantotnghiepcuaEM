# ===== file: utils/video_utils.py =====
"""Video I/O utilities - pattern tham khảo từ supervision, ultralytics.

- VideoInfo: metadata video (fps, resolution, total_frames)
- get_video_info(): đọc metadata trước khi xử lý
- validate_video_source(): kiểm tra nguồn video có mở được không
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2

from vehicle_counting_system.utils.file_utils import VIDEO_EXTENSIONS


@dataclass
class VideoInfo:
    """Metadata video - tương tự supervision.VideoInfo."""

    width: int
    height: int
    fps: float
    total_frames: int
    codec: Optional[str] = None
    path: Optional[str] = None

    @property
    def frame_size(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def duration_seconds(self) -> float:
        if self.fps <= 0:
            return 0.0
        return self.total_frames / self.fps


def get_video_info(source: str | int) -> Optional[VideoInfo]:
    """
    Đọc metadata video từ path hoặc camera index.
    Trả về None nếu không mở được.
    """
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        return None

    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))

        if not fps or fps <= 1e-6:
            fps = 25.0
        if width <= 0 or height <= 0:
            return None

        codec_str = "".join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4)) if fourcc else None

        return VideoInfo(
            width=width,
            height=height,
            fps=float(fps),
            total_frames=max(0, total),
            codec=codec_str,
            path=str(source) if isinstance(source, (str, Path)) else None,
        )
    finally:
        cap.release()


def validate_video_source(source: str | int) -> tuple[bool, str]:
    """
    Kiểm tra nguồn video có mở được không.
    Trả về (ok, message).
    """
    if isinstance(source, int):
        info = get_video_info(source)
        if info is None:
            return False, f"Không mở được camera index {source}"
        return True, ""

    path = Path(source)
    if not path.exists():
        return False, f"File không tồn tại: {path}"

    if path.is_dir():
        return False, f"Đường dẫn là thư mục, cần file video: {path}"

    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return False, f"Định dạng không hỗ trợ. Cho phép: {', '.join(sorted(VIDEO_EXTENSIONS))}"

    info = get_video_info(str(path.resolve()))
    if info is None:
        return False, f"Không đọc được video (file hỏng hoặc codec không hỗ trợ): {path}"

    return True, ""


def normalize_video_path(source: str) -> str:
    """Chuẩn hóa đường dẫn video - absolute, dùng cho cv2.VideoCapture."""
    p = Path(source.strip())
    if p.is_absolute() and p.exists():
        return str(p.resolve())
    return str(p.resolve() if p.exists() else p)
