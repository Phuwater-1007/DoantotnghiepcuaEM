# Chạy Web App - Hệ thống Giám sát Giao thông

## Cách chạy nhanh

### Windows
```bash
# Cách 1: Double-click file
run_web.bat

# Cách 2: Từ terminal
cd c:\Users\admin\Desktop\Python\doan
uvicorn product_web:app --reload --host 127.0.0.1 --port 8000
```

### Hoặc dùng Python trực tiếp
```bash
cd c:\Users\admin\Desktop\Python\doan
python -m uvicorn product_web:app --reload --host 127.0.0.1 --port 8000
```

## Truy cập web

- **URL:** http://127.0.0.1:8000
- **Đăng nhập:** `admin` / `admin123`

## Quy trình để có dữ liệu và video

1. **Đăng nhập** (admin / admin123)
2. **Nguồn video** → Thêm source:
   - Đặt file video vào `vehicle_counting_system/data/input/videos/` (tự tạo khi chạy web)
   - Đường dẫn: `data/input/videos/ten_file.mp4`
3. **Giám sát** → Chọn video → **Chỉnh ROI** → Lưu
4. **Chạy trong VS Code**: `python run_with_web_roi.py --source "data/input/videos/ten_file.mp4"`
5. **Giám sát** → Bấm **Chạy phân tích** → Xem video đã xử lý và số đếm

## Chạy local dùng ROI từ web (mượt hơn, ít lag)

Sau khi chỉnh ROI trên web, có thể xử lý video **trong VS Code** để mượt và ổn định hơn:

```bash
# Từ thư mục gốc dự án (doan)
python run_with_web_roi.py
python run_with_web_roi.py --source data/input/videos/test.mp4
```

Trên trang Giám sát, khi video đã có ROI, sẽ hiện lệnh và nút **Copy** để chạy local.

## Lưu ý

- Video output: `vehicle_counting_system/data/outputs/videos/{tên}_result.mp4` (vd: Test3_result.mp4)
- Web **không** chạy phân tích – chỉ hiển thị video đã xử lý từ VS Code
- Kết quả giữ nguyên đến khi đổi video hoặc refresh trang
