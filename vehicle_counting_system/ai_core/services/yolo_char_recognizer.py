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
        1. Resize nếu quá nhỏ (chiều cao < 100px) để nâng cao độ phân giải ký tự
        2. Tăng contrast nhẹ bằng CLAHE
        3. Làm sắc nét các cạnh ký tự bằng unsharp mask
        """
        if plate_crop is None or plate_crop.size == 0:
            return plate_crop

        try:
            h, w = plate_crop.shape[:2]

            # Resize nếu quá nhỏ — YOLO cần ảnh đủ lớn để detect ký tự chính xác
            if h < 100:
                scale = 100.0 / h
                plate_crop = cv2.resize(
                    plate_crop,
                    (int(w * scale), 100),
                    interpolation=cv2.INTER_CUBIC,
                )

            # CLAHE nhẹ để tăng contrast
            lab = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2LAB)
            l_channel = lab[:, :, 0]
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
            lab[:, :, 0] = clahe.apply(l_channel)
            plate_crop = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

            # Làm sắc nét ảnh (Unsharp Mask)
            gaussian = cv2.GaussianBlur(plate_crop, (0, 0), 1.0)
            plate_crop = cv2.addWeighted(plate_crop, 1.5, gaussian, -0.5, 0)

            return plate_crop
        except Exception as e:
            logger.debug("Plate preprocessing error: %s", e)
            return plate_crop

    def _extract_chars_from_results(self, boxes) -> list[dict]:
        """Trích xuất danh sách ký tự từ kết quả predict của YOLO."""
        chars = []
        for box in boxes:
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
        return chars

    def _estimate_skew_angle(self, chars: list[dict]) -> float:
        """Ước lượng góc nghiêng của biển số dựa trên tọa độ tâm của các ký tự."""
        if len(chars) < 2:
            return 0.0

        # Phân chia dòng sơ bộ để fit đường thẳng cho từng dòng
        y_coords = [c["cy"] for c in chars]
        y_spread = max(y_coords) - min(y_coords)
        avg_char_h = sum(c["h"] for c in chars) / len(chars)

        is_two_line = y_spread > avg_char_h * 1.2

        lines = []
        if is_two_line:
            mid_y = (max(y_coords) + min(y_coords)) / 2.0
            lines.append([c for c in chars if c["cy"] < mid_y])
            lines.append([c for c in chars if c["cy"] >= mid_y])
        else:
            lines.append(chars)

        angles = []
        for line_chars in lines:
            if len(line_chars) < 2:
                continue
            # Sắp xếp theo cx để fit từ trái qua phải
            line_chars = sorted(line_chars, key=lambda c: c["cx"])
            xs = np.array([c["cx"] for c in line_chars], dtype=np.float32)
            ys = np.array([c["cy"] for c in line_chars], dtype=np.float32)

            points = np.vstack([xs, ys]).T
            # fitLine trả về [vx, vy, x, y] với vx, vy là normalized direction vector
            [vx, vy, x, y] = cv2.fitLine(points, cv2.DIST_L2, 0, 0.01, 0.01)

            slope = vy[0] / (vx[0] + 1e-9)
            angle = np.arctan(slope) * 180.0 / np.pi
            angles.append(angle)

        if not angles:
            return 0.0
        return float(np.mean(angles))

    def recognize(self, plate_crop: np.ndarray) -> tuple[str, float] | None:
        """Nhận diện chuỗi biển số từ ảnh biển số đã crop.

        Các bước:
        1. Tiền xử lý (phóng to, tăng tương phản, làm nét)
        2. Nhận diện ký tự lần 1
        3. Phát hiện độ nghiêng, xoay thẳng biển số (deskew) và nhận diện lại nếu cần
        4. Sắp xếp ký tự theo dòng và ghép thành chuỗi biển số
        """
        if self.model is None:
            return None

        if plate_crop is None or plate_crop.size == 0:
            return None

        # 1. Tiền xử lý
        processed = self.preprocess_plate(plate_crop)

        # 2. Chạy detect lần 1
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
        chars = self._extract_chars_from_results(results[0].boxes)
        if not chars:
            return None

        # Loại bỏ các trùng lặp (NMS nhẹ)
        chars = self._remove_duplicates(chars)
        if not chars:
            return None

        # 3. Ước lượng góc nghiêng và xoay thẳng biển số (Deskew)
        angle = self._estimate_skew_angle(chars)

        # Nếu nghiêng từ 2 độ trở lên (và dưới 30 độ để tránh sai lệch quá mức do nhiễu)
        if abs(angle) >= 2.0 and abs(angle) <= 30.0:
            try:
                h_img, w_img = processed.shape[:2]
                center = (w_img // 2, h_img // 2)
                # Tính ma trận xoay: xoay ngược lại góc nghiêng để thẳng biển số
                rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
                rotated_processed = cv2.warpAffine(
                    processed, rot_mat, (w_img, h_img),
                    flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
                )

                # Chạy nhận diện lần 2 trên ảnh đã xoay thẳng
                results_rot = self.model.predict(
                    rotated_processed,
                    conf=self.conf,
                    imgsz=self.imgsz,
                    verbose=False,
                )

                if results_rot and results_rot[0].boxes and len(results_rot[0].boxes) > 0:
                    chars_rot = self._extract_chars_from_results(results_rot[0].boxes)
                    chars_rot = self._remove_duplicates(chars_rot)
                    # Chỉ dùng kết quả xoay nếu nó nhận diện được số lượng ký tự tương đương hoặc tốt hơn
                    if chars_rot and len(chars_rot) >= len(chars) - 1:
                        chars = chars_rot
                        processed = rotated_processed
            except Exception as e:
                logger.warning("Failed to deskew plate image: %s", e)

        # 4. Ghép ký tự thành chuỗi (hỗ trợ 1 dòng + 2 dòng)
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

        Thuật toán phân dòng thông minh dựa trên phân cụm khoảng trống trục Y (Y gap clustering).
        """
        h_img = img_shape[0]

        if len(chars) <= 1:
            return chars[0]["char"] if chars else ""

        # Sắp xếp các ký tự theo Y tăng dần
        sorted_by_y = sorted(chars, key=lambda c: c["cy"])

        # Tính chiều cao trung bình của ký tự để so sánh
        avg_char_h = sum(c["h"] for c in chars) / len(chars)

        # Tìm gap lớn nhất giữa hai ký tự liên tiếp theo trục Y
        max_gap = 0.0
        split_idx = -1

        for i in range(len(sorted_by_y) - 1):
            gap = sorted_by_y[i + 1]["cy"] - sorted_by_y[i]["cy"]
            if gap > max_gap:
                max_gap = gap
                split_idx = i + 1

        # Tính khoảng cách Y tổng thể (spread)
        y_coords = [c["cy"] for c in chars]
        y_spread = max(y_coords) - min(y_coords)

        # Quyết định 1 dòng hay 2 dòng dựa trên phân cụm khoảng trống Y
        is_two_line = (max_gap > avg_char_h * 0.45) and (y_spread > avg_char_h * 1.0)

        if is_two_line and split_idx != -1:
            # Biển 2 dòng: phân chia tại split_idx thành dòng 1 và dòng 2
            line1_chars = sorted_by_y[:split_idx]
            line2_chars = sorted_by_y[split_idx:]

            # Sắp xếp các ký tự trong mỗi dòng từ trái qua phải theo trục X
            line1 = sorted(line1_chars, key=lambda c: c["cx"])
            line2 = sorted(line2_chars, key=lambda c: c["cx"])

            text = "".join(c["char"] for c in line1) + "".join(c["char"] for c in line2)
        else:
            # Biển 1 dòng: sắp xếp toàn bộ từ trái qua phải theo trục X
            chars_sorted = sorted(chars, key=lambda c: c["cx"])
            text = "".join(c["char"] for c in chars_sorted)

        return text
