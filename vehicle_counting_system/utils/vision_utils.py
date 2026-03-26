"""Computer vision utilities for drawing overlay.

Mục tiêu:
- Hiển thị đủ thông tin để debug (ID + class + tổng đếm)
- Hạn chế gây "loạn" màn hình
- Có option bật/tắt center point, nhãn...
"""

from __future__ import annotations

from typing import Dict, Tuple, Sequence

import cv2
import numpy as np

from vehicle_counting_system.models.tracked_object import TrackedObject
from vehicle_counting_system.configs.settings import settings
from vehicle_counting_system.utils.math_utils import get_bbox_bottom_center

BBox = Tuple[float, float, float, float]
Point = Tuple[float, float]


def sharpen_frame(frame, amount: float = 0.4):
    """Làm rõ nét video bằng unsharp mask. amount: 0=tắt, 0.3-1.0=độ mạnh."""
    if amount <= 0:
        return frame
    import numpy as np
    gaussian = cv2.GaussianBlur(frame, (0, 0), 2.0)
    return cv2.addWeighted(frame, 1.0 + amount, gaussian, -amount, 0)


# Font đẹp hơn SIMPLEX: DUPLEX rõ ràng, TRIPLEX đậm.
_FONT = cv2.FONT_HERSHEY_DUPLEX
_FONT_SCALE_LABEL = 0.5
_FONT_SCALE_STATS = 0.7
_FONT_THICKNESS = 1


def _draw_rounded_rect(
    frame,
    x1: int, y1: int, x2: int, y2: int,
    color: Tuple[int, int, int],
    thickness: int,
    radius: int,
) -> None:
    """Vẽ hình chữ nhật bo góc mảnh mai."""
    if radius <= 0 or radius > min(x2 - x1, y2 - y1) // 2:
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        return
    cv2.line(frame, (x1 + radius, y1), (x2 - radius, y1), color, thickness, cv2.LINE_AA)
    cv2.line(frame, (x1 + radius, y2), (x2 - radius, y2), color, thickness, cv2.LINE_AA)
    cv2.line(frame, (x1, y1 + radius), (x1, y2 - radius), color, thickness, cv2.LINE_AA)
    cv2.line(frame, (x2, y1 + radius), (x2, y2 - radius), color, thickness, cv2.LINE_AA)
    cv2.ellipse(frame, (x1 + radius, y1 + radius), (radius, radius), 180, 0, 90, color, thickness, cv2.LINE_AA)
    cv2.ellipse(frame, (x2 - radius, y1 + radius), (radius, radius), 270, 0, 90, color, thickness, cv2.LINE_AA)
    cv2.ellipse(frame, (x2 - radius, y2 - radius), (radius, radius), 0, 0, 90, color, thickness, cv2.LINE_AA)
    cv2.ellipse(frame, (x1 + radius, y2 - radius), (radius, radius), 90, 0, 90, color, thickness, cv2.LINE_AA)


def draw_bbox(
    frame,
    bbox: BBox,
    label: str | None = None,
    color: Tuple[int, int, int] | None = None,
) -> None:
    x1, y1, x2, y2 = map(int, bbox)
    if color is None:
        color = settings._parse_color(settings.bbox_color)
    thick = max(1, getattr(settings, "bbox_thickness", 1))
    radius = max(0, getattr(settings, "bbox_corner_radius", 4))
    _draw_rounded_rect(frame, x1, y1, x2, y2, color, thick, radius)
    if label:
        scale = getattr(settings, "bbox_label_font_scale", _FONT_SCALE_LABEL)
        (tw, th), baseline = cv2.getTextSize(label, _FONT, scale, _FONT_THICKNESS)
        pad = 5
        lbl_x1 = x1
        lbl_y1 = y1 - th - baseline - pad
        lbl_x2 = x1 + tw + pad * 2
        lbl_y2 = y1
        _draw_rounded_rect(frame, lbl_x1, lbl_y1, lbl_x2, lbl_y2, color, thick, min(radius, 3))
        cv2.putText(
            frame, label,
            (x1 + pad, y1 - baseline - pad // 2),
            _FONT,
            scale,
            (255, 255, 255),
            _FONT_THICKNESS,
            cv2.LINE_AA,
        )


def draw_center(
    frame,
    center: Point,
    color: Tuple[int, int, int] | None = None,
) -> None:
    cx, cy = map(int, center)
    if color is None:
        color = settings._parse_color(settings.anchor_color)
    cv2.circle(frame, (cx, cy), 3, color, -1)


def draw_counting_line(
    frame,
    start: Tuple[int, int],
    end: Tuple[int, int],
    color: Tuple[int, int, int] | None = None,
    label: str | None = None,
) -> None:
    if color is None:
        color = settings._parse_color(settings.counting_line_color)

    mode = settings.counting_line_mode
    if mode in {"hidden", "none", "off"}:
        return

    thickness = max(1, int(settings.counting_line_thickness))
    if mode in {"soft", "faded"}:
        overlay = frame.copy()
        cv2.line(overlay, start, end, color, thickness, cv2.LINE_AA)
        alpha = max(0.0, min(1.0, settings.counting_line_alpha))
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    else:
        cv2.line(frame, start, end, color, thickness, cv2.LINE_AA)

    if label and settings.show_counting_line_label:
        x = int((start[0] + end[0]) / 2)
        y = int((start[1] + end[1]) / 2) - 6
        cv2.putText(frame, label, (x, y), _FONT, 0.55, color, _FONT_THICKNESS, cv2.LINE_AA)


def draw_statistics(
    frame,
    stats: Dict[str, int],
    origin: Tuple[int, int] = (10, 30),
) -> None:
    x, y = origin
    lines = [f"{k}: {v}" for k, v in stats.items()]
    if not lines:
        return

    # Measure text block
    max_w = 0
    line_h = 0
    for text in lines:
        (tw, th), _ = cv2.getTextSize(text, _FONT, _FONT_SCALE_STATS, _FONT_THICKNESS)
        max_w = max(max_w, tw)
        line_h = max(line_h, th)
    padding = 10
    bg_color = settings._parse_color(settings.stats_bg_color)
    text_color = settings._parse_color(settings.stats_text_color)

    # Semi-transparent background
    x2 = x + max_w + 2 * padding
    y2 = y + len(lines) * (line_h + 6) + padding
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y - padding), (x2, y2), bg_color, -1)
    alpha = 0.4
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

    # Draw text
    cy = y
    for text in lines:
        cv2.putText(
            frame, text,
            (x + padding // 2, cy),
            _FONT,
            _FONT_SCALE_STATS,
            text_color,
            _FONT_THICKNESS,
            cv2.LINE_AA,
        )
        cy += line_h + 6


def draw_track(
    frame,
    track: TrackedObject,
    *,
    show_center: bool = False,
    show_label: bool = True,
    color: Tuple[int, int, int] | None = None,
    bbox_override: Tuple[float, float, float, float] | None = None,
) -> None:
    bbox = bbox_override if bbox_override is not None else track.bbox
    anchor = get_bbox_bottom_center(bbox) if bbox_override is not None else track.last_anchor()
    label = None
    if show_label:
        short_cls = track.class_name
        did = track.get_display_id()
        if settings.show_confidence:
            label = f"{short_cls} #{did} {track.confidence:.2f}"
        else:
            label = f"{short_cls} #{did}"
    draw_bbox(frame, bbox, label=label, color=color)
    if show_center:
        draw_center(frame, anchor)


def draw_roi_polygon(
    frame,
    points: Sequence[Tuple[int, int]],
    color: Tuple[int, int, int] | None = None,
) -> None:
    if not points:
        return
    pts = [(int(x), int(y)) for x, y in points]
    if color is None:
        color = (0, 255, 255)

    mode = settings.roi_mode
    # Map friendly names in .env to internal modes.
    if mode in {"hidden", "none"}:
        return
    if mode in {"outline", "border"}:
        # Only draw border below.
        pass
    elif mode in {"soft_fill", "filled"}:
        overlay = frame.copy()
        poly = np.array(pts, dtype=np.int32)
        cv2.fillPoly(overlay, [poly], color)
        alpha = max(0.0, min(1.0, settings.roi_alpha))
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    elif mode in {"off"}:
        return

    # Always draw border in outline/filled mode.
    for i in range(len(pts)):
        cv2.line(frame, pts[i], pts[(i + 1) % len(pts)], color, 1)
