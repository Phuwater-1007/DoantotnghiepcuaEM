#!/usr/bin/env python
"""Điểm vào chính - chạy phân tích video. Ấn Run (▶) trong VS Code để chạy."""
import sys
from pathlib import Path

# Đảm bảo package được tìm thấy
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    from vehicle_counting_system.main import main
    sys.exit(main())
