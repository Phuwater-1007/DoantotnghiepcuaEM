# ===== file: detectors/yolo_detector.py =====
"""YOLO detector implementation using Ultralytics library.

Nhiệm vụ:
- Chạy YOLO trên frame (tận dụng GPU và FP16 nếu có).
- Lọc theo confidence, class, kích thước bbox, max_detections.
- Trả về danh sách Detection sạch cho tracker.
"""

import gc
import os
from pathlib import Path
from typing import List
import threading

import torch
from ultralytics import YOLO

from vehicle_counting_system.configs.paths import MODELS_DIR
from vehicle_counting_system.configs.settings import settings
from vehicle_counting_system.models.detection import Detection
from vehicle_counting_system.detectors.base_detector import BaseDetector
from vehicle_counting_system.utils.logger import get_logger


logger = get_logger(__name__)


class YOLODetector(BaseDetector):
    def __init__(self, weights_path: str | None = None, device: str | None = None, *, shared: bool = False):
        # Cho phép override từ tham số, nếu không sẽ dùng settings.
        self._shared = bool(shared)
        self._requested_weights = (os.getenv("YOLO_WEIGHTS") or "").strip()
        self.weights = weights_path or settings.yolo_weights
        if Path(str(self.weights)).suffix.lower() == ".pt":
            raise ValueError(
                "Chỉ hỗ trợ inference TensorRT (.engine). Không load file .pt. "
                "Đặt YOLO_WEIGHTS trỏ tới file .engine (ví dụ data/models/yolo11s.engine)."
            )
        self.model_suffix = Path(str(self.weights)).suffix.lower()
        # Ultralytics TensorRT export dùng đuôi .engine
        self.is_tensorrt_engine = self.model_suffix == ".engine"
        self.device = device or settings.device
        self.conf_thres = settings.conf_threshold
        self.img_size = settings.image_size
        self.min_box_area = settings.min_box_area
        self.max_det = settings.max_detections
        self.allowed_names = set(settings.allowed_class_names)
        self._inference_lock = threading.Lock()

        logger.info(
            f"Loading YOLO model from {self.weights} on {self.device} "
            f"(conf>={self.conf_thres}, img_size={self.img_size}, max_det={self.max_det}, "
            f"precision={settings.yolo_precision})"
        )

        wpath = Path(self.weights)
        if self.is_tensorrt_engine and not wpath.is_file():
            raise FileNotFoundError(self._tensorrt_engine_missing_message())

        try:
            self.model = YOLO(self.weights)
        except Exception as exc:
            if self.is_tensorrt_engine:
                logger.exception("Load TensorRT .engine failed.")
                raise RuntimeError(
                    f"{exc}\n\n"
                    "Gợi ý: cài TensorRT Python đúng phiên bản GPU/CUDA; export engine trên cùng máy/GPU; "
                    "đúng imgsz khi export (IMAGE_SIZE trong .env nên khớp imgsz lúc tạo .engine)."
                ) from exc
            raise

        # Quyết định dùng GPU/CPU.
        if self.is_tensorrt_engine:
            if not (settings.use_gpu and self.device.startswith("cuda") and torch.cuda.is_available()):
                raise RuntimeError(
                    "TensorRT runtime requires CUDA GPU inference. "
                    "Set DEVICE=cuda and USE_GPU=true before loading a .engine model."
                )
            logger.info(
                "Using TensorRT (.engine) inference; FP16/FP32 is fixed at export time "
                "(YOLO_PRECISION only affects PyTorch .pt runs)."
            )
        elif settings.use_gpu and self.device.startswith("cuda") and torch.cuda.is_available():
            self.model.to(self.device)
            logger.info("Using CUDA for YOLO inference.")
        else:
            self.device = "cpu"
            logger.info("Using CPU for YOLO inference.")

    def _tensorrt_engine_missing_message(self) -> str:
        req = self._requested_weights or "(YOLO_WEIGHTS)"
        return (
            f"Không thấy file TensorRT: {self.weights}\n"
            f"- Đặt file .engine vào: {MODELS_DIR} (ví dụ {MODELS_DIR / 'yolo11s.engine'})\n"
            f"- Hoặc sửa YOLO_WEIGHTS thành đường dẫn đầy đủ tới file .engine.\n"
            f"- Export (Ultralytics): yolo export model=yolo11s.pt format=engine imgsz={settings.image_size} half=True\n"
            f"- Hiện YOLO_WEIGHTS trong .env: {req!r}\n"
            f"- App chỉ chạy .engine — không dùng .pt để inference."
        )

    def _area(self, x1: float, y1: float, x2: float, y2: float) -> float:
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    def update_params(self, conf_thres: float | None = None, min_box_area: float | None = None) -> None:
        """Cập nhật nhanh thông số model (thay đổi ngay ở lần detect tiếp theo)."""
        if conf_thres is not None:
            self.conf_thres = float(conf_thres)
            logger.info(f"YOLO conf_threshold updated to {self.conf_thres}")
        if min_box_area is not None:
            self.min_box_area = float(min_box_area)
            logger.info(f"YOLO min_box_area updated to {self.min_box_area}")

    def detect(self, frame) -> List[Detection]:
        if self.model is None:
            raise RuntimeError("YOLO detector has been closed.")

        # Ultralytics dùng BGR (mặc định của OpenCV).
        # TensorRT .engine: không truyền half — precision đã cố định trong engine.
        use_half = (not self.is_tensorrt_engine) and (settings.yolo_precision == "fp16")
        
        with self._inference_lock:
            if settings.use_gpu and self.device.startswith("cuda"):
                results = self.model(
                    frame,
                    imgsz=self.img_size,
                    conf=self.conf_thres,
                    max_det=self.max_det,
                    verbose=False,
                    device=self.device,
                    half=use_half,
                )
            else:
                results = self.model(
                    frame,
                    imgsz=self.img_size,
                    conf=self.conf_thres,
                    max_det=self.max_det,
                    verbose=False,
                    device="cpu",
                    half=False,
                )

        detections: List[Detection] = []
        for r in results:
            boxes = r.boxes
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                name = self.model.names.get(cls, str(cls))

                # Lọc theo class phục vụ bài toán, bỏ person, traffic light,...
                if self.allowed_names and name not in self.allowed_names:
                    continue

                # Bỏ bbox quá nhỏ (thường là object xa / nhiễu).
                if self._area(x1, y1, x2, y2) < self.min_box_area:
                    continue

                detections.append(
                    Detection(
                        bbox=(x1, y1, x2, y2),
                        confidence=conf,
                        class_id=cls,
                        class_name=name,
                    )
                )

        return detections

    def close(self) -> None:
        if getattr(self, "_shared", False):
            # Shared detector is process-scoped; keep it alive for subsequent sessions.
            return
        # Explicitly drop the model so reruns do not keep stale GPU state alive.
        if self.model is None:
            return
        logger.info("Closing YOLO detector.")
        try:
            del self.model
        except Exception:
            pass
        self.model = None
        gc.collect()
        try:
            if settings.use_gpu and self.device.startswith("cuda") and torch.cuda.is_available():
                try:
                    torch.cuda.synchronize()
                except Exception:
                    pass
                torch.cuda.empty_cache()
                try:
                    torch.cuda.ipc_collect()
                except Exception:
                    pass
                logger.info("YOLO CUDA resources released.")
        except Exception:
            pass
