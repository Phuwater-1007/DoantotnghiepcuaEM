#!/usr/bin/env python
"""Chạy phân tích video từ thư mục gốc dự án.

Cách dùng:
  python run_video.py
  python run_video.py --source data/input/videos/video1.mp4
  python run_video.py --source data/input/videos/test.mp4 --output-video data/output/videos/ket_qua.mp4
"""
import os
import sys
from pathlib import Path

# Đảm bảo chạy từ thư mục gốc dự án
ROOT = Path(__file__).resolve().parent
PKG = ROOT / "vehicle_counting_system"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Cwd = package root để path tương đối (data/input/...) hoạt động đúng
os.chdir(PKG if PKG.exists() else ROOT)

if __name__ == "__main__":
    from vehicle_counting_system.main import main
    sys.exit(main())
