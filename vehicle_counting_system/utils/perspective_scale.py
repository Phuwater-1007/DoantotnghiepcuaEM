# ===== file: utils/perspective_scale.py =====
"""Perspective scale utilities based on ROI polygon geometry."""

class PerspectiveScale:
    """Tính perspective scale factor từ ROI polygon.
    
    ROI polygon chứa thông tin phối cảnh ngầm:
    - Top edge (Y nhỏ) = xa camera → xe nhỏ
    - Bottom edge (Y lớn) = gần camera → xe lớn
    
    Scale factor: 0.0 (xa nhất) -> 1.0 (gần nhất)
    """
    
    def __init__(self, roi_polygon: list, frame_height: int = 720):
        self.frame_height = frame_height
        if not roi_polygon or len(roi_polygon) < 3:
            # Fallback nếu không có ROI
            self.y_min = 0
            self.y_max = frame_height
            self.y_range = frame_height
            self.perspective_ratio = 0.5
            return
            
        # Tính Y range từ ROI
        self.y_min = min(p[1] for p in roi_polygon)  # Top of ROI (xa)
        self.y_max = max(p[1] for p in roi_polygon)  # Bottom of ROI (gần)
        self.y_range = max(1, self.y_max - self.y_min)
        
        # Tính width ratio (top/bottom) để ước lượng perspective strength
        # ROI top edge hẹp hơn bottom edge -> perspective mạnh
        top_width = self._roi_width_at_y(self.y_min, roi_polygon)
        bot_width = self._roi_width_at_y(self.y_max, roi_polygon)
        
        ratio = top_width / max(1.0, bot_width)
        self.perspective_ratio = max(0.1, min(1.0, ratio))
    
    def _roi_width_at_y(self, y: float, polygon: list) -> float:
        if not polygon or len(polygon) < 3:
            return 100.0  # Fallback width
        intersections = []
        n = len(polygon)
        for i in range(n):
            p1 = polygon[i]
            p2 = polygon[(i + 1) % n]
            x1, y1 = p1
            x2, y2 = p2
            if min(y1, y2) <= y <= max(y1, y2):
                if y2 != y1:
                    x_intersect = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                    intersections.append(x_intersect)
                else:
                    # Parallel horizontal edge, add both vertices
                    intersections.extend([x1, x2])
        if not intersections:
            return 100.0
        return max(0.1, max(intersections) - min(intersections))

    def get_scale(self, y: float) -> float:
        """Trả về scale factor (tỷ lệ với bottom width) theo vị trí Y trong ROI."""
        t = (y - self.y_min) / self.y_range  # 0 = top ROI, 1 = bottom ROI
        t = max(0.0, min(1.0, t))
        # Interpolate theo perspective: gần camera -> scale lớn
        return self.perspective_ratio + t * (1.0 - self.perspective_ratio)
    
    def scale_area(self, y: float, base_area: float) -> float:
        """Scale MIN_BOX_AREA theo vị trí Y. Xa camera -> cho phép nhỏ hơn."""
        s = self.get_scale(y)
        return base_area * s * s  # Area tỷ lệ thuận với bình phương kích thước dài
    
    def scale_distance(self, y: float, base_dist: float) -> float:
        """Scale debounce radius theo vị trí Y."""
        return base_dist * self.get_scale(y)
