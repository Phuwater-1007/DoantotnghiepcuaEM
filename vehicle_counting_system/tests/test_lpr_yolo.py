import unittest
import cv2
import time
from pathlib import Path
from vehicle_counting_system.ai_core.services.yolo_char_recognizer import YOLOCharRecognizer

class TestLPRYOLO(unittest.TestCase):
    def setUp(self):
        self.project_root = Path(__file__).resolve().parents[2]
        self.model_path = self.project_root / "vehicle_counting_system" / "data" / "models" / "char_detector_yolo11.pt"
        self.valid_images_dir = self.project_root / "data" / "char_dataset_merged" / "valid" / "images"
        
    def test_load_model(self):
        self.assertTrue(self.model_path.exists(), f"Model file not found at {self.model_path}")
        recognizer = YOLOCharRecognizer(model_path=str(self.model_path))
        self.assertTrue(recognizer.is_ready, "YOLOCharRecognizer failed to load the model")

    def test_inference_on_sample(self):
        recognizer = YOLOCharRecognizer(model_path=str(self.model_path))
        self.assertTrue(recognizer.is_ready)
        
        # Lấy 3 ảnh mẫu để test
        self.assertTrue(self.valid_images_dir.exists(), f"Valid images dir not found at {self.valid_images_dir}")
        img_paths = list(self.valid_images_dir.glob("*.jpg"))
        self.assertGreater(len(img_paths), 0, "No sample images found for testing")
        
        for path in img_paths[:5]:
            img = cv2.imread(str(path))
            self.assertIsNotNone(img, f"Failed to read image: {path}")
            
            t0 = time.perf_counter()
            result = recognizer.recognize(img)
            t1 = time.perf_counter()
            
            duration_ms = (t1 - t0) * 1000
            print(f"\nImage: {path.name}")
            print(f"Prediction duration: {duration_ms:.2f}ms")
            
            if result:
                text, conf = result
                print(f"Recognized text: '{text}' with confidence: {conf:.2f}")
                self.assertGreater(len(text), 1)
                self.assertGreaterEqual(conf, 0.0)
                self.assertLessEqual(conf, 1.0)
            else:
                print("No characters detected")

if __name__ == "__main__":
    unittest.main()
