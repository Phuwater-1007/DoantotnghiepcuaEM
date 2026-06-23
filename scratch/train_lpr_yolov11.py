import os
import sys
import torch
from ultralytics import YOLO

def main():
    print("=" * 60)
    print("YOLOv11s License Plate Detection Training Setup")
    print("=" * 60)

    # 1. Kiểm tra môi trường GPU CUDA
    cuda_available = torch.cuda.is_available()
    device = "0" if cuda_available else "cpu"
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {cuda_available}")
    if cuda_available:
        print(f"GPU Device Name: {torch.cuda.get_device_name(0)}")
        print("Huấn luyện sẽ chạy bằng GPU (Tốc độ cao) 🚀")
    else:
        print("KHÔNG tìm thấy GPU. Huấn luyện sẽ chạy bằng CPU (Tốc độ chậm) ⚠️")
    
    # 2. Khởi tạo model base YOLOv11 Small
    # Chúng ta sử dụng file yolo11s.pt đã tải sẵn ở root của dự án
    base_model_path = "yolo11s.pt"
    if not os.path.exists(base_model_path):
        print(f"Không tìm thấy {base_model_path} ở thư mục gốc. Ultralytics sẽ tự động tải về.")
    else:
        print(f"Đã tìm thấy model base: {base_model_path}")
        
    model = YOLO(base_model_path)
    
    # 3. Cấu hình đường dẫn dataset
    yaml_path = r"C:\Users\admin\Desktop\Python\doan\data\lpr_dataset\data.yaml"
    if not os.path.exists(yaml_path):
        print(f"Lỗi: Không tìm thấy file data.yaml tại {yaml_path}")
        sys.exit(1)
        
    print(f"Dataset configuration: {yaml_path}")
    
    # 4. Xác định chế độ chạy (Dry run / Train thật)
    # Nếu truyền đối số '--dry-run', chúng ta chỉ chạy 1 epoch để test phần cứng
    epochs = 50
    if len(sys.argv) > 1 and sys.argv[1] == "--dry-run":
        epochs = 1
        print("Đang chạy chế độ Dry Run (1 epoch) để kiểm thử hệ thống...")
        
    print(f"Bắt đầu huấn luyện với {epochs} epochs trên thiết bị '{device}'...")
    
    # 5. Chạy huấn luyện
    try:
        model.train(
            data=yaml_path,
            epochs=epochs,
            imgsz=640,
            batch=16 if cuda_available else 4, # Giảm batch size nếu dùng CPU để tránh tràn RAM
            device=device,
            workers=4 if cuda_available else 2,
            project="runs/detect",
            name="lpr_yolo11s",
            exist_ok=True
        )
        print("=" * 60)
        print("Quá trình huấn luyện đã kết thúc thành công!")
        print("Model tốt nhất được lưu tại: runs/detect/lpr_yolo11s/weights/best.pt")
        print("=" * 60)
    except Exception as e:
        print("=" * 60)
        print(f"Lỗi trong quá trình huấn luyện: {e}")
        print("=" * 60)
        sys.exit(1)

if __name__ == "__main__":
    main()
