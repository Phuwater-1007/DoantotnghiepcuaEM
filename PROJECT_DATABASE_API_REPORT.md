# BÁO CÁO PHÂN TÍCH DATABASE VÀ API CỦA PROJECT

> Phạm vi: toàn bộ mã nguồn đang hoạt động trong project tại thời điểm phân tích.  
> Nguyên tắc: chỉ đọc mã nguồn và cơ sở dữ liệu; không sửa mã nguồn, không thay đổi dữ liệu nghiệp vụ.  
> Các thư mục môi trường ảo, bản sao lưu, file `.bak` và mã không được giao diện hiện tại nạp đã được tách khỏi kết luận về hệ thống đang chạy.

## 1. Tóm tắt điều hành

Project là một ứng dụng giám sát và đếm phương tiện viết bằng Python/FastAPI, sử dụng SQLite làm cơ sở dữ liệu cục bộ. Hệ thống có các nhóm chức năng chính: đăng nhập và quản lý người dùng, quản lý video/camera đầu vào, cấu hình ROI và vạch đếm, chạy/dừng phân tích, theo dõi realtime qua MJPEG/WebSocket, lưu lịch sử đếm phương tiện và nhận dạng biển số, xem báo cáo và xuất CSV, cùng một số cấu hình quản trị/giao diện.

Kết quả kiểm kê chính:

- Database nghiệp vụ có **7 bảng**, cộng thêm bảng nội bộ `sqlite_sequence` của SQLite.
- Backend khai báo **64 HTTP route**, gồm **41 endpoint API/media/stream/WebSocket liên quan trực tiếp đến dữ liệu**, **25 route HTML/form** (route `/` và `/dashboard` dùng chung một handler), **3 WebSocket**, và **2 static mount**.
- Database dùng trực tiếp thư viện chuẩn `sqlite3`; không dùng SQLAlchemy, SQLModel hay ORM khác.
- Schema thực tế của bảng `license_plate_events` có thêm 3 cột không xuất hiện trong câu lệnh tạo bảng hiện tại: `raw_text`, `corrected_text`, `processing_time_ms`.
- Các khóa ngoại được khai báo trong DDL nhưng kết nối không bật `PRAGMA foreign_keys = ON`; database hiện có các bản ghi vi phạm quan hệ khóa ngoại.
- Không tìm thấy cơ chế migration hay `ALTER TABLE` trong mã nguồn đang hoạt động.
- Route `DELETE /api/sources/by-path` đang bị route động `DELETE /api/sources/{source_id}` khai báo trước che khuất, nên request đúng đường dẫn `by-path` có thể bị FastAPI trả `422` trước khi vào đúng handler.
- `PRAGMA integrity_check` trả về `ok`, nghĩa là cấu trúc file SQLite không bị hỏng; vấn đề hiện tại nằm ở tính toàn vẹn quan hệ và độ lệch schema/mã nguồn.

## 2. Phạm vi và cấu trúc project đang hoạt động

Các thành phần chính liên quan đến database và API:

```text
doan/
├── web_main.py
└── vehicle_counting_system/
    ├── web_main.py
    ├── application/
    │   ├── bootstrap.py
    │   └── services/
    ├── configs/
    │   └── paths.py
    ├── domain/
    │   └── models/entities.py
    ├── infrastructure/
    │   └── persistence/sqlite_db.py
    ├── presentation/
    │   └── web/
    │       ├── app.py
    │       ├── dependencies.py
    │       ├── routes/
    │       ├── templates/
    │       └── static/js/
    └── data/
        └── outputs/app/traffic_monitoring.db
```

Không đưa vào kiểm kê endpoint/schema đang hoạt động:

- `venv`, `.venv` và thư viện bên thứ ba.
- `_backup_pipeline_split_20260720_1700`, `_backup_20260412` và các bản sao lưu tương tự.
- File `*.bak`, nội dung chỉ nằm trong comment/tài liệu.
- `presentation/web/static/js/monitoring.js`: còn chứa lời gọi API cũ nhưng không có template hiện hành nào nạp file này. Những lời gọi trong file được ghi chú riêng, không coi là luồng frontend đang hoạt động.

## 3. Kiến trúc database

### 3.1. Công nghệ và vị trí

| Thuộc tính | Kết quả |
|---|---|
| Hệ quản trị | SQLite |
| Driver | `sqlite3` trong thư viện chuẩn Python |
| ORM | Không có |
| File database | `vehicle_counting_system/data/outputs/app/traffic_monitoring.db` |
| Kích thước lúc phân tích | 901.120 byte |
| Khởi tạo schema | `CREATE TABLE IF NOT EXISTS` trong `sqlite_db.py` |
| Migration framework | Không tìm thấy |
| Chế độ journal | WAL được thiết lập khi kết nối |
| Row factory | `sqlite3.Row` |
| Timeout kết nối | 10 giây |
| Busy timeout | Có thiết lập |
| Thread check | `check_same_thread=False` |
| Foreign-key enforcement | Không thấy bật `PRAGMA foreign_keys = ON` |

Đường dẫn database được cấu hình qua `APP_DB_PATH` trong `configs/paths.py`. Khi tạo application, `build_container()` gọi lần lượt logic khởi tạo schema, phục hồi session bị treo, sửa dữ liệu múi giờ của báo cáo và seed giá trị mặc định. File database có thể được tự tạo nếu chưa tồn tại.

Tài khoản mặc định chỉ được seed khi có biến môi trường `DEFAULT_ADMIN_PASSWORD` hoặc khi bật `DEMO_MODE`; không thấy mật khẩu mặc định cố định được hard-code trong luồng chính.

### 3.2. Danh sách bảng

| Bảng | Vai trò |
|---|---|
| `users` | Tài khoản, vai trò và trạng thái người dùng |
| `sources` | Video/camera/stream đầu vào và đường dẫn cấu hình đếm |
| `analysis_sessions` | Một lần chạy phân tích trên một nguồn |
| `report_snapshots` | Ảnh chụp tổng hợp báo cáo của một session |
| `vehicle_counts` | Từng sự kiện phương tiện vượt vạch được đếm |
| `license_plate_events` | Sự kiện nhận dạng biển số và ảnh liên quan |
| `activity_logs` | Nhật ký thao tác của người dùng |
| `sqlite_sequence` | Bảng nội bộ quản lý `AUTOINCREMENT` của SQLite |

### 3.3. Schema chi tiết

#### Bảng `users`

| Cột | Kiểu/ràng buộc | Ý nghĩa |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Khóa chính |
| `username` | `TEXT UNIQUE NOT NULL` | Tên đăng nhập |
| `password_hash` | `TEXT NOT NULL` | Mật khẩu đã băm |
| `full_name` | `TEXT NOT NULL` | Họ tên hiển thị |
| `role` | `TEXT NOT NULL` | Vai trò, ví dụ admin/user |
| `is_active` | `INTEGER NOT NULL DEFAULT 1` | Trạng thái hoạt động |
| `created_at` | `TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP` | Thời điểm tạo |

Quan hệ được khai báo:

- `analysis_sessions.started_by -> users.id`
- `activity_logs.user_id -> users.id`

CRUD chính nằm trong `auth_service`, route người dùng và route quản trị.

#### Bảng `sources`

| Cột | Kiểu/ràng buộc | Ý nghĩa |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Khóa chính |
| `name` | `TEXT NOT NULL` | Tên nguồn |
| `source_type` | `TEXT NOT NULL` | Loại nguồn, như video/camera/stream |
| `source_uri` | `TEXT NOT NULL` | Đường dẫn file hoặc URL nguồn |
| `is_active` | `INTEGER NOT NULL DEFAULT 0` | Nguồn đang được chọn/chạy |
| `status` | `TEXT NOT NULL DEFAULT 'ready'` | Trạng thái nguồn |
| `notes` | `TEXT NOT NULL DEFAULT ''` | Ghi chú |
| `counting_config_path` | `TEXT NULL` | Đường dẫn cấu hình ROI/vạch đếm |
| `created_at` | `TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP` | Thời điểm tạo |
| `updated_at` | `TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP` | Thời điểm cập nhật |

Index riêng:

- `idx_sources_uri` là unique index trên `source_uri`.

Được tham chiếu bởi `analysis_sessions`, `vehicle_counts` và `license_plate_events`.

#### Bảng `analysis_sessions`

| Cột | Kiểu/ràng buộc | Ý nghĩa |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Khóa chính session |
| `source_id` | `INTEGER NOT NULL` | Nguồn được phân tích |
| `started_by` | `INTEGER NOT NULL` | Người bắt đầu chạy |
| `status` | `TEXT NOT NULL` | Trạng thái session |
| `started_at` | `TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP` | Thời điểm bắt đầu |
| `finished_at` | `TEXT NULL` | Thời điểm kết thúc |
| `output_video_path` | `TEXT NULL` | Video kết quả |
| `summary_json` | `TEXT NOT NULL DEFAULT '{}'` | Tổng hợp JSON |
| `error_message` | `TEXT NULL` | Thông báo lỗi |

Khóa ngoại khai báo:

- `source_id -> sources.id`
- `started_by -> users.id`

`summary_json` thường chứa `total`, `per_class`; luồng realtime/phục hồi có thể bổ sung dữ liệu liên quan stream. Luồng headless còn có thể ghi `frames_processed`, `elapsed_seconds`, `analysis_mode`, `min_track_frames` và `pipelines`.

#### Bảng `report_snapshots`

| Cột | Kiểu/ràng buộc | Ý nghĩa |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Khóa chính |
| `session_id` | `INTEGER UNIQUE NOT NULL` | Mỗi session tối đa một snapshot |
| `report_date` | `TEXT NOT NULL` | Ngày báo cáo |
| `total` | `INTEGER NOT NULL DEFAULT 0` | Tổng phương tiện |
| `per_class_json` | `TEXT NOT NULL DEFAULT '{}'` | Tổng theo loại xe |
| `peak_hour_label` | `TEXT NOT NULL DEFAULT 'N/A'` | Nhãn giờ cao điểm |
| `created_at` | `TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP` | Thời điểm tạo |

Khóa ngoại: `session_id -> analysis_sessions.id`. `per_class_json` có dạng logic `{class_name: count}`.

#### Bảng `vehicle_counts`

| Cột | Kiểu/ràng buộc | Ý nghĩa |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Khóa chính sự kiện |
| `session_id` | `INTEGER NOT NULL` | Session phân tích |
| `source_id` | `INTEGER NOT NULL` | Nguồn đầu vào |
| `track_id` | `INTEGER NOT NULL` | ID theo dõi vật thể |
| `class_name` | `TEXT NOT NULL` | Loại phương tiện |
| `confidence` | `REAL NOT NULL DEFAULT 0` | Độ tin cậy |
| `direction` | `TEXT NOT NULL DEFAULT 'unknown'` | Hướng di chuyển |
| `line_index` | `INTEGER NOT NULL DEFAULT 0` | Chỉ số vạch đếm |
| `anchor_x` | `REAL NULL` | Tọa độ neo X |
| `anchor_y` | `REAL NULL` | Tọa độ neo Y |
| `counted_at` | `TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP` | Thời điểm đếm |

Khóa ngoại:

- `session_id -> analysis_sessions.id`
- `source_id -> sources.id`

Index:

- `idx_vc_session(session_id)`
- `idx_vc_source(source_id)`
- `idx_vc_counted_at(counted_at)`

Dữ liệu đếm được ghi theo batch bằng `executemany` trong service persistence đếm xe.

#### Bảng `license_plate_events`

Schema thực tế đọc từ file database:

| Cột | Kiểu/ràng buộc | Ý nghĩa |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Khóa chính |
| `session_id` | `INTEGER NOT NULL` | Session phân tích |
| `source_id` | `INTEGER NOT NULL` | Nguồn đầu vào |
| `track_id` | `INTEGER NOT NULL` | ID theo dõi xe |
| `vehicle_class` | `TEXT NOT NULL` | Loại phương tiện |
| `license_plate` | `TEXT NOT NULL` | Biển số kết quả |
| `confidence` | `REAL NOT NULL DEFAULT 0` | Độ tin cậy |
| `vehicle_image_path` | `TEXT NULL` | Ảnh toàn xe |
| `plate_image_path` | `TEXT NULL` | Ảnh vùng biển số |
| `created_at` | `TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP` | Thời điểm tạo |
| `raw_text` | `TEXT NOT NULL DEFAULT ''` | Chuỗi OCR thô; chỉ có trong DB thực tế |
| `corrected_text` | `TEXT NOT NULL DEFAULT ''` | Chuỗi sau hiệu chỉnh; chỉ có trong DB thực tế |
| `processing_time_ms` | `REAL NOT NULL DEFAULT 0` | Thời gian xử lý; chỉ có trong DB thực tế |

Khóa ngoại:

- `session_id -> analysis_sessions.id`
- `source_id -> sources.id`

Index:

- index theo `session_id`
- index theo `track_id`

Mã nguồn tạo bảng hiện tại chỉ khai báo 10 cột đầu, không khai báo ba cột cuối. Không tìm thấy migration tương ứng trong mã đang hoạt động. Logic có tra cứu theo cặp `(session_id, track_id)` nhưng schema không đặt unique constraint cho cặp này.

#### Bảng `activity_logs`

| Cột | Kiểu/ràng buộc | Ý nghĩa |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Khóa chính |
| `user_id` | `INTEGER NULL` | Người thực hiện, có thể rỗng |
| `username` | `TEXT NOT NULL DEFAULT ''` | Tên người dùng snapshot |
| `action` | `TEXT NOT NULL` | Loại hành động |
| `detail` | `TEXT NOT NULL DEFAULT ''` | Nội dung chi tiết |
| `ip_address` | `TEXT NOT NULL DEFAULT ''` | Địa chỉ IP |
| `created_at` | `TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP` | Thời điểm ghi log |

Khóa ngoại: `user_id -> users.id`.

#### Bảng `sqlite_sequence`

Đây là bảng nội bộ của SQLite gồm `name`, `seq`, dùng cho `AUTOINCREMENT`. Mã quản trị có xóa/reset sequence khi xóa dữ liệu của một số bảng.

### 3.4. Sơ đồ quan hệ

```text
users (1) ───────< analysis_sessions >─────── (1) sources
  │                       │                         │
  │                       ├──── (0..1) report_snapshots
  │                       │
  │                       ├────< vehicle_counts >──┘
  │                       │
  │                       └────< license_plate_events >──┘
  │
  └──────────────< activity_logs
```

| Bảng con/cột | Bảng cha/cột | Cardinality logic | Hành vi xóa khai báo |
|---|---|---|---|
| `analysis_sessions.source_id` | `sources.id` | N:1 | `NO ACTION` mặc định |
| `analysis_sessions.started_by` | `users.id` | N:1 | `NO ACTION` |
| `report_snapshots.session_id` | `analysis_sessions.id` | 0..1:1 do `UNIQUE` | `NO ACTION` |
| `vehicle_counts.session_id` | `analysis_sessions.id` | N:1 | `NO ACTION` |
| `vehicle_counts.source_id` | `sources.id` | N:1 | `NO ACTION` |
| `license_plate_events.session_id` | `analysis_sessions.id` | N:1 | `NO ACTION` |
| `license_plate_events.source_id` | `sources.id` | N:1 | `NO ACTION` |
| `activity_logs.user_id` | `users.id` | N:1, tùy chọn | `NO ACTION` |

Không có bảng trung gian many-to-many. `vehicle_counts.track_id` và `license_plate_events.track_id` chỉ tạo liên hệ logic trong cùng session, không có khóa ngoại giữa hai bảng.

## 4. Kiểm kê API đầy đủ

### 4.1. Quy ước chung

- Router API và stream chủ yếu dùng prefix `/api`.
- Không thấy endpoint `PUT` hoặc `PATCH`.
- Các schema Pydantic và tham số typed có thể phát sinh lỗi validation `422` mặc định của FastAPI.
- Không khai báo `response_model`; response là dict/list/FileResponse/StreamingResponse trực tiếp.
- API nghiệp vụ kiểm tra session cookie. Khi chưa đăng nhập, API thường trả `401`; route HTML thường redirect.
- CSRF middleware bỏ qua nhóm `/api`, trong khi các form HTML dùng CSRF token.
- Xác thực thực tế là session cookie, không phải bearer/API token dù có comment mô tả chưa khớp.

### 4.2. Endpoint API, media và stream

| # | Method và path | Input | Output chính | Lỗi/ghi chú |
|---:|---|---|---|---|
| 1 | `POST /api/client/heartbeat` | Session cookie | `ok`, `enabled`, `active_tabs`, `last_seen_ts` | `401` nếu chưa đăng nhập |
| 2 | `POST /api/client/disconnect` | Session cookie | `ok`, trạng thái client/tab | `401` |
| 3 | `GET /api/dashboard` | Session cookie | Dữ liệu tổng hợp dashboard | `401` |
| 4 | `GET /api/sessions` | Query `limit` mặc định 50, tối đa 200 | Danh sách session: id, source, status, thời gian, summary, output | `401` |
| 5 | `GET /api/sessions/{session_id}` | Path session ID | Chi tiết session | `401`, `404` |
| 6 | `GET /api/sessions/{session_id}/lpr-events` | Query `limit` mặc định 100 | Danh sách biển số, ảnh và thời gian | `401`, `404` tùy dữ liệu |
| 7 | `GET /api/reports` | Session cookie | Danh sách report với session/source/summary/LPR | `401` |
| 8 | `GET /api/vehicle-counts` | `limit=50`, `offset=0`, `class_name=''` | `counts`, `summary`, `total_count`, phân trang | `401` |
| 9 | `GET /api/vehicle-counts/summary` | Session cookie | `total`, `per_class` | `401` |
| 10 | `GET /api/sessions/{session_id}/vehicle-counts` | `limit=500`, tối đa 1000 | `session_id`, `counts`, `total` | `401` |
| 11 | `POST /api/sources/upload` | Multipart `file` | `ok`, `path`, `source_id`, thông tin đổi tên | `400`, `500`; kiểm tra phần mở rộng |
| 12 | `POST /api/monitoring/add-stream` | JSON `name`, `url` | `ok`, `source_id`, `message` | `400`, `500` |
| 13 | `DELETE /api/sources/{source_id}` | Path integer | `ok`, tên/loại/id nguồn đã xóa | `404`, `500` |
| 14 | `DELETE /api/sources/by-path` | JSON `path` | Dự kiến `ok` và thông tin xóa | Hiện có thể bị route #13 bắt trước và trả `422` |
| 15 | `GET /api/video/input` | Query `path` bắt buộc theo logic | File video, media type cố định `video/mp4` | `400`, `403`, `404` |
| 16 | `GET /api/sources` | Session cookie | Danh sách nguồn | `401` |
| 17 | `GET /api/sources/{source_id}/preview-frame` | Path source ID | Ảnh base64, `width`, `height` | `400`, `404`, `500` tùy nguồn |
| 18 | `GET /api/sources/{source_id}/config` | Path source ID | `has_config`, `coordinates_mode`, `roi`, `line`, `lpr_zone`, path | `404` |
| 19 | `POST /api/sources/{source_id}/config` | JSON: `roi`, `line`; `width`, `height`; `lpr_zone` tùy chọn | `ok`, đường dẫn config | `400`, `404`, `422`, `500` |
| 20 | `POST /api/monitoring/start-with-video` | JSON `source_id`, `analysis_mode='line'`, `min_track_frames=5`; có `video_path` nhưng không dùng | Thông tin session vừa chạy | `400`, `401`, `404`, `409`, `500` |
| 21 | `POST /api/monitoring/stop` | Session cookie | `ok`, `message` | `401`, lỗi runtime có thể `500` |
| 22 | `GET /api/monitoring/status` | Session cookie | `active_session_id` và trạng thái | `401` |
| 23 | `GET /api/monitoring/live-state` | Session cookie | `active_session_id`, `live_state` | `401`; state gồm summary/frame/image/error |
| 24 | `POST /api/monitoring/queue` | JSON thô, cần `source_id`; action tùy nhánh | Kết quả thêm/điều khiển hàng chờ | `400`, `401`, `404`, `409` tùy trường hợp |
| 25 | `GET /api/monitoring/queue` | Session cookie | `active_session_id`, `active_live_state`, `queue` | `401` |
| 26 | `DELETE /api/monitoring/queue/{source_id}` | Path source ID | `ok`, `source_id` | `401`, `404` |
| 27 | `GET /api/monitoring/job-status` | Query `video_name` | Trạng thái nguồn/job | Giá trị quan sát: `waiting`, `running`, `complete`; comment còn nhắc `error` |
| 28 | `GET /api/monitoring/output-videos` | Session cookie | `videos`: name, display_name, URL, summary | `401` |
| 29 | `GET /api/monitoring/vscode-output` | Query `video_name` bắt buộc theo logic | `has_output`, `video_url`, `summary` | `400`, `401` |
| 30 | `GET /api/export-reports` | Query `sessions` bắt buộc | CSV UTF-8 BOM, filename `ChiTiet_PhuongTien.csv` | ID lỗi có thể trả JSON lỗi với HTTP 200; chưa login redirect 303 |
| 31 | `GET /api/reports/{session_id}` | Path session ID | `metadata`, `lpr_events`, `chart_data`, hướng, duration | Một số lỗi trả payload `error` nhưng HTTP 200 |
| 32 | `GET /api/stream/active-stats` | Session cookie | Tổng realtime, theo class, danh sách stream | `401` |
| 33 | `GET /api/stream/{source_id}` | Path source ID | MJPEG frame đã xử lý | `400`, `404`, `429` |
| 34 | `GET /api/stream/{source_id}/raw` | Path source ID | MJPEG frame thô | `404` và lỗi stream tùy runtime |
| 35 | `GET /api/stream/{source_id}/stats` | Path source ID | `streaming`, `total`, `per_class`, `directions` | `404` |
| 36 | `POST /api/stream/{source_id}/stop` | Path source ID | `ok` | `404` hoặc lỗi runtime |
| 37 | `POST /api/stream/{source_id}/set-classes` | JSON thô `classes` là list | `ok`, `active_classes`; có nhánh reset | `400`, `404` |
| 38 | `GET /media/{filename:path}` | Path tương đối | File media | Cần session; redirect `303`, hoặc `403`/`404` |
| 39 | `WS /ws/monitoring` | WebSocket | Gói `monitoring` gồm session, stream, live state, LPR, timestamp | Không thấy xác thực WebSocket |
| 40 | `WS /ws/dashboard` | WebSocket | Gói `dashboard`: live state, stream stats, tổng DB theo ngày/toàn kỳ/giờ | Không thấy xác thực WebSocket |
| 41 | `WS /ws/app-status` | WebSocket | `app_status`, active session, có stream hay không, timestamp | Không thấy xác thực WebSocket |

Ngoài các route trên, FastAPI mặc định có thể công bố `/openapi.json`, `/docs`, `/docs/oauth2-redirect` và `/redoc` nếu không bị cấu hình tắt.

### 4.3. Static mount

| Mount | Phạm vi | Xác thực |
|---|---|---|
| `/static/{path}` | CSS, JavaScript, ảnh giao diện | Public |
| `/outputs/{path}` | Toàn bộ cây thư mục output | Public theo cấu hình mount hiện tại |

Mount `/outputs` đáng chú ý vì cây output cũng chứa thư mục `app` và file database. Trong khi `/media/{filename:path}` có kiểm tra đăng nhập và path, static mount `/outputs` không có lớp xác thực tương đương.

### 4.4. Route HTML và form

| Method/path | Chức năng | Input chính | Kết quả |
|---|---|---|---|
| `GET /login` | Trang đăng nhập | Query/flash tùy luồng | Template login |
| `POST /login` | Đăng nhập | Form username/password, CSRF | Tạo session cookie hoặc trả lỗi |
| `POST /logout` | Đăng xuất | Form/session | Xóa session, redirect |
| `GET /access-denied` | Trang từ chối truy cập | — | Template thông báo |
| `GET /` | Dashboard | Session | Template dashboard |
| `GET /dashboard` | Dashboard | Session | Cùng handler dashboard |
| `GET /monitoring` | Trang giám sát | Session | Template monitoring |
| `GET /multi-monitoring` | Giám sát nhiều nguồn | Session | Template multi-monitoring |
| `POST /monitoring/start` | Chạy phân tích qua form | Form source/config | Redirect/thông báo |
| `GET /edit-roi-for-video` | Sửa ROI theo video/path | Query path/source | Template edit ROI |
| `GET /sources/{source_id}/edit-roi` | Sửa ROI một nguồn | Path ID | Template edit ROI |
| `POST /monitoring/stop` | Dừng qua form | Session/CSRF | Redirect/thông báo |
| `GET /reports` | Trang báo cáo | Session | Template reports |
| `GET /admin` | Trang quản trị | Admin session | Template admin |
| `POST /admin/clear-sessions` | Xóa session/report/count | Admin form/CSRF | Redirect kết quả |
| `POST /admin/clear-output` | Xóa output | Admin form/CSRF | Redirect kết quả |
| `POST /admin/clear-logs` | Xóa activity log | Admin form/CSRF | Redirect kết quả |
| `GET /ai-config` | Xem cấu hình AI | Session/quyền | Template cấu hình |
| `POST /ai-config` | Lưu cấu hình AI | Form/CSRF | Redirect/thông báo |
| `GET /users` | Danh sách người dùng | Admin session | Template users |
| `POST /users` | Tạo người dùng | Form username/full name/role/password | Redirect/thông báo |
| `POST /users/{user_id}/toggle` | Bật/tắt user | Path ID, form CSRF | Redirect |
| `POST /users/{user_id}/delete` | Xóa user | Path ID, form CSRF | Redirect |
| `POST /users/{user_id}/reset-password` | Đặt lại mật khẩu | Path ID, form password | Redirect |
| `GET /brand` | Xem cấu hình thương hiệu | Admin/session | Template brand |
| `POST /brand/save` | Lưu tên/logo thương hiệu | Multipart/form | Redirect/thông báo |

## 5. Realtime, file, upload và export

### 5.1. MJPEG/video

| Endpoint | Nội dung |
|---|---|
| `GET /api/stream/{source_id}` | Stream MJPEG đã chạy pipeline nhận diện/đếm |
| `GET /api/stream/{source_id}/raw` | Stream MJPEG frame thô |
| `GET /api/video/input?path=...` | Phục vụ file video đầu vào |

`/api/video/input` đặt media type cố định là `video/mp4`, mặc dù upload chấp nhận cả AVI, MOV và MKV. Điều này có thể làm header `Content-Type` không đúng định dạng file thực tế.

### 5.2. Upload nguồn video

`POST /api/sources/upload`:

- Nhận multipart field `file`.
- Cho phép phần mở rộng `.mp4`, `.avi`, `.mov`, `.mkv`.
- Lưu vào `vehicle_counting_system/data/inputs/videos`.
- Có xử lý đổi tên khi trùng tên file.
- Tạo bản ghi `sources` và trả về `source_id`.
- Chỉ thấy kiểm tra phần mở rộng; không thấy giới hạn kích thước và xác minh MIME/magic bytes.

### 5.3. Upload logo thương hiệu

`POST /brand/save` nhận logo với các phần mở rộng `.jpg`, `.jpeg`, `.png`, `.svg`, `.webp`, `.gif`, lưu thành logo tùy chỉnh trong static. Tương tự upload video, không thấy giới hạn kích thước hoặc xác minh nội dung thực tế của file.

### 5.4. CSV và file media

- `GET /api/export-reports` xuất CSV chi tiết phương tiện, UTF-8 có BOM, tên tải xuống `ChiTiet_Phuong_Tien.csv` theo header/logic xuất file (tên nội bộ quan sát có thể không hoàn toàn đồng nhất ở các vị trí).
- `GET /media/{filename:path}` trả file media sau kiểm tra đăng nhập và đường dẫn.
- `GET /api/monitoring/output-videos` trả metadata và URL các video output.
- `/outputs/{path}` phục vụ static trực tiếp và không áp dụng kiểm tra session giống `/media`.

### 5.5. WebSocket

| Path | Tần suất/nội dung logic | Xác thực |
|---|---|---|
| `/ws/monitoring` | Live state, trạng thái stream, LPR mới, timestamp | Không thấy kiểm tra session |
| `/ws/dashboard` | Tổng theo ngày/toàn kỳ/giờ và dữ liệu stream/session | Không thấy kiểm tra session |
| `/ws/app-status` | Trạng thái app, session và stream | Không thấy kiểm tra session |

## 6. Đối chiếu frontend và backend

### 6.1. Các lời gọi đang hoạt động

| Frontend/template | Backend được sử dụng |
|---|---|
| `app.js` | `/api/client/heartbeat`, `/api/client/disconnect`, `/api/monitoring/status`, `/ws/app-status` |
| `login.html` | `/login` |
| `dashboard.html`, `dashboard.js` | `/api/dashboard`, `/api/vehicle-counts`, `/api/monitoring/live-state`, `/api/stream/active-stats`, `/ws/dashboard` |
| `monitoring.html` và script liên quan | `/api/monitoring/vscode-output`, session detail, stream endpoints, live-state, active-stats, sessions list, upload, add-stream, xóa source/by-path, `/ws/monitoring` |
| `multi_monitoring` | `/api/stream/{id}`, stop stream, active stats |
| `edit_roi` | preview frame, GET/POST config với `roi`, `line`, `width`, `height`, `lpr_zone` |
| `reports.js` | export report, report detail, live-state, `/ws/monitoring` |
| Form users | Route tạo/bật-tắt/xóa/reset password |
| Form admin | Route clear sessions/output/logs |
| Form AI config | GET/POST `/ai-config` |
| Form brand | GET `/brand`, POST `/brand/save` |

Không phát hiện lời gọi frontend đang được template nạp mà hoàn toàn không có endpoint backend tương ứng. Method và các field chính nhìn chung khớp, ngoại trừ lỗi thứ tự route của `/api/sources/by-path`.

### 6.2. Endpoint backend chưa thấy frontend hiện hành gọi trực tiếp

- `GET /api/reports`
- `GET /api/sessions/{session_id}/lpr-events`
- `GET /api/vehicle-counts/summary`
- `GET /api/sessions/{session_id}/vehicle-counts`
- `GET /api/sources`
- `POST /api/monitoring/start-with-video`
- `POST /api/monitoring/stop`
- Ba endpoint `/api/monitoring/queue`
- `GET /api/monitoring/job-status`
- `GET /api/monitoring/output-videos`
- `GET /api/stream/{source_id}/raw`
- `POST /api/stream/{source_id}/set-classes`

`start-with-video` có xuất hiện trong `static/js/monitoring.js`, nhưng file này không được template hiện tại nạp nên không được tính là frontend đang hoạt động.

## 7. Nhóm chức năng nghiệp vụ

| Nhóm | Database/service/route liên quan |
|---|---|
| Đăng nhập và người dùng | `users`, auth service, `/login`, `/logout`, `/users*` |
| Nguồn video/camera | `sources`, upload/add-stream/delete/list/preview |
| ROI và vạch đếm | `counting_config_path`, GET/POST source config, edit ROI |
| Bắt đầu/dừng phân tích | `analysis_sessions`, monitoring service, start/stop/queue |
| Stream realtime | stream manager, MJPEG, active stats, WebSocket |
| Lịch sử đếm | `vehicle_counts`, session history endpoints |
| Biển số xe | `license_plate_events`, LPR service/report |
| Báo cáo | `report_snapshots`, report service, detail/CSV |
| Hệ thống/quản trị | `activity_logs`, clear data, AI config, brand config |
| Media/output | output video, media route, static output mount |

## 8. Ví dụ request/response tiêu biểu

### 8.1. Bắt đầu phân tích một nguồn video

Request:

```http
POST /api/monitoring/start-with-video
Content-Type: application/json
Cookie: <session-cookie>

{
  "source_id": 12,
  "analysis_mode": "line",
  "min_track_frames": 5
}
```

Response thành công có cấu trúc:

```json
{
  "ok": true,
  "session_id": 101,
  "source_id": 12,
  "source_name": "video_demo.mp4",
  "analysis_mode": "line",
  "min_track_frames": 5
}
```

Các lỗi được xử lý rõ trong route gồm `400`, `401`, `404`, `409`, `500`. Schema đánh dấu `source_id` là tùy chọn nhưng handler thực tế yêu cầu phải có. Field `video_path` được schema nhận nhưng không được dùng trong xử lý chính.

### 8.2. Lấy chi tiết báo cáo một session

Request:

```http
GET /api/reports/101
Cookie: <session-cookie>
```

Response logic:

```json
{
  "metadata": {
    "session_id": 101,
    "source_name": "video_demo.mp4",
    "status": "completed",
    "started_at": "...",
    "finished_at": "...",
    "total": 42,
    "per_class": {
      "car": 20,
      "motorcycle": 15,
      "bus": 3,
      "truck": 4
    },
    "output_video_path": "...",
    "media_url": "..."
  },
  "lpr_events": [],
  "chart_data": {
    "labels": [],
    "total": [],
    "car": [],
    "motorcycle": [],
    "bus": [],
    "truck": []
  },
  "direction_counts": {
    "in": 0,
    "out": 0,
    "unknown": 42
  },
  "duration_formatted": "..."
}
```

Route này có nhánh trả `{ "error": ... }` với HTTP 200 thay vì dùng status `4xx/5xx`, vì vậy frontend phải kiểm tra nội dung payload chứ không thể chỉ dựa vào status code.

## 9. Vấn đề, rủi ro và điểm không nhất quán

### 9.1. Độ lệch schema `license_plate_events`

Database thực tế có ba cột `raw_text`, `corrected_text`, `processing_time_ms` nhưng câu lệnh `CREATE TABLE IF NOT EXISTS` hiện tại không có. Điều này cho thấy database từng được nâng cấp bằng mã/migration không còn nằm trong code active, hoặc được tạo bởi phiên bản khác.

Tác động:

- Database mới tạo từ code hiện tại sẽ có schema khác database đang chạy.
- Code nào phụ thuộc ba cột mở rộng có thể lỗi trên môi trường cài mới.
- Không thể tái tạo database production một cách chắc chắn chỉ từ source hiện tại.

### 9.2. Khóa ngoại không được thực thi

DDL có khai báo foreign key nhưng helper kết nối không bật `PRAGMA foreign_keys = ON`. Với SQLite, enforcement mặc định tắt theo từng connection nếu không bật rõ ràng.

Kết quả kiểm tra database tại thời điểm phân tích:

- `PRAGMA integrity_check`: `ok`.
- `PRAGMA foreign_key_check`: có **373 vi phạm** liên quan `license_plate_events` và **4 vi phạm** liên quan `activity_logs`.

Như vậy file database không hỏng vật lý, nhưng có dữ liệu mồ côi theo quan hệ đã khai báo.

### 9.3. Luồng xóa nguồn không xóa toàn bộ dữ liệu phụ thuộc

Handler xóa source xử lý một số dữ liệu liên quan nhưng không thấy xóa `license_plate_events`. Vì foreign key đang tắt, xóa source vẫn có thể thành công và để lại sự kiện biển số mồ côi.

### 9.4. Clear session/report không bao phủ LPR

Chức năng admin clear sessions/reports xóa session, snapshot, vehicle counts và reset một số sequence, nhưng không thấy xử lý tương ứng cho `license_plate_events`. Đây là nguồn có thể tạo session/source reference mồ côi và giữ lại ảnh/dữ liệu nhạy cảm ngoài mong đợi.

### 9.5. Route `/api/sources/by-path` bị che khuất

Hai route cùng method DELETE được khai báo theo thứ tự:

```text
/api/sources/{source_id}
/api/sources/by-path
```

Starlette/FastAPI xét route theo thứ tự; chuỗi `by-path` khớp mẫu động `{source_id}` trước, sau đó validation integer thất bại. Kết quả thực tế có thể là `422`, không chạy handler xóa theo path mà frontend mong đợi.

### 9.6. Public static mount cho output

`/outputs` mount trực tiếp toàn bộ thư mục output mà không có dependency kiểm tra session. Nếu database hoặc file nhạy cảm nằm dưới cây này và static server cho phép truy cập bằng path tương ứng, dữ liệu có thể bị tải xuống mà không cần đăng nhập. Điều này không nhất quán với `/media`, vốn có kiểm tra xác thực và path.

### 9.7. WebSocket không thấy xác thực

Ba WebSocket endpoint không thấy kiểm tra session trước khi accept/gửi dữ liệu. Chúng có thể làm lộ trạng thái xử lý, thống kê và dữ liệu realtime cho client không đăng nhập, tùy cách ứng dụng được triển khai ra mạng.

### 9.8. Comment xác thực không khớp triển khai

Một số comment mô tả API token, nhưng triển khai dùng session cookie. Đây là rủi ro tài liệu gây hiểu nhầm khi tích hợp hoặc kiểm thử bảo mật.

### 9.9. Schema và logic `start-with-video` không đồng nhất

- `source_id` được khai báo optional trong request model nhưng handler coi là bắt buộc.
- `video_path` được nhận nhưng không sử dụng.
- Điều này làm OpenAPI/schema sinh ra không phản ánh đúng hợp đồng runtime.

### 9.10. Lỗi nghiệp vụ trả HTTP 200

Ít nhất API report detail và một số nhánh export trả JSON chứa `error` với status 200. Điều này làm cache, monitoring, client SDK và frontend khó phân biệt thành công/thất bại.

### 9.11. MIME video cố định

Upload nhận MP4/AVI/MOV/MKV nhưng `/api/video/input` luôn trả `video/mp4`. Trình duyệt/proxy có thể xử lý sai AVI/MOV/MKV.

### 9.12. Trạng thái job không thống nhất với mô tả

Comment/tài liệu trong route nhắc tới trạng thái `error`, nhưng logic quan sát chủ yếu trả `waiting`, `running`, `complete`. Client dựa trên comment có thể chờ một trạng thái không bao giờ xuất hiện.

### 9.13. JavaScript cũ không được nạp

`static/js/monitoring.js` có các lời gọi API, bao gồm `start-with-video`, nhưng template monitoring hiện tại không nạp file. Đây có thể là mã dư hoặc dấu hiệu frontend đã được chuyển sang script inline/module khác.

### 9.14. Upload mới chỉ kiểm tra extension

Video và logo chủ yếu được kiểm tra theo phần mở rộng. Không thấy giới hạn dung lượng, kiểm tra MIME thực, magic bytes, quét SVG chủ động hay quota lưu trữ. Rủi ro phụ thuộc việc ứng dụng có được public ra ngoài hay chỉ chạy nội bộ.

## 10. Những điều chưa thể khẳng định chỉ từ source

- Không thể xác định chắc chắn ba cột bổ sung của `license_plate_events` được tạo bởi phiên bản/migration nào vì không tìm thấy lịch sử migration trong code active.
- Không thể khẳng định mọi route public đều có thể truy cập từ Internet; điều này phụ thuộc reverse proxy, firewall và cách deploy bên ngoài project.
- Không thể xác định nội dung thực tế của biến môi trường, secret/session configuration hoặc tài khoản triển khai nếu không đọc môi trường runtime ngoài source.
- Không thể khẳng định format `summary_json` duy nhất vì nhiều pipeline ghi thêm field theo chế độ chạy.
- Không thể kết luận đầy đủ về retention của file ảnh/video nếu có tiến trình ngoài project dọn dẹp dữ liệu.
- Không thấy tài liệu OpenAPI tùy chỉnh hoặc client SDK riêng; hợp đồng API được suy ra trực tiếp từ route và frontend.

## 11. Thứ tự ưu tiên khắc phục đề xuất

Các đề xuất dưới đây chỉ là kết quả phân tích; báo cáo này không thực hiện thay đổi mã nguồn.

1. Đưa schema vào một cơ chế migration có version và bổ sung migration rõ ràng cho ba cột LPR.
2. Bật `PRAGMA foreign_keys = ON` cho mọi connection sau khi có kế hoạch dọn dữ liệu mồ côi; không bật ngay trên database hiện tại mà chưa xử lý 377 vi phạm.
3. Sửa toàn bộ transaction xóa source/session để bao phủ `license_plate_events`, ảnh liên quan và sequence cần thiết.
4. Đặt route tĩnh `/api/sources/by-path` trước route động hoặc đổi path để không xung đột.
5. Không public toàn bộ output tree; đưa database và file nội bộ ra ngoài static root, hoặc bắt buộc xác thực/ủy quyền.
6. Xác thực session và quyền trên WebSocket trước khi `accept` và trước khi gửi dữ liệu.
7. Đồng bộ Pydantic model với logic: bắt buộc `source_id`, bỏ hoặc triển khai `video_path`, thêm response model.
8. Chuẩn hóa status code lỗi và cấu trúc error response.
9. Trả MIME đúng theo loại file, đồng thời bổ sung giới hạn dung lượng và xác minh upload.
10. Xóa hoặc tích hợp rõ JavaScript cũ để tránh hai hợp đồng frontend/backend song song.

## 12. File nguồn quan trọng đã dùng để đối chiếu

- `vehicle_counting_system/configs/paths.py`
- `vehicle_counting_system/infrastructure/persistence/sqlite_db.py`
- `vehicle_counting_system/application/bootstrap.py`
- `vehicle_counting_system/application/services/auth_service.py`
- `vehicle_counting_system/application/services/source_service.py`
- `vehicle_counting_system/application/services/monitoring_service.py`
- `vehicle_counting_system/application/services/report_service.py`
- `vehicle_counting_system/application/services/counting_persistence_service.py`
- `vehicle_counting_system/application/services/lpr_persistence_service.py`
- `vehicle_counting_system/application/services/dashboard_service.py`
- `vehicle_counting_system/presentation/web/app.py`
- `vehicle_counting_system/presentation/web/dependencies.py`
- `vehicle_counting_system/presentation/web/routes/api.py`
- `vehicle_counting_system/presentation/web/routes/stream.py`
- `vehicle_counting_system/presentation/web/routes/ws.py`
- `vehicle_counting_system/presentation/web/routes/reports.py`
- `vehicle_counting_system/presentation/web/routes/monitoring.py`
- `vehicle_counting_system/presentation/web/routes/auth.py`
- Các template và JavaScript đang được template hiện tại nạp.
- `vehicle_counting_system/data/outputs/app/traffic_monitoring.db` được kiểm tra read-only về schema và integrity.

---

# ========== NỘI DUNG ĐỂ SAO CHÉP GỬI CHATGPT ==========

## 1. Bối cảnh hệ thống

Đây là ứng dụng FastAPI giám sát giao thông và đếm phương tiện. Database là SQLite, truy cập trực tiếp bằng `sqlite3`, file tại `vehicle_counting_system/data/outputs/app/traffic_monitoring.db`. Ứng dụng quản lý user, nguồn video/camera, session phân tích, số lượt xe, sự kiện biển số, snapshot báo cáo và activity log. Realtime dùng MJPEG và WebSocket; giao diện server-rendered kết hợp JavaScript gọi API bằng session cookie.

## 2. Database schema tóm tắt

```text
users(
  id PK AI,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL,
  role TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)

sources(
  id PK AI,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'ready',
  notes TEXT NOT NULL DEFAULT '',
  counting_config_path TEXT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
UNIQUE INDEX idx_sources_uri(source_uri)

analysis_sessions(
  id PK AI,
  source_id INTEGER NOT NULL FK -> sources.id,
  started_by INTEGER NOT NULL FK -> users.id,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT NULL,
  output_video_path TEXT NULL,
  summary_json TEXT NOT NULL DEFAULT '{}',
  error_message TEXT NULL
)

report_snapshots(
  id PK AI,
  session_id INTEGER UNIQUE NOT NULL FK -> analysis_sessions.id,
  report_date TEXT NOT NULL,
  total INTEGER NOT NULL DEFAULT 0,
  per_class_json TEXT NOT NULL DEFAULT '{}',
  peak_hour_label TEXT NOT NULL DEFAULT 'N/A',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)

vehicle_counts(
  id PK AI,
  session_id INTEGER NOT NULL FK -> analysis_sessions.id,
  source_id INTEGER NOT NULL FK -> sources.id,
  track_id INTEGER NOT NULL,
  class_name TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  direction TEXT NOT NULL DEFAULT 'unknown',
  line_index INTEGER NOT NULL DEFAULT 0,
  anchor_x REAL NULL,
  anchor_y REAL NULL,
  counted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
INDEXES: session_id, source_id, counted_at

license_plate_events(
  id PK AI,
  session_id INTEGER NOT NULL FK -> analysis_sessions.id,
  source_id INTEGER NOT NULL FK -> sources.id,
  track_id INTEGER NOT NULL,
  vehicle_class TEXT NOT NULL,
  license_plate TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  vehicle_image_path TEXT NULL,
  plate_image_path TEXT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  raw_text TEXT NOT NULL DEFAULT '',
  corrected_text TEXT NOT NULL DEFAULT '',
  processing_time_ms REAL NOT NULL DEFAULT 0
)
INDEXES: session_id, track_id

activity_logs(
  id PK AI,
  user_id INTEGER NULL FK -> users.id,
  username TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  ip_address TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
```

Lưu ý quan trọng: ba cột cuối của `license_plate_events` chỉ có trong database thực tế, không có trong DDL hiện tại. Foreign key được khai báo nhưng connection không bật enforcement. `foreign_key_check` hiện ghi nhận 373 lỗi ở LPR và 4 lỗi ở activity log; `integrity_check` vẫn `ok`.

## 3. Quan hệ dữ liệu

```text
users 1--N analysis_sessions
users 1--N activity_logs
sources 1--N analysis_sessions
analysis_sessions 1--0..1 report_snapshots
analysis_sessions 1--N vehicle_counts
sources 1--N vehicle_counts
analysis_sessions 1--N license_plate_events
sources 1--N license_plate_events
```

Không có cascade delete và không có bảng many-to-many. `track_id` nối logic giữa count và LPR nhưng không có FK/unique constraint tương ứng.

## 4. API chính

```text
POST   /api/client/heartbeat
POST   /api/client/disconnect
GET    /api/dashboard
GET    /api/sessions
GET    /api/sessions/{session_id}
GET    /api/sessions/{session_id}/lpr-events
GET    /api/reports
GET    /api/vehicle-counts
GET    /api/vehicle-counts/summary
GET    /api/sessions/{session_id}/vehicle-counts
POST   /api/sources/upload
POST   /api/monitoring/add-stream
DELETE /api/sources/{source_id}
DELETE /api/sources/by-path
GET    /api/video/input
GET    /api/sources
GET    /api/sources/{source_id}/preview-frame
GET    /api/sources/{source_id}/config
POST   /api/sources/{source_id}/config
POST   /api/monitoring/start-with-video
POST   /api/monitoring/stop
GET    /api/monitoring/status
GET    /api/monitoring/live-state
POST   /api/monitoring/queue
GET    /api/monitoring/queue
DELETE /api/monitoring/queue/{source_id}
GET    /api/monitoring/job-status
GET    /api/monitoring/output-videos
GET    /api/monitoring/vscode-output
GET    /api/export-reports
GET    /api/reports/{session_id}
GET    /api/stream/active-stats
GET    /api/stream/{source_id}
GET    /api/stream/{source_id}/raw
GET    /api/stream/{source_id}/stats
POST   /api/stream/{source_id}/stop
POST   /api/stream/{source_id}/set-classes
GET    /media/{filename:path}
WS     /ws/monitoring
WS     /ws/dashboard
WS     /ws/app-status
```

Các route HTML/form còn có login/logout, dashboard, monitoring, multi-monitoring, ROI editor, reports, admin clear data, AI config, users và brand config.

## 5. Hợp đồng dữ liệu đáng chú ý

- `POST /api/sources/upload`: multipart `file`, nhận mp4/avi/mov/mkv, trả `source_id` và path.
- `POST /api/monitoring/add-stream`: JSON `{name, url}`.
- `POST /api/sources/{id}/config`: JSON `{roi, line, width, height, lpr_zone}`.
- `POST /api/monitoring/start-with-video`: JSON `{source_id, analysis_mode, min_track_frames}`; `source_id` thực tế bắt buộc.
- `GET /api/monitoring/live-state`: trả session, summary, frame index, output path, ảnh base64, lỗi và timestamp.
- `GET /api/stream/{id}` và `/raw`: MJPEG.
- `GET /api/export-reports`: CSV UTF-8 BOM.
- WebSocket dashboard/monitoring/app-status đẩy dữ liệu realtime nhưng chưa thấy auth.

## 6. Lỗi/điểm cần sửa ưu tiên cao

1. Có schema drift ở `license_plate_events`; cần migration có version.
2. Foreign key chưa bật và database có 377 vi phạm quan hệ.
3. Xóa source/session không bao phủ đầy đủ LPR, gây orphan.
4. `DELETE /api/sources/by-path` bị route `/{source_id}` che khuất.
5. `/outputs` public toàn bộ output tree, có nguy cơ lộ database/file nội bộ.
6. Ba WebSocket chưa thấy kiểm tra session/quyền.
7. Request model `start-with-video` không khớp handler; `video_path` không dùng.
8. Một số lỗi API trả HTTP 200.
9. Video input luôn trả `video/mp4` dù nhận nhiều định dạng.
10. Upload thiếu giới hạn kích thước và xác minh nội dung thực.

## 7. Frontend/backend

Frontend đang hoạt động có endpoint tương ứng cho heartbeat, dashboard, monitoring, stream, ROI, reports, users, admin, AI config và brand. Không thấy lời gọi frontend active nào hoàn toàn không tồn tại ở backend. Ngoại lệ chức năng là `/api/sources/by-path`: endpoint có khai báo nhưng thứ tự route khiến request có thể rơi vào route động và lỗi 422.

Một số backend endpoint chưa thấy frontend hiện tại dùng trực tiếp: API danh sách reports, LPR theo session, vehicle summary, source list, queue/job-status/output-videos, raw stream và set-classes. `static/js/monitoring.js` có lời gọi cũ nhưng không được template nạp.

## 8. Câu hỏi nên yêu cầu AI hỗ trợ tiếp

1. Thiết kế migration an toàn để đồng bộ schema LPR mà không mất dữ liệu.
2. Viết quy trình dọn 377 orphan trước khi bật foreign key.
3. Thiết kế transaction/cascade delete đúng cho source và session.
4. Audit và vá quyền truy cập `/outputs`, `/media` và WebSocket.
5. Chuẩn hóa OpenAPI bằng request/response model và status code.
6. Viết test integration cho toàn bộ route conflict, auth, upload, export và realtime.

## 9. Ràng buộc khi đề xuất thay đổi

- Không được giả định database mới giống database hiện tại; phải xử lý schema drift.
- Không bật foreign key ngay trước khi dọn orphan.
- Không xóa file/output hoặc record LPR nếu chưa có backup và mapping rõ ràng.
- Phải giữ tương thích session cookie của frontend hiện tại hoặc lập kế hoạch migration xác thực.
- Mọi thay đổi route cần kiểm thử frontend hiện đang dùng và route cũ trong JavaScript không còn được nạp.

---

Kết thúc báo cáo. Không có file mã nguồn nào được chỉnh sửa trong quá trình tạo tài liệu này.
