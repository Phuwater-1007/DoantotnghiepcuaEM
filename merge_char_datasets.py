"""Gộp 2 dataset detect ký tự biển số thành 1 dataset thống nhất 36 class.

Dataset 210: 36 class (0-9, A-Z) — class ID mapping chuẩn
Dataset v1:  35 class (0-9, A-Z trừ 'I') — cần remap class ID

Output: data/char_dataset_merged/ với 36 class thống nhất
"""

import shutil
from pathlib import Path
import yaml

# Paths
BASE = Path(r"c:\Users\admin\Desktop\Python\doan\data")
DS_210 = BASE / "char_dataset_210"
DS_V1 = BASE / "char_dataset_v1"
DS_MERGED = BASE / "char_dataset_merged"

# Unified 36 classes
UNIFIED_NAMES = [
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
    'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J',
    'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T',
    'U', 'V', 'W', 'X', 'Y', 'Z'
]

# Dataset v1 names (35 classes, missing 'I' at index 18)
V1_NAMES = [
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
    'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K',
    'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U',
    'V', 'W', 'X', 'Y', 'Z'
]

# Build remap: v1_class_id -> unified_class_id
V1_TO_UNIFIED = {}
for v1_id, name in enumerate(V1_NAMES):
    unified_id = UNIFIED_NAMES.index(name)
    V1_TO_UNIFIED[v1_id] = unified_id

print("V1 -> Unified class ID mapping:")
for v1_id, uni_id in V1_TO_UNIFIED.items():
    print(f"  {v1_id} ({V1_NAMES[v1_id]}) -> {uni_id} ({UNIFIED_NAMES[uni_id]})")


def copy_dataset(src_dir: Path, dst_dir: Path, split: str, remap: dict | None = None, prefix: str = ""):
    """Copy images and labels from src to dst, optionally remapping class IDs."""
    src_img = src_dir / split / "images"
    src_lbl = src_dir / split / "labels"
    dst_img = dst_dir / split / "images"
    dst_lbl = dst_dir / split / "labels"
    
    dst_img.mkdir(parents=True, exist_ok=True)
    dst_lbl.mkdir(parents=True, exist_ok=True)
    
    if not src_img.exists():
        print(f"  Skipping {src_img} (not found)")
        return 0
    
    count = 0
    for img_file in src_img.iterdir():
        if img_file.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}:
            continue
        
        # Copy image with prefix to avoid name conflicts
        new_name = f"{prefix}{img_file.name}" if prefix else img_file.name
        shutil.copy2(img_file, dst_img / new_name)
        
        # Copy/remap label
        lbl_file = src_lbl / (img_file.stem + ".txt")
        new_lbl_name = f"{prefix}{img_file.stem}.txt" if prefix else f"{img_file.stem}.txt"
        
        if lbl_file.exists():
            if remap:
                # Read and remap class IDs
                lines = lbl_file.read_text().strip().split("\n")
                new_lines = []
                for line in lines:
                    if not line.strip():
                        continue
                    parts = line.strip().split()
                    old_cls = int(parts[0])
                    new_cls = remap.get(old_cls, old_cls)
                    new_lines.append(f"{new_cls} {' '.join(parts[1:])}")
                (dst_lbl / new_lbl_name).write_text("\n".join(new_lines) + "\n")
            else:
                shutil.copy2(lbl_file, dst_lbl / new_lbl_name)
        
        count += 1
    
    return count


# Clean and create merged directory
if DS_MERGED.exists():
    shutil.rmtree(DS_MERGED)

print("\n=== Merging datasets ===")
total = 0

# Copy Dataset 210 (already has correct 36-class IDs)
for split in ["train", "valid", "test"]:
    n = copy_dataset(DS_210, DS_MERGED, split, remap=None, prefix="d210_")
    print(f"  Dataset 210 [{split}]: {n} images")
    total += n

# Copy Dataset v1 (needs class ID remapping)
for split in ["train", "valid", "test"]:
    n = copy_dataset(DS_V1, DS_MERGED, split, remap=V1_TO_UNIFIED, prefix="dv1_")
    print(f"  Dataset v1  [{split}]: {n} images")
    total += n

print(f"\nTotal merged: {total} images")

# Write data.yaml
data_yaml = {
    'train': 'train/images',
    'val': 'valid/images',
    'test': 'test/images',
    'nc': 36,
    'names': UNIFIED_NAMES
}

yaml_path = DS_MERGED / "data.yaml"
with open(yaml_path, 'w') as f:
    yaml.dump(data_yaml, f, default_flow_style=False, allow_unicode=True)

print(f"\ndata.yaml written to: {yaml_path}")
print("Done! Dataset merged successfully.")
