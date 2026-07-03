from pathlib import Path

def search_files(keyword):
    core_dir = Path("c:/Users/admin/Desktop/Python/doan/vehicle_counting_system/core")
    for file in core_dir.glob("*.py"):
        with open(file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        for idx, line in enumerate(lines):
            if keyword in line:
                print(f"{file.name}:{idx+1}: {line.strip()}")

if __name__ == "__main__":
    print("Searching for 'char_detector':")
    search_files("char_detector")
    print("\nSearching for 'plate':")
    search_files("plate")
