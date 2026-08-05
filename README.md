# Hệ thống giám sát và đếm phương tiện giao thông

Ứng dụng đồ án tốt nghiệp dùng YOLO11, TensorRT, ByteTrack và OpenCV để phát hiện, theo dõi, phân loại và đếm phương tiện từ video hoặc camera mạng. Kết quả được hiển thị trên giao diện FastAPI, lưu vào SQLite và có thể xuất thành CSV.

Luồng xử lý chính:

```text
Video / RTSP / HTTP
        ↓
OpenCV đọc khung hình
        ↓
YOLO11 TensorRT phát hiện phương tiện
        ↓
ByteTrack theo dõi và ổn định lớp
        ↓
ROI + vạch đếm hai chiều
        ↓
Web realtime + SQLite + báo cáo CSV
```

## 1. Chức năng

- Tải lên video `mp4`, `avi`, `mov`, `mkv` hoặc kết nối camera RTSP/HTTP/HTTPS/RTMP.
- Phát hiện bốn nhóm phương tiện: `motorcycle`, `car`, `truck`, `bus`.
- Theo dõi phương tiện bằng ByteTrack, hiển thị bounding box và ID.
- Vẽ riêng cho từng nguồn: vùng ROI, vạch đếm và vùng nhận dạng biển số.
- Đếm phương tiện qua vạch theo hai chiều hoặc thống kê panorama.
- Nhận dạng biển số, lưu ảnh xe và ảnh biển số khi pipeline LPR được bật.
- Giám sát đơn luồng và bố trí đa luồng 1x1, 2x2, 3x3 hoặc 4x4.
- Dashboard, lịch sử phiên, báo cáo chi tiết và xuất CSV có BOM UTF-8.
- Đăng nhập, phân quyền `admin`/`user`, quản lý tài khoản và nhật ký hoạt động.
- Lưu dữ liệu bằng SQLite ở chế độ WAL; phục hồi phiên bị gián đoạn khi khởi động lại.

## 2. Cấu trúc chính

```text
doan/
├── README.md                         # tài liệu cài đặt và sử dụng chính
├── product_web.py                    # ASGI entrypoint cho Uvicorn
├── web_main.py                       # chạy web và tự mở trình duyệt
├── main.py                           # wrapper chạy CLI
├── run_video.py                      # chạy video CLI từ thư mục gốc
├── run_with_web_roi.py               # CLI dùng ROI đã lưu trên web
└── vehicle_counting_system/
    ├── .env                          # cấu hình local, không commit
    ├── requirements.txt
    ├── application/                  # dịch vụ nghiệp vụ
    ├── core/                         # pipeline xử lý frame/video
    ├── detectors/                    # YOLO detector
    ├── trackers/                     # ByteTrack
    ├── counters/                     # bộ đếm qua vạch/panorama
    ├── infrastructure/persistence/   # SQLite
    ├── presentation/web/             # FastAPI, template và static files
    ├── tests/                        # kiểm thử tự động
    └── data/
        ├── inputs/videos/            # video đầu vào
        ├── models/                   # model .engine/.pt
        └── outputs/                  # DB, video, ảnh, CSV và log
```

## 3. Yêu cầu hệ thống

### 3.1. Môi trường đã được xác minh

- Windows 10/11 64-bit.
- Python 3.10.
- GPU NVIDIA hỗ trợ CUDA; môi trường hiện tại dùng RTX 3050 Laptop GPU.
- Driver NVIDIA, CUDA/PyTorch CUDA và TensorRT tương thích với nhau.
- Trình duyệt hiện đại như Chrome, Edge hoặc Firefox.

Ứng dụng chính hiện chỉ chấp nhận model phương tiện dạng TensorRT `.engine`. Không đổi `YOLO_WEIGHTS` sang `.pt`: code sẽ từ chối cấu hình này. File `.engine` có thể không tương thích giữa các phiên bản GPU, driver, CUDA và TensorRT; khi chuyển máy có thể phải export lại từ checkpoint `.pt`.

Máy chỉ có CPU không chạy được model `.engine` hiện tại. Chế độ CPU cần thay đổi thiết kế/model và nằm ngoài cấu hình demo đã xác minh.

### 3.2. Các model cần có

Tối thiểu phải có:

```text
vehicle_counting_system/data/models/yolo11s.engine
```

Nếu bật nhận dạng biển số, cần thêm:

```text
vehicle_counting_system/data/models/license_plate_detector_yolo11.pt
vehicle_counting_system/data/models/char_detector_yolo11.pt
```

## 4. Cài đặt trên Windows

Mở PowerShell tại thư mục gốc `doan` rồi thực hiện lần lượt.

### Bước 1: Tạo môi trường Python

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Nếu PowerShell chặn script kích hoạt, có thể gọi trực tiếp `.\.venv\Scripts\python.exe` trong các lệnh tiếp theo mà không cần kích hoạt.

### Bước 2: Cài thư viện

```powershell
python -m pip install -r vehicle_counting_system\requirements.txt
```

`requirements.txt` không thể tự chọn chính xác bản CUDA/TensorRT cho mọi máy. Hãy cài bản PyTorch CUDA và TensorRT phù hợp với driver/GPU của máy, sau đó kiểm tra:

```powershell
python -c "import torch; print('torch=', torch.__version__); print('cuda=', torch.cuda.is_available()); print('gpu=', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
python -c "import tensorrt as trt; print('tensorrt=', trt.__version__)"
```

Điều kiện đạt cho bản demo GPU:

- `cuda=True`.
- Import `tensorrt` không lỗi.
- File `yolo11s.engine` tồn tại đúng vị trí.

### Bước 3: Tạo cấu hình môi trường

File được chương trình đọc là:

```text
vehicle_counting_system/.env
```

Với bản cài mới, sao chép file mẫu:

```powershell
Copy-Item vehicle_counting_system\.env.example vehicle_counting_system\.env
```

Không chạy lệnh trên nếu `.env` đang chứa cấu hình đã tinh chỉnh mà chưa sao lưu. Mở `.env` và bắt buộc thay:

```dotenv
DEFAULT_ADMIN_PASSWORD=MatKhauManhCuaBan
TRAFFIC_MONITORING_SESSION_SECRET=chuoi-bi-mat-ngau-nhien
```

Có thể sinh session secret bằng:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Lưu ý về tài khoản:

- `DEFAULT_ADMIN_PASSWORD` chỉ tạo tài khoản `admin` nếu tài khoản này chưa tồn tại trong CSDL.
- Biến này không đổi mật khẩu của tài khoản `admin` đã có.
- Không ghi mật khẩu thật hoặc URL RTSP chứa mật khẩu vào Git.
- `DEMO_MODE=1` sẽ tạo thêm `demo/demo123`; chỉ dùng cho demo local, không dùng khi triển khai thật.

### Bước 4: Kiểm tra model và import

```powershell
Test-Path vehicle_counting_system\data\models\yolo11s.engine
python -c "from vehicle_counting_system.product_web import app; print(app.title)"
```

Lệnh thứ nhất phải trả về `True`; lệnh thứ hai phải in `Traffic Monitoring System`.

## 5. Chạy ứng dụng web

### Cách khuyến nghị khi demo

Từ thư mục gốc:

```powershell
python web_main.py
```

Chương trình dùng `WEB_HOST` và `WEB_PORT` trong `.env`, mặc định là `127.0.0.1:8000`, đồng thời mở trang `/monitoring` trên trình duyệt.

Truy cập thủ công:

```text
http://127.0.0.1:8000/login
```

Dừng server bằng `Ctrl+C`. Nếu bật `WEB_AUTO_SHUTDOWN=1`, server có thể tự dừng sau khi không còn tab gửi heartbeat.

### Chạy bằng Uvicorn

```powershell
python -m uvicorn product_web:app --host 127.0.0.1 --port 8000
```

Chỉ dùng `--reload` trong lúc phát triển. Khi demo TensorRT/GPU, không nên bật reload để tránh nạp lại model ngoài ý muốn.

## 6. Hướng dẫn sử dụng chi tiết

### 6.1. Đăng nhập và phân quyền

1. Mở `/login`.
2. Đăng nhập bằng tài khoản `admin` và mật khẩu đã đặt trong `DEFAULT_ADMIN_PASSWORD` ở lần tạo CSDL đầu tiên.
3. Tài khoản `admin` có menu quản lý người dùng, thương hiệu và dữ liệu hệ thống.
4. Tài khoản `user` được xem dashboard, giám sát và báo cáo nhưng không có chức năng quản trị.

Mỗi lần server khởi động lại, phiên trình duyệt cũ bị vô hiệu và người dùng phải đăng nhập lại. Đây là hành vi chủ động của ứng dụng.

### 6.2. Thêm video đầu vào

Cách thuận tiện nhất:

1. Vào **Giám sát đơn luồng**.
2. Tại **Nguồn dữ liệu**, bấm hoặc kéo thả video vào ô **Tải video lên**.
3. Chọn file có đuôi `mp4`, `avi`, `mov` hoặc `mkv`.
4. Chờ thanh upload hoàn tất; nguồn mới xuất hiện trong danh sách camera.

Nếu trùng tên, server tự đổi `video.mp4` thành `video_1.mp4`, `video_2.mp4`, ...

Cũng có thể chép video trực tiếp vào:

```text
vehicle_counting_system/data/inputs/videos/
```

Sau đó tải lại trang. Code vẫn nhận cấu trúc cũ `data/input`, nhưng tài liệu và cấu trúc chuẩn hiện tại dùng `data/inputs`.

### 6.3. Thêm camera IP

1. Vào **Giám sát đơn luồng**.
2. Nhập tên camera tại **Kết nối Camera IP**.
3. Nhập URL bắt đầu bằng `rtsp://`, `http://`, `https://` hoặc `rtmp://`.
4. Bấm **Kết nối**.

Ví dụ dạng URL, không dùng nguyên thông tin mẫu này:

```text
rtsp://user:password@192.168.1.100:554/stream1
```

Máy chạy server phải truy cập được camera. Mặc định RTSP dùng TCP (`STREAM_RTSP_TRANSPORT=tcp`).

### 6.4. Vẽ ROI, vạch đếm và vùng LPR

Mỗi nguồn cần cấu hình riêng trước khi nút xem trực tiếp được bật.

1. Chọn tile video/camera trong **Luồng Camera**.
2. Bấm **Chỉnh ROI**.
3. Bấm **Vẽ ROI (Xanh lá)** rồi click ít nhất 3 điểm bao quanh vùng cần phân tích.
4. Bấm **Vẽ đường đếm (Vàng)** rồi chọn điểm đầu và điểm cuối của vạch. Không đặt hai điểm trùng nhau.
5. Nếu dùng nhận dạng biển số, bấm **Vẽ vùng biển số (Tím hồng)** và chọn ít nhất 3 điểm. Nên đặt vùng này trước vạch đếm theo hướng xe chạy để LPR có thời gian xử lý.
6. Bấm **Lưu cấu hình**.
7. Quay lại **Giám sát** và kiểm tra nhãn **ROI sẵn sàng**.

Tọa độ được lưu chuẩn hóa theo kích thước frame, vì vậy cấu hình tự co giãn theo độ phân giải hiển thị. Nút **Xóa hết** chỉ xóa nội dung đang vẽ; phải bấm **Lưu cấu hình** để ghi trạng thái mới.

### 6.5. Chạy giám sát đơn luồng

1. Chọn nguồn đã có nhãn **ROI sẵn sàng**.
2. Bấm **▶ Xem trực tiếp**.
3. Chờ model khởi tạo; lần đầu có thể chậm hơn do TensorRT warm-up.
4. Quan sát bounding box, tổng số xe, số lượng theo lớp/hướng và bảng biển số.
5. Bấm **■ Dừng trực tiếp** trước khi đổi cấu hình hoặc đóng ứng dụng.

Tại một thời điểm, luồng headless theo phiên chỉ cho phép một phiên hoạt động. API stream realtime có giới hạn đồng thời qua `MAX_CONCURRENT_STREAMS`, mặc định 3.

### 6.6. Chạy giám sát đa luồng

1. Vào **Giám sát đa luồng**.
2. Chọn bố cục 1x1, 2x2, 3x3 hoặc 4x4.
3. Bấm vào từng ô trống và gán một nguồn đã có ROI.
4. Bấm **Chạy tất cả đã gán** hoặc kích hoạt từng ô.
5. Bấm **Dừng tất cả** trước khi thoát.

Số ô hiển thị không đồng nghĩa với số model có thể chạy ổn định. Backend mặc định giới hạn 3 stream; khả năng thực tế phụ thuộc VRAM, độ phân giải, LPR và FPS. Hãy kiểm thử tải trên máy đích trước khi demo đa luồng.

### 6.7. Xem dashboard và xuất báo cáo

- **Tổng quan**: xem tổng số phiên, phương tiện và biểu đồ tổng hợp.
- **Báo cáo kỹ thuật**: xem lịch sử phiên, trạng thái, cơ cấu phương tiện, chi tiết biển số và video output.
- Click một hàng báo cáo để mở chi tiết phiên.
- Chọn một hoặc nhiều checkbox rồi bấm **Xuất CSV**. File tải xuống có tên `ChiTiet_PhuongTien.csv` và được mã hóa UTF-8 BOM để mở bằng Excel.

Báo cáo chỉ xuất hiện sau khi phiên đã tạo dữ liệu và được hoàn tất/dừng đúng cách.

### 6.8. Quản lý người dùng

Chỉ `admin` truy cập được **Người dùng**:

- Tạo tài khoản với vai trò `admin` hoặc `user`.
- Mật khẩu mới phải có ít nhất 8 ký tự.
- Kích hoạt/vô hiệu hóa, đặt lại mật khẩu hoặc xóa tài khoản phụ.
- Tài khoản chính có username `admin` không thể bị xóa hoặc vô hiệu hóa từ giao diện.

### 6.9. Quản trị dữ liệu

Trang **Quản trị hệ thống** hiển thị dung lượng CSDL, input/output và nhật ký. Các nút xóa phiên, output hoặc log là thao tác mất dữ liệu; kiểm tra kỹ hộp xác nhận và sao lưu trước khi dùng.

Vị trí dữ liệu:

```text
vehicle_counting_system/data/outputs/app/traffic_monitoring.db
vehicle_counting_system/data/outputs/videos/
vehicle_counting_system/data/outputs/csv/
vehicle_counting_system/data/outputs/images/
vehicle_counting_system/data/outputs/logs/vehicle_counting.log
```

## 7. Chạy CLI

### Phân tích một video

```powershell
python run_video.py --source "data/inputs/videos/Test.mp4" --output-video "data/outputs/videos/Test_result.mp4"
```

Các tùy chọn:

```text
--source          đường dẫn video hoặc chỉ số webcam, ví dụ 0
--output-video    đường dẫn video kết quả .mp4
--counting-lines  file JSON cấu hình ROI/vạch đếm
--no-export-csv   không xuất CSV cuối phiên
```

Nhấn `q` tại cửa sổ OpenCV hoặc `Ctrl+C` ở terminal để dừng.

### Dùng ROI đã lưu từ web

Sau khi upload nguồn và lưu ROI trên web:

```powershell
python run_with_web_roi.py --source "data/inputs/videos/Test.mp4"
```

Script tìm nguồn trong SQLite và dùng đúng file cấu hình của nguồn đó. Nếu báo không tìm thấy source/ROI, hãy mở web, chọn video, lưu ROI rồi chạy lại.

## 8. Kiểm thử và benchmark

Nếu môi trường mới chưa có Pytest:

```powershell
python -m pip install pytest
```

Chạy toàn bộ test:

```powershell
.\.venv\Scripts\python.exe -m pytest vehicle_counting_system\tests -q
```

Lần xác minh gần nhất ngày 05/08/2026: `40 passed`; có cảnh báo deprecation FastAPI nhưng không có test thất bại.

Benchmark detector + tracker + counting, tắt LPR:

```powershell
.\.venv\Scripts\python.exe -m vehicle_counting_system.tools.benchmark --video "vehicle_counting_system\data\inputs\videos\Test.mp4" --frames 100
```

Kết quả tham chiếu trên môi trường hiện tại sau warm-up: `37.54 FPS` cho 100 frame. Đây là benchmark lõi một video, không đại diện cho web + LPR + đa luồng.

## 9. Cấu hình quan trọng

Các biến thường cần chỉnh trong `vehicle_counting_system/.env`:

| Biến | Ý nghĩa | Giá trị khởi đầu đề xuất |
|---|---|---|
| `YOLO_WEIGHTS` | Model xe TensorRT | `data/models/yolo11s.engine` |
| `DEVICE` | GPU dùng inference | `cuda:0` |
| `IMAGE_SIZE` | Kích thước inference; phải phù hợp engine | `960` |
| `CONF_THRESHOLD` | Ngưỡng confidence | `0.25` |
| `ALLOWED_CLASSES` | Lớp phương tiện giữ lại | `motorcycle,car,truck,bus` |
| `STREAM_MAX_FPS` | Giới hạn FPS xử lý web | `12` |
| `MAX_CONCURRENT_STREAMS` | Số stream backend tối đa | `3` |
| `ENABLE_COUNTING_PIPELINE` | Bật đếm xe | `true` |
| `ENABLE_LPR_PIPELINE` | Bật nhận dạng biển số | `true` |
| `TRAFFIC_MONITORING_SESSION_SECRET` | Khóa ký session | chuỗi ngẫu nhiên riêng |
| `DEFAULT_ADMIN_PASSWORD` | Seed admin khi chưa tồn tại | mật khẩu mạnh riêng |

Sau khi đổi `.env`, dừng và chạy lại server. Giảm `IMAGE_SIZE` có thể tăng tốc nhưng engine TensorRT static có thể yêu cầu đúng kích thước lúc export; không tùy ý đổi trước khi kiểm tra model.

## 10. Xử lý sự cố

### Không đăng nhập được bằng mật khẩu trong `.env`

`DEFAULT_ADMIN_PASSWORD` không reset tài khoản đã tồn tại. Kiểm tra bạn đang dùng đúng CSDL `vehicle_counting_system/data/outputs/app/traffic_monitoring.db`. Nếu còn đăng nhập được bằng một admin khác, vào **Người dùng** để quản lý tài khoản phụ. Với tài khoản admin chính bị mất mật khẩu, hãy sao lưu CSDL trước khi thực hiện quy trình phục hồi riêng.

### `cuda=False`, lỗi CUDA hoặc không thấy GPU

- Kiểm tra `nvidia-smi`.
- Kiểm tra bản PyTorch có CUDA, không phải bản CPU.
- Kiểm tra driver/CUDA/PyTorch tương thích.
- Giữ `DEVICE=cuda:0` sau khi CUDA hoạt động.

### Không nạp được `yolo11s.engine`

- Kiểm tra `YOLO_WEIGHTS=data/models/yolo11s.engine`.
- Không trỏ ứng dụng sang `.pt` vì settings chủ động từ chối.
- Nếu engine được tạo trên môi trường khác, export lại từ `yolo11s.pt` bằng đúng GPU/TensorRT của máy đích.
- Xem traceback trong `vehicle_counting_system/data/outputs/logs/vehicle_counting.log`.

### Nút **Xem trực tiếp** bị khóa

Nguồn chưa có cấu hình. Chọn nguồn → **Chỉnh ROI** → vẽ ROI tối thiểu 3 điểm → vẽ vạch hai điểm → **Lưu cấu hình** → tải lại trang.

### Không mở được video hoặc camera

- Video: kiểm tra đuôi file và thử mở bằng OpenCV/trình phát khác.
- RTSP: kiểm tra URL, user/password, firewall và khả năng truy cập từ máy server.
- Nếu camera không ổn định với UDP, giữ `STREAM_RTSP_TRANSPORT=tcp`.
- Không để `..` hoặc đường dẫn ngoài thư mục input trong API preview.

### Web không mở ở cổng 8000

Kiểm tra cổng đang được dùng:

```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
```

Đổi `WEB_PORT` trong `.env`, hoặc chạy:

```powershell
python -m uvicorn product_web:app --host 127.0.0.1 --port 8001
```

### Không có báo cáo/CSV

- Đảm bảo phiên đã thực sự bắt đầu và có sự kiện đếm.
- Dừng phiên đúng bằng nút trên giao diện.
- Kiểm tra mục **Báo cáo kỹ thuật** và thư mục `data/outputs/csv`.
- Xem log nếu phiên có trạng thái `failed`.

### Stream lag hoặc thiếu VRAM

- Tắt LPR tạm thời bằng `ENABLE_LPR_PIPELINE=false` để kiểm tra pipeline đếm.
- Giảm số stream đồng thời và `STREAM_OUTPUT_WIDTH`.
- Chỉ thay `IMAGE_SIZE` khi engine hỗ trợ kích thước đó.
- Đóng chương trình GPU khác và chạy benchmark một nguồn trước.

## 11. Ghi chú an toàn và phạm vi

- Đây là prototype đồ án chạy local, chưa phải cấu hình production/cloud đã kiểm định.
- Không công khai `.env`, CSDL, URL RTSP, video riêng tư hoặc ảnh biển số.
- Khi đặt `TRAFFIC_MONITORING_ENV=production`, bắt buộc cấu hình session secret và triển khai HTTPS/reverse proxy phù hợp.
- Sao lưu thư mục `vehicle_counting_system/data/outputs` trước khi dùng chức năng xóa trong trang Admin.
- FPS lõi một video không chứng minh khả năng đa camera; phải benchmark lại đúng phần cứng và kịch bản triển khai.

## 12. Tài liệu bổ sung

- [Kiến trúc sản phẩm](vehicle_counting_system/docs/PRODUCT_ARCHITECTURE.md)
- [Luồng xử lý](vehicle_counting_system/docs/flow.md)
- [Báo cáo kiểm kê phục vụ đồ án](PROJECT_AUDIT_FOR_THESIS.md)
- [Báo cáo CSDL và API](PROJECT_DATABASE_API_REPORT.md)
