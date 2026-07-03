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
# Limit threads to optimize RAM and CPU overhead on Windows
try:
    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
except Exception:
    pass

try:
    import cv2
    cv2.setNumThreads(1)
except Exception:
    pass

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
        self.nms_iou_thres = getattr(settings, 'nms_iou_threshold', 0.45)
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

        # Warmup model to load backend (AutoBackend) and prevent lazy loading / threading issues in TensorRT
        try:
            import numpy as np
            dummy_w = 640 if self.img_size <= 0 else self.img_size
            dummy = np.zeros((dummy_w, dummy_w, 3), dtype=np.uint8)
            logger.info(f"Warming up YOLO model with imgsz={dummy_w}... Detector ID: {id(self)}, Model ID: {id(self.model)}")
            # Perform first predict to force deserialize engine and build execution context on the current thread
            if self.device.startswith("cuda"):
                self.model(dummy, imgsz=dummy_w, verbose=False, device=self.device)
            else:
                self.model(dummy, imgsz=dummy_w, verbose=False, device="cpu")
            
            # Verify shape mismatch if TensorRT engine
            if self.is_tensorrt_engine and hasattr(self.model, "predictor") and self.model.predictor is not None:
                backend = self.model.predictor.model
                if backend is not None and hasattr(backend, "imgsz"):
                    engine_imgsz = list(backend.imgsz)
                    # backend.imgsz is typically [H, W] or similar. Let's compare with self.img_size.
                    # TensorRT static engines have a strict size.
                    if engine_imgsz and (self.img_size not in engine_imgsz):
                        logger.warning(
                            f"=== SHAPE MISMATCH WARNING ===\n"
                            f"IMAGE_SIZE in .env is {self.img_size}, but TensorRT engine is compiled with imgsz={engine_imgsz}.\n"
                            f"This may lead to inference failure or reduced accuracy.\n"
                            f"Ensure your .env IMAGE_SIZE matches the engine's compiled shape!\n"
                            f"=============================="
                        )
            logger.info(f"YOLO model warmed up successfully. Predictor ID: {id(getattr(self.model, 'predictor', None))}")
        except Exception as e:
            logger.warning(f"YOLO model warmup failed: {e}. Lazy loading will be used.")

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

    _SMALL_VEHICLE_CLASSES = {"motorcycle", "bicycle"}

    def _get_min_area_for_class(self, class_name: str) -> float:
        """Xe máy/xe đạp cho phép bbox nhỏ hơn vì chúng nhỏ hơn ô tô nhiều."""
        if class_name in self._SMALL_VEHICLE_CLASSES:
            return max(80.0, self.min_box_area * 0.33)  # ~83px cho motorcycle (với min_box_area=250)
        return self.min_box_area

    def _get_adaptive_min_area(self, class_name: str, bottom_y: float, frame_h: int) -> float:
        """Tính MIN_BOX_AREA adaptive theo vị trí Y trong frame.
        
        Xe ở trên (xa camera) -> ngưỡng nhỏ hơn.
        Xe ở dưới (gần camera) -> ngưỡng lớn hơn.
        """
        y_ratio = bottom_y / max(1, frame_h)
        # Bắt chước phối cảnh: diện tích tỷ lệ nghịch với bình phương khoảng cách
        # Ta dùng bình phương tỷ lệ Y làm hệ số scale
        scale = y_ratio * y_ratio
        
        if class_name in self._SMALL_VEHICLE_CLASSES:
            base = self.min_box_area * 0.33
            min_limit = 20.0
        else:
            base = self.min_box_area
            min_limit = 50.0
            
        scaled_min = base * scale
        # Đảm bảo giới hạn dưới cực tiểu để không bị lọc các xe máy siêu nhỏ ở xa
        return max(min_limit, min(base, scaled_min))

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

        frame_h = frame.shape[0] if hasattr(frame, 'shape') else 720
        frame_w = frame.shape[1] if hasattr(frame, 'shape') else 1280

        # Ultralytics dùng BGR (mặc định của OpenCV).
        # TensorRT .engine: không truyền half — precision đã cố định trong engine.
        use_half = (not self.is_tensorrt_engine) and (settings.yolo_precision == "fp16")
        
        with self._inference_lock:
            if settings.use_gpu and self.device.startswith("cuda"):
                results = self.model(
                    frame,
                    imgsz=self.img_size,
                    conf=self.conf_thres,
                    iou=self.nms_iou_thres,
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
                    iou=self.nms_iou_thres,
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
                # Adaptive: tự động điều chỉnh MIN_BOX_AREA theo tọa độ Y của bbox (phối cảnh xa gần)
                min_area = self._get_adaptive_min_area(name, y2, frame_h)
                if self._area(x1, y1, x2, y2) < min_area:
                    continue

                # Lọc bbox tỷ lệ bất thường (quá dẹp hoặc quá cao)
                w = x2 - x1
                h = y2 - y1
                aspect = w / max(h, 1)
                
                # Nới lỏng giới hạn dưới cho xe máy vì từ trên cao xuống xe máy rất dài và hẹp
                if name in {"motorcycle", "bicycle"}:
                    if aspect > 3.0 or aspect < 0.05:
                        continue
                else:
                    if aspect > 5.0 or aspect < 0.10:
                        continue

                # Bỏ xe bị cắt quá nhiều ở rìa frame (>50% box ngoài frame)
                margin = 5
                if x1 < margin or y1 < margin or x2 > frame_w - margin or y2 > frame_h - margin:
                    visible_w = min(x2, frame_w - margin) - max(x1, margin)
                    visible_h = min(y2, frame_h - margin) - max(y1, margin)
                    if visible_w < w * 0.5 or visible_h < h * 0.5:
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
