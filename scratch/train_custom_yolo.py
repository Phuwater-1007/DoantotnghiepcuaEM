import os
import sys
from pathlib import Path
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

def train_custom_model(data_yaml_path: str, epochs: int = 50, batch_size: int = 16, imgsz: int = 960):
    """
    Huấn luyện mô hình YOLO11s trên tập dữ liệu tùy chỉnh.
    Sau khi huấn luyện xong, tự động xuất sang định dạng TensorRT (.engine) để chạy tốc độ tối đa.
    """
    yaml_path = str(Path(data_yaml_path).resolve())
    if not os.path.exists(yaml_path):
        print(f"LỖI: Không tìm thấy file data.yaml tại: {yaml_path}")
        print("Vui lòng kiểm tra lại đường dẫn tập dữ liệu bạn đã tải về.")
        return
        
    print(f"=== BẮT ĐẦU QUÁ TRÌNH HUẤN LUYỆN YOLO ===")
    print(f" - Config YAML: {yaml_path}")
    print(f" - Số lượng Epoch: {epochs}")
    print(f" - Batch Size: {batch_size}")
    print(f" - Kích thước ảnh: {imgsz}")
    print("========================================")
    
    # Sử dụng mô hình pretrained yolo11s.pt làm nền tảng (backbone) để hội tụ nhanh
    base_model_path = str(ROOT / "yolo11s.pt")
    if not os.path.exists(base_model_path):
        print(f"Đang tự động tải mô hình nền tảng yolo11s.pt...")
        
    model = YOLO(base_model_path)
    
    # Bắt đầu huấn luyện
    model.train(
        data=yaml_path,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch_size,
        device=0,                   # Sử dụng GPU CUDA thứ nhất
        project=str(ROOT / "runs" / "detect"),
        name="custom_yolo11s",
        exist_ok=True,
        patience=15,                # Dừng sớm nếu sau 15 epoch không cải thiện độ chính xác
        workers=4,                  # Số luồng CPU load data
        verbose=True,
        plots=True
    )
    
    best_pt_path = ROOT / "runs" / "detect" / "custom_yolo11s" / "weights" / "best.pt"
    print("\n=== Huấn luyện hoàn tất! ===")
    print(f"Mô hình tốt nhất được lưu tại: {best_pt_path}")
    
    # Tự động xuất sang định dạng TensorRT (.engine) để chạy thời gian thực siêu mượt
    print("\n=== Đang xuất mô hình sang TensorRT (.engine) ===")
    export_model = YOLO(str(best_pt_path))
    engine_path = export_model.export(
        format="engine",
        device=0,
        imgsz=imgsz,
        half=True                   # Chạy ở độ chính xác FP16 để tăng gấp đôi tốc độ trên GPU
    )
    
    print("\n=== QUÁ TRÌNH HOÀN TẤT THÀNH CÔNG! ===")
    print(f"File TensorRT mới của bạn: {engine_path}")
    print("Hãy copy file .engine này thay thế vào thư mục data/models/ để sử dụng trong hệ thống.")

if __name__ == "__main__":
    # Điền đường dẫn tới file data.yaml của bạn ở đây
    # Ví dụ: data_yaml = "c:/Users/admin/Desktop/Python/doan/data/custom_dataset/data.yaml"
    data_yaml = str(ROOT / "data" / "custom_dataset" / "data.yaml")
    
    train_custom_model(data_yaml_path=data_yaml, epochs=50, batch_size=16, imgsz=960)
