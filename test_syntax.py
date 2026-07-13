import sys
from pathlib import Path

# Add root folder to sys.path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from vehicle_counting_system.ai_core.services.lpr_service import LPRService

def run_tests():
    class MockLPRService(LPRService):
        def _init_models(self):
            # Bypass model loading for syntax test
            self.detector = None
            self.char_recognizer = None
            self.images_dir = Path(".")
            
    service = MockLPRService(use_gpu=False)
    
    test_cases = [
        # (input_text, expected_output, vehicle_class)
        # 1. Motorcycle 5-digit (e.g. 29G1-12611)
        ("29G1L2611", "29G112611", "motorcycle"),
        ("29G112611", "29G112611", "motorcycle"),
        ("29G1I2611", "29G112611", "motorcycle"),
        ("29G1S2611", "29G152611", "motorcycle"),
        # 2. Motorcycle 4-digit (e.g. 30T4-1945)
        ("30T419A5", "30T41945", "motorcycle"),
        ("3OT41945", "30T41945", "motorcycle"),
        # 3. Car 5-digit (e.g. 30F-12345)
        ("30F1234S", "30F12345", "car"),
        ("30F12345", "30F12345", "car"),
        # 4. Joint venture / special plates (e.g. 29LD-12345)
        ("29LD123A5", "29LD12345", "car"),
        ("29LD12345", "29LD12345", "car"),
        # 5. Car 4-digit (e.g. 29A-1234)
        ("29A123A", "29A1234", "car"),
        ("29A1234", "29A1234", "car"),
        # 6. Military plates (e.g. KP-12-34)
        ("KP123A", "KP1234", "unknown"),
        ("KP1234", "KP1234", "unknown"),
    ]
    
    success = True
    for idx, (inp, expected, vclass) in enumerate(test_cases):
        out = service.correct_vietnamese_plate_syntax(inp, vclass)
        if out == expected:
            print(f"[PASS] Case {idx+1}: {inp} ({vclass}) -> {out}")
        else:
            print(f"[FAIL] Case {idx+1}: {inp} ({vclass}) -> {out} (Expected: {expected})")
            success = False
            
    if success:
        print("\nAll tests passed successfully!")
        sys.exit(0)
    else:
        print("\nSome tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
