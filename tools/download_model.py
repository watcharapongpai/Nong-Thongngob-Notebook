"""ดาวน์โหลดโมเดล CLIP ไว้ล่วงหน้า (ทำครั้งเดียวตอนมีอินเทอร์เน็ต ก่อนวันเดโม)

รัน:  python tools/download_model.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from bot import vision  # noqa: E402

if __name__ == "__main__":
    analyzer = vision.ClipRelevance()
    print(f"กำลังโหลดโมเดล {analyzer.model_name} (ครั้งแรกประมาณ 600 MB) ...")
    try:
        analyzer.warmup()
    except vision.VisionUnavailable as e:
        sys.exit(f"ไม่สำเร็จ: {e}")
    result = analyzer.analyze(Image.new("RGB", (224, 224), "white"))
    print("พร้อมใช้งาน — ทดลองกับรูปพื้นขาว:", result)
