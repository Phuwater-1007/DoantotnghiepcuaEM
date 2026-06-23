"""Train YOLO11s để detect ký tự biển số (0-9, A-Z).

Sử dụng dataset gộp từ 2 nguồn Roboflow:
- License Plate Characters 210 (36 class)
- License-Plate-Characters v1 (35 class, remapped to 36)

Output: runs/detect/char_yolo11s/weights/best.pt
Copy best.pt -> data/models/char_detector_yolo11.pt để sử dụng trong LPR pipeline.
"""

from ultralytics import YOLO
from pathlib import Path

# Paths
DATA_YAML = str(Path(r"c:\Users\admin\Desktop\Python\doan\data\char_dataset_merged\data.yaml"))
BASE_MODEL = "yolo11s.pt"  # Pretrained backbone

def train():
    model = YOLO(BASE_MODEL)
    
    results = model.train(
        data=DATA_YAML,
        epochs=80,
        imgsz=320,              # Ảnh biển số crop nhỏ → imgsz 320 đủ
        batch=32,               # RTX 3050 xử lý tốt batch 32 ở imgsz 320
        device="0",             # GPU
        project="runs/detect",
        name="char_yolo11s",
        exist_ok=True,
        patience=20,            # Early stopping nếu 20 epoch không cải thiện
        
        # Augmentation phù hợp cho ký tự biển số
        flipud=0.0,             # KHÔNG lật dọc (ký tự bị ngược)
        fliplr=0.0,             # KHÔNG lật ngang (ký tự bị gương)
        degrees=5.0,            # Xoay nhẹ (biển số có thể hơi nghiêng)
        translate=0.1,          # Dịch chuyển nhẹ
        scale=0.3,              # Co giãn
        mosaic=0.5,             # Giảm mosaic (biển số nhỏ)
        hsv_h=0.01,             # Thay đổi màu nhẹ
        hsv_s=0.5,
        hsv_v=0.3,
        erasing=0.2,            # Random erasing nhẹ
        
        # Optimizer
        optimizer="auto",
        lr0=0.01,
        lrf=0.01,
        
        # Logging
        verbose=True,
        plots=True,
    )
    
    print("\n=== Training complete! ===")
    print(f"Best model saved at: runs/detect/char_yolo11s/weights/best.pt")
    print(f"\nCopy to production:")
    print(f"  copy runs\\detect\\char_yolo11s\\weights\\best.pt data\\models\\char_detector_yolo11.pt")
    
    return results

if __name__ == "__main__":
    train()
