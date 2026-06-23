"""AI service to detect license plates in vehicle crops and recognize characters using YOLO.

Pipeline 100% YOLO:
- YOLO 2: Detect vùng biển số trên ảnh xe crop
- YOLO 3: Detect từng ký tự (0-9, A-Z) trên ảnh biển số crop
- Post-processing: Sửa lỗi cú pháp biển VN, validate format
"""
from __future__ import annotations

import os
import re
import cv2
import numpy as np
from pathlib import Path
from ultralytics import YOLO

from vehicle_counting_system.ai_core.services.yolo_char_recognizer import YOLOCharRecognizer
from vehicle_counting_system.configs.paths import DATA_OUTPUT_DIR
from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)


class LPRService:
    def __init__(self, use_gpu: bool = True):
        self.use_gpu = use_gpu
        self.detector = None
        self.char_recognizer = None
        self._init_models()

        # Tạo thư mục lưu ảnh crop nếu chưa có
        self.images_dir = Path(DATA_OUTPUT_DIR) / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def _init_models(self):
        model_dir = Path(__file__).resolve().parents[2] / "data" / "models"
        model_dir.mkdir(parents=True, exist_ok=True)

        # ============================================================
        # 1. Khởi tạo YOLO License Plate Detector (YOLO 2)
        # ============================================================
        local_model_path = model_dir / "license_plate_detector.pt"
        yolo11_model_path = model_dir / "license_plate_detector_yolo11.pt"

        # Ưu tiên load model YOLOv11 tự train nếu có
        if yolo11_model_path.exists():
            try:
                logger.info("Loading local YOLOv11 License Plate Detector from %s...", yolo11_model_path)
                self.detector = YOLO(str(yolo11_model_path))
                logger.info("YOLOv11 License Plate Detector loaded successfully.")
            except Exception as e:
                logger.error("Failed to load YOLOv11 license plate detector from %s: %s", yolo11_model_path, e)
                
        # Nếu chưa load được model YOLOv11, fallback về model mặc định
        if self.detector is None:
            if not local_model_path.exists():
                logger.info("Local license plate detector model not found. Attempting download...")
                import requests
                url = "https://huggingface.co/joker5914/yolov8n-license-plate/resolve/main/best.pt"
                success = False
                try:
                    logger.info("Downloading LPR model from %s...", url)
                    r = requests.get(url, stream=True, timeout=60)
                    r.raise_for_status()
                    with open(local_model_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    logger.info("LPR model downloaded successfully and saved to %s.", local_model_path)
                    success = True
                except Exception as e:
                    logger.warning("Failed to download primary LPR model: %s. Trying fallback model URL...", e)
                    fallback_url = "https://huggingface.co/keremberke/yolov5n-license-plate/resolve/main/best.pt"
                    try:
                        logger.info("Downloading fallback LPR model from %s...", fallback_url)
                        r = requests.get(fallback_url, stream=True, timeout=60)
                        r.raise_for_status()
                        with open(local_model_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        logger.info("Fallback LPR model downloaded successfully and saved to %s.", local_model_path)
                        success = True
                    except Exception as e2:
                        logger.error("Failed to download fallback LPR model: %s", e2)
            
            if local_model_path.exists():
                try:
                    logger.info("Loading local YOLO License Plate Detector from %s...", local_model_path)
                    self.detector = YOLO(str(local_model_path))
                    logger.info("YOLO License Plate Detector loaded successfully.")
                except Exception as e:
                    logger.error("Failed to load YOLO license plate detector from %s: %s", local_model_path, e)

        # ============================================================
        # 2. Khởi tạo YOLO Character Recognizer (YOLO 3) — thay EasyOCR
        # ============================================================
        char_model_path = model_dir / "char_detector_yolo11.pt"
        if char_model_path.exists():
            try:
                self.char_recognizer = YOLOCharRecognizer(
                    model_path=str(char_model_path),
                    conf=0.25,
                    imgsz=320,
                    use_gpu=self.use_gpu,
                )
                logger.info("YOLO Character Recognizer loaded successfully.")
            except Exception as e:
                logger.error("Failed to load YOLO Character Recognizer: %s", e)
        else:
            logger.warning(
                "YOLO Character Recognizer model not found at %s. "
                "LPR character recognition will be disabled. "
                "Train the model using train_char_detector.py first.",
                char_model_path,
            )

    def normalize_plate(self, text: str) -> str:
        """Chuẩn hóa biển số: viết hoa, chỉ giữ lại chữ cái và số, viết liền."""
        if not text:
            return ""
        # Viết hoa toàn bộ
        text = text.upper()
        # Loại bỏ các ký tự đặc biệt, khoảng trắng, dấu chấm, gạch ngang
        text = re.sub(r'[^A-Z0-9]', '', text)
        return text

    def correct_vietnamese_plate_syntax(self, text: str) -> str:
        """Sửa lỗi ký tự dựa trên cú pháp biển số Việt Nam.
        
        Format biển số VN: XX-Y-ZZZZZ
        - XX: 2 số (mã tỉnh, vd: 51, 29, 30)
        - Y: 1-2 chữ cái (series, vd: A, B, D, T, LD, MD)
        - ZZZZZ: 4-5 số (số đuôi)
        """
        if not text:
            return ""
        
        # 1. Chuẩn hóa cơ bản
        text = text.upper().strip()
        text = re.sub(r'[^A-Z0-9]', '', text)
        
        if len(text) < 4:
            return text

        # Bản đồ quy đổi lỗi ký tự (đã sửa, không map các ký tự series hợp lệ)
        to_digit = {
            'O': '0', 'Q': '0',    # O/Q dễ nhầm với 0
            'I': '1', 'L': '1',    # I/L dễ nhầm với 1
            'Z': '2',              # Z dễ nhầm với 2
            'S': '5',              # S dễ nhầm với 5
            'B': '8',              # B dễ nhầm với 8
            'G': '9',              # G dễ nhầm với 9
        }
        to_letter = {
            '0': 'O',              # 0 dễ nhầm với O
            '8': 'B',              # 8 dễ nhầm với B
            '1': 'L',              # 1 dễ nhầm với L
            '5': 'S',              # 5 dễ nhầm với S
        }

        chars = list(text)
        
        # 1. Hai ký tự đầu phải là số (Mã tỉnh)
        for i in range(min(2, len(chars))):
            if chars[i].isalpha():
                chars[i] = to_digit.get(chars[i], chars[i])

        # 2. Ký tự thứ 3 phải là chữ cái (Series biển)
        if len(chars) > 2 and chars[2].isdigit():
            chars[2] = to_letter.get(chars[2], chars[2])

        # 3. Xác định vị trí bắt đầu của dãy số đuôi (index 3 hoặc 4)
        start_digits_idx = 3
        if len(chars) > 3 and chars[3].isalpha():
            start_digits_idx = 4
            
        # Các ký tự từ start_digits_idx trở đi phải là số
        for i in range(start_digits_idx, len(chars)):
            if chars[i].isalpha():
                chars[i] = to_digit.get(chars[i], chars[i])
                
        return "".join(chars)

    def detect_plate_box(self, vehicle_crop: np.ndarray) -> tuple[np.ndarray, float] | None:
        """
        Phát hiện vị trí biển số xe trong ảnh xe crop.
        Trả về: (plate_crop_image, YOLO_confidence) hoặc None.
        """
        if self.detector is None:
            return None
        
        try:
            results = self.detector.predict(vehicle_crop, verbose=False, conf=0.30)
        except Exception as e:
            logger.debug("YOLO Plate Predict error: %s", e)
            return None

        best_plate_box = None
        best_plate_conf = 0.0

        for result in results:
            if not result.boxes:
                continue
            for box in result.boxes:
                conf = float(box.conf[0])
                if conf > best_plate_conf:
                    best_plate_conf = conf
                    best_plate_box = box.xyxy[0].cpu().numpy()

        if best_plate_box is None:
            return None

        px1, py1, px2, py2 = best_plate_box
        
        # Thêm padding 8% để tránh cắt ký tự ở rìa biển số
        pad_x = int((px2 - px1) * 0.08)
        pad_y = int((py2 - py1) * 0.10)
        px1 = max(0, int(px1) - pad_x)
        py1 = max(0, int(py1) - pad_y)
        px2 = min(vehicle_crop.shape[1], int(px2) + pad_x)
        py2 = min(vehicle_crop.shape[0], int(py2) + pad_y)

        if (px2 - px1) < 10 or (py2 - py1) < 5:
            return None

        # Kiểm tra aspect ratio: biển VN 1 dòng ~2.5:1, 2 dòng ~1.2:1
        aspect_ratio = (px2 - px1) / max(1, py2 - py1)
        if aspect_ratio < 0.8 or aspect_ratio > 6.0:
            return None

        plate_crop = vehicle_crop[py1:py2, px1:px2]
        return plate_crop, best_plate_conf

    def run_ocr(self, plate_crop: np.ndarray) -> tuple[str, float] | None:
        """
        Nhận diện ký tự biển số bằng YOLO Character Detection.
        Thay thế hoàn toàn EasyOCR.
        """
        if self.char_recognizer is None or not self.char_recognizer.is_ready:
            return None

        result = self.char_recognizer.recognize(plate_crop)
        if result is None:
            return None

        plate_text, avg_conf = result

        # Post-processing: sửa lỗi cú pháp biển VN
        plate_text = self.correct_vietnamese_plate_syntax(plate_text)

        if len(plate_text) < 4 or len(plate_text) > 11:
            return None

        return plate_text, avg_conf

    def save_cropped_images(self, vehicle_crop: np.ndarray, plate_crop: np.ndarray, track_id: int, session_id: int) -> tuple[str, str]:
        """Lưu ảnh xe crop và ảnh biển số crop ra file, trả về đường dẫn tương đối."""
        vehicle_filename = f"session_{session_id}_track_{track_id}_vehicle.jpg"
        plate_filename = f"session_{session_id}_track_{track_id}_plate.jpg"
        
        vehicle_path = self.images_dir / vehicle_filename
        plate_path = self.images_dir / plate_filename

        try:
            cv2.imwrite(str(vehicle_path), vehicle_crop)
            cv2.imwrite(str(plate_path), plate_crop)
        except Exception as e:
            logger.warning("Failed to save LPR cropped images: %s", e)

        rel_vehicle_path = f"outputs/images/{vehicle_filename}"
        rel_plate_path = f"outputs/images/{plate_filename}"
        return rel_vehicle_path, rel_plate_path

    def detect_and_ocr(
        self, 
        frame: np.ndarray, 
        vehicle_bbox: tuple[float, float, float, float],
        track_id: int,
        session_id: int,
        vehicle_class: str
    ) -> tuple[str, float, str | None, str | None] | None:
        """
        Nhận diện biển số xe từ ảnh frame và bbox của xe.
        (Giữ lại để đảm bảo tính tương thích ngược)
        """
        if self.detector is None or self.char_recognizer is None:
            return None

        h_frame, w_frame = frame.shape[:2]
        vx1, vy1, vx2, vy2 = vehicle_bbox
        vx1 = max(0, int(vx1))
        vy1 = max(0, int(vy1))
        vx2 = min(w_frame, int(vx2))
        vy2 = min(h_frame, int(vy2))

        if (vx2 - vx1) < 20 or (vy2 - vy1) < 20:
            return None

        vehicle_crop = frame[vy1:vy2, vx1:vx2]
        res_det = self.detect_plate_box(vehicle_crop)
        if res_det is None:
            return None
        
        plate_crop, best_plate_conf = res_det
        res_ocr = self.run_ocr(plate_crop)
        if res_ocr is None:
            return None
        
        plate_text, avg_ocr_conf = res_ocr
        final_confidence = (best_plate_conf * 0.4) + (avg_ocr_conf * 0.6)
        rel_vehicle_path, rel_plate_path = self.save_cropped_images(vehicle_crop, plate_crop, track_id, session_id)

        return plate_text, final_confidence, rel_vehicle_path, rel_plate_path
