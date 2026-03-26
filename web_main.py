#!/usr/bin/env python
"""Chạy web UI bằng nút Run (▶) trong VS Code.

- Tự mở trình duyệt vào /monitoring.
- Khi bạn đóng hết tab web (không còn heartbeat), server tự tắt sau vài giây.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    from vehicle_counting_system.web_main import main

    raise SystemExit(main())

