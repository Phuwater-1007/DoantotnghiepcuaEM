# Product Architecture Blueprint

## Product Vision

Bien he thong dem xe hien tai thanh mot san pham giam sat giao thong thong minh co giao dien, phan quyen nguoi dung, dashboard, cau hinh nguon, bao cao va canh bao.

Muc tieu cho do an/demo:
- nhin nhu mot san pham doc lap
- co quy trinh su dung ro rang: dang nhap -> chon nguon -> chay phan tich -> xem dashboard -> xem bao cao
- giu lai pipeline AI hien co lam technical core
- san sang mo rong sang camera/live stream sau nay

## Recommended Layers

### 1. AI Engine Layer
- detector, tracker, classifier, counter, pipeline
- chiu trach nhiem xu ly frame/video/source
- khong chua logic nguoi dung, UI, hay role

### 2. Application Layer
- quan ly use-case
- bat/tat phien phan tich
- quan ly nguon video/camera
- dieu phoi export, dashboard data, report data

### 3. Domain/Data Layer
- user
- role/permission
- source
- analysis session
- traffic statistics
- alerts
- report models

### 4. Infrastructure Layer
- file storage / sqlite
- auth provider
- logging
- config loading
- repository implementation

### 5. Presentation Layer
- desktop UI hoac web UI
- dashboard, login, reports, source config
- chi goi application services, khong goi truc tiep detector/tracker

## Suggested Product Modules

### Auth & Users
- login/logout
- account list
- role assignment
- permissions

### Source Management
- offline video source
- local camera source
- future rtsp/ip camera source
- source health/status

### Monitoring & Sessions
- start analysis
- stop analysis
- session history
- current active source
- current processing state

### Dashboard
- tong luong xe hom nay
- theo loai xe
- thong ke theo source
- cards + chart + quick status

### Reporting
- loc theo ngay/gio
- luu luong theo khung gio
- gio cao diem
- bang du lieu + export csv/json

### Alerts
- nguong mat do giao thong cao
- gio cao diem
- future: camera offline / source disconnected

## Suggested Folder Direction

Giu lai core hien tai, sau do tien hoa dan theo huong:

```text
vehicle_counting_system/
  app.py
  main.py
  docs/
    PRODUCT_ARCHITECTURE.md
  ai_core/
    detectors/
    trackers/
    counters/
    classifiers/
    pipeline/
  application/
    services/
      auth_service.py
      session_service.py
      dashboard_service.py
      report_service.py
      source_service.py
      alert_service.py
    dto/
  domain/
    models/
      user.py
      role.py
      permission.py
      source.py
      analysis_session.py
      traffic_report.py
      traffic_alert.py
  infrastructure/
    persistence/
      sqlite/
    repositories/
    auth/
    config/
  presentation/
    desktop/
    web/
  shared/
    logging/
    utils/
```

## Mapping From Current Code

### Keep and later move into `ai_core/`
- `detectors/`
- `trackers/`
- `counters/`
- `classifiers/`
- `core/frame_processor.py`
- `core/pipeline.py`

### Keep but gradually reorganize
- `models/` -> tach thanh `domain/models/` va `ai_core/models/`
- `services/export_service.py` -> `application/services/report_service.py`
- `configs/` -> `infrastructure/config/`
- `utils/` -> `shared/utils/`

### Replace over time
- `main_ui.py`, `ui/*` placeholder -> thay bang giao dien that

## Demo-First UX Flow

1. Login
2. Dashboard
3. Source Configuration
4. Start Monitoring
5. Live Result / Session Screen
6. Reports
7. Users (admin only)

## Recommended Screen Set

### Login
- username/password
- role hint
- basic branding

### Dashboard
- tong xe hom nay
- car/motorcycle/truck/bus
- source dang chay
- quick cards
- chart theo gio
- alert box

### Source Configuration
- chon video
- chon camera
- source list
- status: active/inactive
- thong so model co ban

### Monitoring Screen
- video/camera preview
- line/roi config summary
- status run/stop
- live counters
- last alerts

### Reports
- bo loc theo thoi gian
- chart luu luong
- bang thong ke
- xuat csv/json

### User Management
- danh sach user
- tao/sua user
- role: admin/user

## Thesis-Demo Practical Scope

### Must-Have
- login gia lap hoac sqlite auth don gian
- dashboard co du lieu that tu output hien co
- source config cho offline video + camera placeholder
- monitoring screen
- report screen

### Can Mock/Simplify Initially
- quyen chi tiet theo tung action
- alert real-time phuc tap
- multi-camera dong thoi
- RTSP production-grade reconnect

## Recommended First Structural Moves

1. Dung them logic moi trong `main.py`
2. Tao `application/services/` cho dashboard, report, source, auth
3. Giu pipeline AI lam engine doc lap
4. Tao 1 storage don gian bang SQLite cho user, source, session, report summary
5. Chon 1 giao dien that:
   - desktop-first: PySide6/PyQt6
   - web-first: FastAPI + React/Vite

## UI Strategy Recommendation

Cho do an/demo, co 2 huong:

### Option A - Desktop Product Demo
- PySide6/PyQt6
- de demo offline tren may giang vien
- nhin giong phan mem giam sat

### Option B - Web Dashboard Product Demo
- FastAPI backend + React frontend
- nhin hien dai hon, de trinh bay dashboard/report/auth
- van giu AI engine Python rieng

Neu uu tien “nhin giong san pham that” nhanh nhat cho thesis: web dashboard + local backend la lua chon dep hon.
