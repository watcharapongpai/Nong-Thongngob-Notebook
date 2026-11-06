"""เติมคอลัมน์ spec_summary (สเปกคร่าว ๆ) และ suitable_for (ผ่านเกณฑ์การใช้งานไหนบ้าง)
ลงใน data/products.csv โดยคำนวณจากข้อมูลในไฟล์และเกณฑ์ใน bot/rules.py

ใช้หลังแก้ข้อมูลสินค้าหรือแก้เกณฑ์:  python tools/enrich_catalog.py
(ตัวบอทคำนวณเองตอนรันอยู่แล้ว สองคอลัมน์นี้มีไว้ให้คนอ่าน/ใส่ในรายงาน)
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.catalog import Catalog  # noqa: E402

CSV_PATH = ROOT / "data" / "products.csv"
EXTRA = ["spec_summary", "suitable_for"]


def main():
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h for h in reader.fieldnames if h not in EXTRA]
        rows = list(reader)
    catalog = Catalog.from_csv(CSV_PATH)
    for r in rows:
        p = catalog.get(r["product_id"])
        r["spec_summary"] = p.spec_summary()
        r["suitable_for"] = ", ".join(p.suitable_labels())
    idx = header.index("promo_price_thb") + 1  # วางสเปกคร่าว ๆ ไว้ถัดจากราคา อ่านง่ายใน Excel
    fieldnames = header[:idx] + EXTRA + header[idx:]
    # utf-8-sig ทำให้ Excel เปิดภาษาไทยได้ถูกต้อง
    with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"updated {len(rows)} rows in {CSV_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
