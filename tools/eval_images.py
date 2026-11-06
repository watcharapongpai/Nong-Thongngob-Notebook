"""วัดความแม่นยำของการตรวจว่ารูป "เกี่ยวกับโน้ตบุ๊ก" หรือไม่ (ใช้เป็นผลการทดลองในรายงาน)

เตรียมรูปทดสอบแยกเป็น 2 โฟลเดอร์:
    eval_images/
        relevant/     รูปที่เกี่ยวกับโน้ตบุ๊ก (รูปเครื่อง สติกเกอร์สเปก ภาพหน้าจอหน้าสินค้า ...)
        irrelevant/   รูปที่ไม่เกี่ยว (มือถือ อาหาร คน วิว มีม ...)

รัน:  python tools/eval_images.py eval_images
ผลลัพธ์: คะแนนรายรูป, Accuracy/Precision/Recall/F1 ที่เกณฑ์ปัจจุบัน, ตารางลองเกณฑ์หลายค่า
และไฟล์ eval_results.csv สำหรับแนบรายงาน
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot import vision  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def evaluate(analyzer, folder: Path) -> list[dict]:
    rows = []
    for label in ("relevant", "irrelevant"):
        sub = folder / label
        if not sub.is_dir():
            continue
        for f in sorted(sub.iterdir()):
            if f.suffix.lower() not in IMAGE_EXT:
                continue
            try:
                img = vision.load_image(f.read_bytes())
            except vision.ImageError as e:
                print(f"ข้าม {f.name}: {e}")
                continue
            a = analyzer.analyze(img)
            rows.append({"file": f"{label}/{f.name}", "actual": label, "score": a["score"],
                         "verdict": a["verdict"], "kind": a["kind"], "top_prompt": a["top_prompt"]})
    return rows


def metrics_at(rows: list[dict], threshold: float) -> dict:
    tp = sum(r["actual"] == "relevant" and r["score"] >= threshold for r in rows)
    fp = sum(r["actual"] == "irrelevant" and r["score"] >= threshold for r in rows)
    fn = sum(r["actual"] == "relevant" and r["score"] < threshold for r in rows)
    tn = sum(r["actual"] == "irrelevant" and r["score"] < threshold for r in rows)
    n = len(rows) or 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "accuracy": (tp + tn) / n, "precision": precision, "recall": recall, "f1": f1}


def main():
    if len(sys.argv) < 2:
        sys.exit("วิธีใช้: python tools/eval_images.py <โฟลเดอร์ที่มี relevant/ และ irrelevant/>")
    folder = Path(sys.argv[1])
    rows = evaluate(vision.ClipRelevance(), folder)
    if not rows:
        sys.exit("ไม่พบรูปในโฟลเดอร์ relevant/ หรือ irrelevant/")

    print(f"\n{'ไฟล์':40} {'จริง':11} {'คะแนน':>6}  ผลตรวจ")
    for r in rows:
        print(f"{r['file'][:40]:40} {r['actual']:11} {r['score']*100:5.1f}%  {r['verdict']}")

    m = metrics_at(rows, vision.RELEVANT_AT)
    print(f"\nเกณฑ์ปัจจุบัน RELEVANT_AT = {vision.RELEVANT_AT:.2f} (นับ 'ไม่แน่ใจ' เป็นไม่เกี่ยวข้อง)")
    print(f"  รูปทั้งหมด {len(rows)} รูป | TP {m['tp']}  FP {m['fp']}  FN {m['fn']}  TN {m['tn']}")
    print(f"  Accuracy {m['accuracy']:.1%}  Precision {m['precision']:.1%}  "
          f"Recall {m['recall']:.1%}  F1 {m['f1']:.3f}")

    print("\nลองเกณฑ์หลายค่า:")
    sweep = [metrics_at(rows, t / 100) for t in range(30, 95, 5)]
    for s in sweep:
        print(f"  {s['threshold']:.2f}  Acc {s['accuracy']:.1%}  P {s['precision']:.1%}  "
              f"R {s['recall']:.1%}  F1 {s['f1']:.3f}")
    best = max(sweep, key=lambda s: (s["f1"], s["accuracy"]))
    print(f"\nเกณฑ์ที่ได้ F1 สูงสุด: {best['threshold']:.2f} (แก้ RELEVANT_AT ใน bot/vision.py ได้)")

    out = Path("eval_results.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"บันทึกผลรายรูปที่ {out.resolve()}")


if __name__ == "__main__":
    main()
