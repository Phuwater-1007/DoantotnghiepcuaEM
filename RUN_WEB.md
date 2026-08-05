# Chạy ứng dụng web

Tài liệu chuẩn nằm tại [README.md](README.md), gồm yêu cầu GPU/TensorRT, cài đặt, cấu hình tài khoản và hướng dẫn từng chức năng.

Sau khi hoàn tất các bước cài đặt trong README, chạy từ thư mục gốc:

```powershell
.\.venv\Scripts\python.exe web_main.py
```

Hoặc chạy ASGI trực tiếp:

```powershell
.\.venv\Scripts\python.exe -m uvicorn product_web:app --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000/login`. Username quản trị là `admin`; mật khẩu là giá trị `DEFAULT_ADMIN_PASSWORD` đã dùng khi tạo CSDL lần đầu, không phải một mật khẩu cố định trong mã nguồn.
