Đặt file TensorRT vào thư mục này (app chỉ chạy .engine, không dùng .pt để inference).

Bắt buộc:
  - yolo11s.engine

Export (file .pt chỉ dùng một lần để tạo engine):
  yolo export model=yolo11s.pt format=engine imgsz=960 half=True
  (imgsz phải khớp IMAGE_SIZE trong .env)

Cấu hình .env: YOLO_WEIGHTS=data/models/yolo11s.engine
Hoặc: YOLO_WEIGHTS=yolo11s.engine (app tìm trong thư mục này và các thư mục gốc project).
