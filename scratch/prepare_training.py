import cv2
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

def extract_frames_for_dataset(video_path: str, output_dir: str, sample_interval_seconds: float = 1.0):
    """
    Tự động trích xuất các khung hình từ video của bạn để làm tập dữ liệu huấn luyện (dataset).
    Mỗi sample_interval_seconds giây sẽ trích xuất 1 ảnh để tránh các ảnh bị trùng lặp quá giống nhau.
    """
    video_path = str(Path(video_path).resolve())
    output_path = Path(output_dir) / "images"
    output_path.mkdir(parents=True, exist_ok=True)
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"LỖI: Không thể mở video: {video_path}")
        return
        
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_interval = int(round(fps * sample_interval_seconds))
    
    print(f"Bắt đầu trích xuất ảnh từ: {video_path}")
    print(f"Khoảng cách trích xuất: {sample_interval_seconds} giây (mỗi {frame_interval} khung hình)")
    print(f"Thư mục lưu ảnh: {output_path}")
    
    frame_idx = 0
    saved_count = 0
    
    while True:
        ok, frame = cap.read()
        if not ok:
            break
            
        if frame_idx % frame_interval == 0:
            img_name = f"frame_{saved_count:04d}.jpg"
            img_path = output_path / img_name
            cv2.imwrite(str(img_path), frame)
            saved_count += 1
            
        frame_idx += 1
        
    cap.release()
    print(f"Hoàn thành! Đã trích xuất {saved_count} ảnh chất lượng cao để gán nhãn.")
    print("\n--- HƯỚNG DẪN TIẾP THEO ---")
    print("1. Hãy tải các ảnh trong thư mục này lên công cụ gán nhãn như Roboflow (roboflow.com) hoặc LabelImg.")
    print("2. Gán nhãn các lớp xe (motorcycle, car, truck, bus) bằng bounding box.")
    print("3. Export tập dữ liệu dưới định dạng 'YOLOv8' (gồm các file .txt chứa tọa độ gán nhãn).")
    print("4. Chạy script train YOLO bằng GPU của bạn để tối ưu hóa.")

if __name__ == "__main__":
    # Mặc định trích xuất từ video Test.mp4 của bạn
    default_video = str(ROOT / "vehicle_counting_system" / "data" / "inputs" / "videos" / "Test.mp4")
    default_output = str(ROOT / "data" / "custom_dataset")
    
    extract_frames_for_dataset(default_video, default_output, sample_interval_seconds=1.0)
