#!/usr/bin/env python
"""Chạy phân tích video dùng ROI đã cấu hình trên web.

Workflow:
  1. Chỉnh ROI trên web (trang Giám sát → Chỉnh ROI)
  2. Chạy script này trong VS Code để xử lý local (mượt, ổn định hơn web)

Cách dùng:
  python run_with_web_roi.py
  python run_with_web_roi.py --source data/input/videos/test.mp4
  python run_with_web_roi.py --source test.mp4 --output-video ket_qua.mp4
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = ROOT / "vehicle_counting_system"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(PKG if PKG.exists() else ROOT)


def main() -> int:
    import argparse
    from vehicle_counting_system.application.bootstrap import build_container
    from vehicle_counting_system.configs.paths import INPUT_VIDEOS_DIR, PROJECT_ROOT
    from vehicle_counting_system.utils.file_utils import ensure_dir

    p = argparse.ArgumentParser(
        description="Chạy đếm xe dùng ROI đã chỉnh trên web. Xử lý local mượt hơn web."
    )
    p.add_argument(
        "--source",
        default=str(INPUT_VIDEOS_DIR / "test.mp4"),
        help="Đường dẫn video (mặc định: data/input/videos/test.mp4)",
    )
    p.add_argument(
        "--output-video",
        default=None,
        help="Đường dẫn video output (mặc định: data/outputs/videos/{tên}_result.mp4)",
    )
    p.add_argument(
        "--no-export-csv",
        action="store_true",
        help="Không xuất CSV kết quả.",
    )
    args = p.parse_args()

    source_path = args.source.strip()
    if not Path(source_path).is_absolute():
        source_path = str((PROJECT_ROOT / source_path).resolve())

    container = build_container()
    source = container.source_service.get_source_by_uri(source_path)

    if source is None:
        print("Không tìm thấy source cho video này trong cơ sở dữ liệu.")
        print("Hãy thêm video vào web (trang Giám sát) và chỉnh ROI trước.")
        print(f"  Video: {source_path}")
        return 1

    if not source.counting_config_path:
        print("Video này chưa có ROI. Vui lòng chỉnh ROI trên web trước:")
        print("  1. Mở web → Giám sát")
        print("  2. Chọn video → Chỉnh ROI")
        print("  3. Vẽ vùng ROI và đường đếm → Lưu")
        print(f"  Video: {source.name}")
        return 1

    from vehicle_counting_system.configs.paths import OUTPUT_VIDEOS_DIR, OUTPUT_CSV_DIR
    output_path = args.output_video
    if not output_path:
        # Output theo tên video: Test3.mp4 -> Test3_result.mp4 (web dễ map)
        safe_name = Path(source.name).stem
        output_path = str(OUTPUT_VIDEOS_DIR / f"{safe_name}_result.mp4")
    ensure_dir(Path(output_path).parent)

    # Ghi file .running để web biết đang xử lý
    running_marker = OUTPUT_VIDEOS_DIR / f"{Path(source.name).stem}.running"
    try:
        running_marker.write_text(source.name, encoding="utf-8")
    except Exception:
        pass

    print("Đang chạy phân tích local với ROI từ web...")
    print(f"  Video: {source.name}")
    print(f"  ROI config: {source.counting_config_path}")
    print()

    # Dùng source_uri (đường dẫn tuyệt đối) để tránh lệch path
    video_arg = source.source_uri if Path(source.source_uri).exists() else args.source
    sys.argv = [
        "main.py",
        "--source", video_arg,
        "--output-video", output_path,
        "--counting-lines", source.counting_config_path,
    ]
    if args.no_export_csv:
        sys.argv.append("--no-export-csv")

    from vehicle_counting_system.main import main as _main
    try:
        exit_code = _main()
    finally:
        try:
            running_marker.unlink(missing_ok=True)
        except Exception:
            pass

    # Sau khi chạy xong: copy entry cuối từ summary.json sang {name}_summary.json để web map
    if exit_code == 0 and not args.no_export_csv:
        summary_path = OUTPUT_CSV_DIR / "summary.json"
        if summary_path.exists():
            try:
                import json
                data = json.loads(summary_path.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    last = data[-1]
                    out_summary = OUTPUT_VIDEOS_DIR / f"{Path(source.name).stem}_summary.json"
                    out_summary.write_text(json.dumps(last, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
