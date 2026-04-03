# ===== file: configs/settings.py =====
"""Centralized configuration helper.

Reads environment variables from .env and provides access to settings used
across the codebase (paths, device, thresholds, UI toggles...).
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from vehicle_counting_system.configs.paths import MODELS_DIR, PROJECT_ROOT

# Load variables from .env into the environment once.
load_dotenv()


def _read_list(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    # Accept both comma and semicolon separated lists.
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    return [p for p in parts if p]


def _read_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "y"}


@dataclass
class Settings:
    # === Model & device ===

    # Chỉ TensorRT: đường dẫn tới file .engine (không dùng .pt để chạy app).
    yolo_weights: str = os.getenv("YOLO_WEIGHTS", "data/models/yolo11s.engine")

    # Device: cuda:0 = NVIDIA GPU (RTX 30...), fallback CPU nếu không có.
    device: str = os.getenv("DEVICE", "cuda:0")

    # Hint: should we try to use GPU when available?
    use_gpu: bool = _read_bool("USE_GPU", "true")

    # Use half-precision (FP16) on GPU to speed up inference (if supported).
    use_half: bool = _read_bool("USE_HALF", "true")
    # Preferred precision mode for inference: fp16 or fp32.
    # If provided, this overrides USE_HALF.
    yolo_precision: str = os.getenv("YOLO_PRECISION", "").strip().lower()

    # === Detection performance ===

    # Confidence threshold: cao hơn => ít box chất lượng thấp, nhận diện chặt hơn.
    conf_threshold: float = float(os.getenv("CONF_THRESHOLD", "0.49"))

    # Input size for YOLO (imgsz). Smaller => faster but less accurate.
    image_size: int = int(os.getenv("IMAGE_SIZE", "640"))

    # Drop boxes with very small area (in pixels) to remove far/noisy objects.
    min_box_area: float = float(os.getenv("MIN_BOX_AREA", "800.0"))

    # Max detections per frame (cap heavy scenes to avoid lag).
    max_detections: int = int(os.getenv("MAX_DETECTIONS", "150"))

    # Only keep these class names from YOLO (case-sensitive, as returned by model.names).
    allowed_class_names: List[str] = field(
        default_factory=lambda: _read_list(
            "ALLOWED_CLASSES",
            "motorcycle,car,truck,bus",
        )
    )

    # === Runtime & overlay ===

    # End-of-video behavior:
    # - "stop": stop cleanly (release cap/writer, close window) when EOF reached
    # - "hold_last_frame": freeze on last frame, stop all background processing,
    #   keep window responsive until user closes it
    end_of_video_mode: str = os.getenv("END_OF_VIDEO_MODE", "stop").lower()
    # Force the CLI process to exit after cleanup. Useful for Windows/OpenCV demo
    # cases where native handles or library threads keep Python alive in background.
    force_exit_on_shutdown: bool = _read_bool("FORCE_EXIT_ON_SHUTDOWN", "true")

    # Skip frames: 1 = xử lý mọi frame; 2 = mỗi 2 frame 1 lần (nhanh hơn, đếm có thể kém hơn).
    skip_frames: int = int(os.getenv("SKIP_FRAMES", "1"))
    vid_stride: int = int(os.getenv("VID_STRIDE", "1"))

    # Video sharpen: làm rõ nét (unsharp mask). 0=tắt, 0.3-1.0=độ mạnh.
    video_sharpen: float = float(os.getenv("VIDEO_SHARPEN", "0.4"))

    # Làm mượt box/label khi hiển thị (EMA). 0=tắt, 0.3-0.8=độ mượt. Không ảnh hưởng đếm.
    display_smooth_alpha: float = float(os.getenv("DISPLAY_SMOOTH_ALPHA", "0.5"))

    # Overlay options.
    # For counting debug: show bottom-center anchor point.
    show_track_center: bool = _read_bool("SHOW_TRACK_CENTER", "true")
    show_labels: bool = _read_bool("SHOW_LABELS", "true")
    show_confidence: bool = _read_bool("SHOW_CONFIDENCE", "false")

    # ROI rendering mode (friendly names):
    # "hidden" (or "off", "none")  -> no ROI drawn
    # "outline" (or "border")      -> only thin border
    # "soft_fill" (or "filled")    -> soft transparent fill + border
    roi_mode: str = os.getenv("ROI_MODE", "outline").lower()
    # ROI overlay alpha if filled (0..1)
    roi_alpha: float = float(os.getenv("ROI_ALPHA", "0.15"))

    # Counting-line rendering mode:
    # "hidden" (or "off", "none")  -> no line drawn
    # "outline" (or "border")      -> clear line
    # "soft" (or "faded")          -> softer transparent line
    counting_line_mode: str = os.getenv("COUNTING_LINE_MODE", "soft").lower()
    counting_line_alpha: float = float(os.getenv("COUNTING_LINE_ALPHA", "0.35"))
    counting_line_thickness: int = int(os.getenv("COUNTING_LINE_THICKNESS", "2"))
    show_counting_line_label: bool = _read_bool("SHOW_COUNTING_LINE_LABEL", "false")

    # Bounding box: độ dày viền (1=mảnh), bo góc (pixel).
    bbox_thickness: int = int(os.getenv("BBOX_THICKNESS", "1"))
    bbox_corner_radius: int = int(os.getenv("BBOX_CORNER_RADIUS", "4"))
    bbox_label_font_scale: float = float(os.getenv("BBOX_LABEL_FONT_SCALE", "0.5"))

    # Colors (BGR)
    bbox_color: str = os.getenv("BBOX_COLOR", "0,255,0")
    counting_line_color: str = os.getenv("COUNTING_LINE_COLOR", "255,200,0")
    anchor_color: str = os.getenv("ANCHOR_COLOR", "0,128,255")
    stats_bg_color: str = os.getenv("STATS_BG_COLOR", "0,0,0")
    stats_text_color: str = os.getenv("STATS_TEXT_COLOR", "255,255,255")

    def _parse_color(self, value: str):
        parts = [int(p) for p in value.split(",") if p.strip()]
        if len(parts) != 3:
            return (255, 255, 255)
        return tuple(parts)  # type: ignore[return-value]

    # === Tracking (ByteTrack) ===
    # These defaults are chosen for crowded traffic scenes (stable IDs > aggressive new tracks).
    bytetrack_activation_threshold: float = float(os.getenv("BYTETRACK_ACTIVATION_TH", "0.35"))
    bytetrack_matching_threshold: float = float(os.getenv("BYTETRACK_MATCHING_TH", "0.80"))
    bytetrack_lost_buffer: int = int(os.getenv("BYTETRACK_LOST_BUFFER", "80"))
    # NOTE: supervision ByteTrack currently does not emit tracks reliably with >1 here,
    # so keep it at 1 for stable demo output.
    bytetrack_min_consecutive: int = int(os.getenv("BYTETRACK_MIN_CONSEC_FRAMES", "1"))

    # === Classification smoothing (per-track) ===
    class_smoothing_window: int = int(os.getenv("CLASS_SMOOTHING_WINDOW", "15"))
    class_smoothing_min_votes: int = int(os.getenv("CLASS_SMOOTHING_MIN_VOTES", "6"))

    def __post_init__(self) -> None:
        # Chuẩn hóa thiết bị: .env hay dùng "cuda" → PyTorch/Ultralytics ổn định hơn với "cuda:0"
        self.device = self._normalize_device(self.device)
        self._reject_pytorch_weights_path()
        self.yolo_weights = self._resolve_yolo_weights(self.yolo_weights)
        self.yolo_precision = self._normalize_precision(self.yolo_precision)
        # Keep backward compatibility with existing USE_HALF flag.
        if self.yolo_precision:
            self.use_half = self.yolo_precision == "fp16"

    def _normalize_precision(self, value: str) -> str:
        normalized = (value or "").strip().lower()
        if not normalized:
            return "fp16" if self.use_half else "fp32"
        if normalized in {"16", "fp16", "half"}:
            return "fp16"
        if normalized in {"32", "fp32", "float", "float32", "full"}:
            return "fp32"
        return "fp16" if self.use_half else "fp32"

    def _normalize_device(self, value: str) -> str:
        d = (value or "cuda:0").strip()
        low = d.lower()
        if low in {"cuda", "gpu"}:
            return "cuda:0"
        return d

    def _reject_pytorch_weights_path(self) -> None:
        """App chỉ chạy TensorRT .engine — không chấp nhận YOLO_WEIGHTS trỏ tới .pt."""
        raw = (os.getenv("YOLO_WEIGHTS") or "").strip()
        if not raw:
            return
        if raw.lower().split("?")[0].endswith(".pt"):
            raise ValueError(
                "YOLO_WEIGHTS không được trỏ tới file .pt — dự án chỉ dùng TensorRT (.engine).\n"
                "Sửa .env: YOLO_WEIGHTS=data/models/yolo11s.engine (và đặt file engine đúng chỗ).\n"
                "File .pt chỉ dùng khi export: yolo export model=yolo11s.pt format=engine ..."
            )

    def _resolve_yolo_weights(self, raw_value: str) -> str:
        """
        Make local CLI/Web runs robust:
        - accept absolute paths as-is
        - resolve relative weights from both package root and workspace root
        - support exported runtimes such as TensorRT `.engine`
        - auto-fix common typo `yolov11*.pt` -> `yolo11*.pt` when local files exist
        - với .engine: không fallback sang .pt — file phải tồn tại (detector sẽ báo lỗi rõ)
        """
        value = (raw_value or "").strip()
        if not value:
            return str((PROJECT_ROOT / "data" / "models" / "yolo11s.engine").resolve())

        candidate_names = [value]
        # Nhầm đuôi TensorRT: *.tensorPT / *.tensorpt -> thử *.engine cùng tên gốc
        low = value.lower()
        if low.endswith(".tensorpt"):
            candidate_names.append(str(Path(value).with_suffix(".engine")))
        if "yolov11" in value.lower():
            candidate_names.append(value.replace("yolov11", "yolo11"))

        search_roots = [
            Path.cwd(),
            PROJECT_ROOT,
            PROJECT_ROOT.parent,
            MODELS_DIR,
            MODELS_DIR.parent,  # data/
        ]

        def _find_existing(names: List[str]) -> Optional[str]:
            for name in names:
                p = Path(name)
                if p.is_absolute() and p.is_file():
                    return str(p.resolve())
                for root in search_roots:
                    candidate = root / name
                    if candidate.is_file():
                        return str(candidate.resolve())
            return None

        found = _find_existing(candidate_names)
        if found:
            return found

        last = candidate_names[-1]
        p_last = Path(last)
        if not p_last.is_absolute():
            return str((PROJECT_ROOT / p_last).resolve())
        return last


# Singleton settings object used by other modules.
settings = Settings()
