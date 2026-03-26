## Processing flow

```text
Video/Camera
   ↓
Read frame
   ↓
Detect (YOLO)
   ↓
Track (IoU placeholder / later ByteTrack)
   ↓
Count (line crossing)
   ↓
Export (CSV/log/video) + Visualize
```

