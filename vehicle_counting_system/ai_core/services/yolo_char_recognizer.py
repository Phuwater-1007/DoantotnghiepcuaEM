"""YOLO Character Recognizer — Nhận diện ký tự biển số bằng YOLO.

Thay thế hoàn toàn EasyOCR. Detect từng ký tự (0-9, A-Z) trên ảnh biển số crop,
sắp xếp theo vị trí để ghép thành chuỗi biển số.

Ưu điểm so với EasyOCR:
- Nhanh hơn ~5-10x (YOLO ~5-15ms vs EasyOCR ~50-200ms trên GPU)
- Chính xác hơn vì được train đúng trên font chữ biển số
- Xử lý biển 2 dòng tự nhiên (detect vị trí từng ký tự)
- Không cần dependency easyocr
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO

from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)


class YOLOCharRecognizer:
    """Nhận diện ký tự biển số bằng YOLO Character Detection.

    Pipeline:
    1. YOLO detect từng ký tự trên ảnh biển số crop
    2. Phân chia ký tự thành 1 hoặc 2 dòng dựa trên tọa độ Y
    3. Sắp xếp ký tự trong mỗi dòng theo tọa độ X (trái → phải)
    4. Ghép thành chuỗi biển số hoàn chỉnh
    """

    def __init__(
        self,
        model_path: str | Path,
        conf: float = 0.25,
        imgsz: int = 320,
        use_gpu: bool = True,
    ):
        self.model: Optional[YOLO] = None
        self.conf = conf
        self.imgsz = imgsz
        self.use_gpu = use_gpu

        model_path = Path(model_path)
        if not model_path.exists():
            logger.error("YOLO Char model not found: %s", model_path)
            return

        try:
            logger.info("Loading YOLO Character Detector from %s...", model_path)
            self.model = YOLO(str(model_path))
            logger.info(
                "YOLO Character Detector loaded successfully. "
                "Classes: %s, conf=%.2f, imgsz=%d",
                len(self.model.names),
                self.conf,
                self.imgsz,
            )
        except Exception as e:
            logger.error("Failed to load YOLO Character Detector: %s", e)
            self.model = None

    @property
    def is_ready(self) -> bool:
        return self.model is not None

    def preprocess_plate(self, plate_crop: np.ndarray) -> np.ndarray:
        """Tiền xử lý ảnh biển số trước khi detect ký tự.

        Các bước:
        1. Resize nếu quá nhỏ (chiều cao < 40px)
        2. Tăng contrast nhẹ bằng CLAHE
        """
        if plate_crop is None or plate_crop.size == 0:
            return plate_crop

        try:
            h, w = plate_crop.shape[:2]

            # Resize nếu quá nhỏ — YOLO cần ảnh đủ lớn để detect ký tự
            if h < 40:
                scale = 40.0 / h
                plate_crop = cv2.resize(
                    plate_crop,
                    (int(w * scale), 40),
                    interpolation=cv2.INTER_CUBIC,
                )

            # CLAHE nhẹ để tăng contrast
            lab = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2LAB)
            l_channel = lab[:, :, 0]
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
            lab[:, :, 0] = clahe.apply(l_channel)
            plate_crop = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

            return plate_crop
        except Exception as e:
            logger.debug("Plate preprocessing error: %s", e)
            return plate_crop

    def recognize(self, plate_crop: np.ndarray) -> tuple[str, float] | None:
        """Nhận diện chuỗi biển số từ ảnh biển số đã crop.

        Args:
            plate_crop: Ảnh biển số BGR (đã crop từ ảnh xe)

        Returns:
            (plate_text, avg_confidence) hoặc None nếu không nhận diện được
        """
        if self.model is None:
            return None

        if plate_crop is None or plate_crop.size == 0:
            return None

        # Tiền xử lý
        processed = self.preprocess_plate(plate_crop)

        try:
            results = self.model.predict(
                processed,
                conf=self.conf,
                imgsz=self.imgsz,
                verbose=False,
            )
        except Exception as e:
            logger.debug("YOLO Char predict error: %s", e)
            return None

        if not results or not results[0].boxes or len(results[0].boxes) == 0:
            return None

        # Thu thập ký tự detected
        chars = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            char_name = self.model.names.get(cls_id, "?")

            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            char_h = y2 - y1
            char_w = x2 - x1

            chars.append({
                "char": char_name,
                "conf": conf,
                "cx": cx,
                "cy": cy,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "h": char_h,
                "w": char_w,
            })

        if not chars:
            return None

        # Loại bỏ các detection trùng lặp (NMS nhẹ theo vị trí)
        chars = self._remove_duplicates(chars)

        if not chars:
            return None

        # Ghép ký tự thành chuỗi (hỗ trợ 1 dòng + 2 dòng)
        plate_text = self._assemble_plate_text(chars, processed.shape)
        avg_conf = sum(c["conf"] for c in chars) / len(chars)

        if not plate_text or len(plate_text) < 2:
            return None

        return plate_text, avg_conf

    def _remove_duplicates(self, chars: list[dict], iou_threshold: float = 0.5) -> list[dict]:
        """Loại bỏ các ký tự trùng lặp (overlap quá nhiều).

        Giữ ký tự có confidence cao hơn khi 2 box overlap > iou_threshold.
        """
        if len(chars) <= 1:
            return chars

        # Sắp xếp theo confidence giảm dần
        chars = sorted(chars, key=lambda c: c["conf"], reverse=True)
        keep = []

        for char in chars:
            is_dup = False
            for kept in keep:
                iou = self._calc_iou(char, kept)
                if iou > iou_threshold:
                    is_dup = True
                    break
            if not is_dup:
                keep.append(char)

        return keep

    def _calc_iou(self, a: dict, b: dict) -> float:
        """Tính IoU giữa 2 bounding box."""
        x1 = max(a["x1"], b["x1"])
        y1 = max(a["y1"], b["y1"])
        x2 = min(a["x2"], b["x2"])
        y2 = min(a["y2"], b["y2"])

        inter = max(0, x2 - x1) * max(0, y2 - y1)
        area_a = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"])
        area_b = (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
        union = area_a + area_b - inter

        return inter / max(union, 1e-6)

    def _assemble_plate_text(self, chars: list[dict], img_shape: tuple) -> str:
        """Sắp xếp ký tự theo vị trí → ghép thành chuỗi biển số.

        Tự động xử lý:
        - Biển 1 dòng (ô tô): sắp xếp trái → phải theo X
        - Biển 2 dòng (xe máy): phân chia dòng theo Y, mỗi dòng sắp xếp theo X

        Thuật toán phân dòng:
        - Tính spread Y (khoảng cách Y lớn nhất giữa các ký tự)
        - Nếu spread > 35% chiều cao ảnh → biển 2 dòng
        - Dùng điểm giữa Y để chia 2 dòng
        """
        h_img = img_shape[0]

        if len(chars) <= 1:
            return chars[0]["char"] if chars else ""

        y_coords = [c["cy"] for c in chars]
        y_spread = max(y_coords) - min(y_coords)

        # Tính chiều cao trung bình của ký tự để so sánh
        avg_char_h = sum(c["h"] for c in chars) / len(chars)

        # Quyết định 1 dòng hay 2 dòng
        is_two_line = y_spread > max(h_img * 0.35, avg_char_h * 1.2)

        if is_two_line:
            # Biển 2 dòng: phân chia bằng điểm giữa Y
            mid_y = (max(y_coords) + min(y_coords)) / 2.0

            line1 = sorted(
                [c for c in chars if c["cy"] < mid_y],
                key=lambda c: c["cx"],
            )
            line2 = sorted(
                [c for c in chars if c["cy"] >= mid_y],
                key=lambda c: c["cx"],
            )

            text = "".join(c["char"] for c in line1) + "".join(c["char"] for c in line2)
        else:
            # Biển 1 dòng: sắp xếp trái → phải
            chars_sorted = sorted(chars, key=lambda c: c["cx"])
            text = "".join(c["char"] for c in chars_sorted)

        return text
