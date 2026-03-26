# Vehicle Counting System

Sample system built around the flow: **detect -> track -> count -> export**.

## Quick Demo (OpenCV)

1. Create a virtual environment and install dependencies:

```bash
pip install -r requirements.txt
```

2. Add a test video to `data/input/videos/test.mp4`

3. Run:

```bash
python main.py
```

Press `q` to exit.

## Product Web Demo

Web entrypoint for the thesis/demo build:

```bash
uvicorn product_web:app --reload
```

Then open:

- `http://127.0.0.1:8000/login`

If you want sessions to remain valid across restarts, set `TRAFFIC_MONITORING_SESSION_SECRET` before starting the web app.

## CLI Options

```bash
python main.py --source 0
python main.py --source "path/to/video.mp4" --output-video "data/output/videos/out.mp4"
python main.py --counting-lines "configs/counting_lines.json"
```

## Output

- Video: `data/output/videos/result.mp4`
- CSV summary: `data/output/csv/summary.csv`
- Log: `data/output/logs/vehicle_counting.log`

## Product Roadmap

- Product-oriented architecture blueprint: `docs/PRODUCT_ARCHITECTURE.md`
- Safe editable ROI/line config: `configs/editable_roi.json`
- Web product scaffold entrypoint: `product_web.py`

## Data Directory Note

The project supports both directory layouts:

- `data/inputs` + `data/outputs`
- `data/input` + `data/output`
