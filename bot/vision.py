"""ตรวจว่ารูปที่ลูกค้าส่งมา "เกี่ยวกับโน้ตบุ๊ก" หรือไม่ ด้วยโมเดล CLIP แบบ zero-shot (ฟรี รันในเครื่อง)

วิธีวัด:
1. เทียบรูปกับประโยคอธิบายภาพ (prompt) หลายประโยคใน PROMPTS ทั้งกลุ่ม "เกี่ยวข้อง" และ "ไม่เกี่ยวข้อง"
2. CLIP ให้ความน่าจะเป็นของแต่ละประโยค (softmax รวมกันได้ 1)
3. คะแนนความเกี่ยวข้อง = ผลรวมความน่าจะเป็นของประโยคกลุ่ม "เกี่ยวข้อง" (0–1)
4. ตัดสิน: >= RELEVANT_AT = เกี่ยวข้อง, >= UNCERTAIN_AT = ไม่แน่ใจ, ต่ำกว่านั้น = ไม่เกี่ยวข้อง

ตัววิเคราะห์รูปให้แค่คะแนนและประเภทภาพเท่านั้น ไม่ได้อ่านชื่อรุ่นหรือราคา
คำตอบเรื่องสินค้ายังมาจาก products.csv เสมอ (ขอบเขต 1.1.1) และรูปไม่ถูกบันทึกลงเครื่อง
"""
from __future__ import annotations

import importlib.util
import io
import threading
import warnings

MODEL_NAME = "openai/clip-vit-base-patch32"
RELEVANT_AT = 0.60   # ปรับได้หลังวัดผลด้วย tools/eval_images.py
UNCERTAIN_AT = 0.35
PERSONAL_DOC_FLAG_AT = 0.25

MAX_BYTES = 5 * 1024 * 1024        # 5 MB
MAX_PIXELS = 40_000_000            # กันไฟล์รูปที่ขยายแล้วใหญ่ผิดปกติ
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}

# (ประโยคภาษาอังกฤษสำหรับ CLIP, กลุ่ม, ประเภท) — CLIP เข้าใจภาษาอังกฤษดีที่สุด
PROMPTS = [
    ("a photo of a laptop computer", "relevant", "laptop"),
    ("a photo of an open laptop on a desk", "relevant", "laptop"),
    ("a photo of a closed laptop", "relevant", "laptop"),
    ("a close-up photo of a laptop keyboard and touchpad", "relevant", "laptop"),
    ("a photo of a gaming laptop with a colorful backlit keyboard", "relevant", "gaming"),
    ("a photo of a laptop box or packaging", "relevant", "box"),
    ("a photo of a specification sticker on a laptop", "relevant", "box"),
    ("a screenshot of a laptop product page with a price", "relevant", "screenshot"),
    ("a screenshot of laptop specifications", "relevant", "screenshot"),
    ("a photo of a laptop screen showing an error message", "relevant", "problem"),
    ("a photo of a broken or damaged laptop", "relevant", "problem"),
    ("a photo of a smartphone", "irrelevant", "phone"),
    ("a photo of a tablet", "irrelevant", "tablet"),
    ("a photo of a desktop computer tower", "irrelevant", "desktop"),
    ("a photo of a computer monitor", "irrelevant", "monitor"),
    ("a photo of a television", "irrelevant", "other"),
    ("a photo of food", "irrelevant", "other"),
    ("a photo of an animal", "irrelevant", "other"),
    ("a photo of a person", "irrelevant", "person"),
    ("a selfie", "irrelevant", "person"),
    ("a photo of a landscape or a building", "irrelevant", "other"),
    ("a photo of a car", "irrelevant", "other"),
    ("a photo of clothes or shoes", "irrelevant", "other"),
    ("a screenshot of a chat conversation", "irrelevant", "other"),
    ("a meme or a cartoon", "irrelevant", "other"),
    ("a photo of an ID card or a personal document", "irrelevant", "personal_doc"),
]


class ImageError(ValueError):
    """รูปใช้ไม่ได้ ข้อความเป็นภาษาไทยสำหรับแสดงให้ลูกค้า"""


class VisionUnavailable(RuntimeError):
    """ยังไม่ได้ติดตั้งไลบรารีหรือโหลดโมเดลไม่ได้"""


def load_image(data: bytes):
    """ตรวจไฟล์รูปอย่างปลอดภัย แล้วคืนค่าเป็นภาพ RGB ย่อขนาดแล้ว (ไม่บันทึกลงดิสก์)"""
    from PIL import Image, ImageOps

    if not data:
        raise ImageError("ไม่พบไฟล์รูปครับ")
    if len(data) > MAX_BYTES:
        raise ImageError("รูปใหญ่เกินไปครับ รองรับไฟล์ไม่เกิน 5 MB")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)  # ตรวจขนาดเองด้านล่าง
            probe = Image.open(io.BytesIO(data))
        with probe:
            fmt = probe.format
            w, h = probe.size
            if w * h > MAX_PIXELS:
                raise ImageError("รูปมีความละเอียดสูงเกินไปครับ ลองย่อรูปแล้วส่งใหม่")
            if fmt not in ALLOWED_FORMATS:
                raise ImageError("รองรับเฉพาะรูป JPG, PNG, WEBP หรือ GIF ครับ")
            probe.verify()
        img = Image.open(io.BytesIO(data))
        img.seek(0)  # GIF ใช้เฟรมแรก
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1024, 1024))
        return img
    except ImageError:
        raise
    except Exception:
        raise ImageError("ไฟล์นี้ไม่ใช่รูปภาพที่รองรับครับ (รองรับ JPG, PNG, WEBP, GIF)")


def verdict_for(score: float) -> str:
    if score >= RELEVANT_AT:
        return "relevant"
    if score >= UNCERTAIN_AT:
        return "uncertain"
    return "irrelevant"


def summarize(probs: list[float]) -> dict:
    """แปลงความน่าจะเป็นของแต่ละ prompt เป็นผลการตรวจ (ใช้ได้ทั้งโมเดลจริงและตัวทดสอบ)"""
    if len(probs) != len(PROMPTS):
        raise ValueError("จำนวนความน่าจะเป็นไม่ตรงกับ PROMPTS")
    score = sum(p for p, (_, g, _) in zip(probs, PROMPTS) if g == "relevant")
    verdict = verdict_for(score)
    top_i = max(range(len(probs)), key=probs.__getitem__)
    best_rel = max(((p, k) for p, (_, g, k) in zip(probs, PROMPTS) if g == "relevant"))
    kind = best_rel[1] if verdict != "irrelevant" else PROMPTS[top_i][2]
    doc_p = sum(p for p, (_, _, k) in zip(probs, PROMPTS) if k == "personal_doc")
    flags = ["personal_doc"] if doc_p >= PERSONAL_DOC_FLAG_AT or PROMPTS[top_i][2] == "personal_doc" else []
    return {
        "score": round(score, 4),
        "verdict": verdict,
        "kind": kind,
        "flags": flags,
        "top_prompt": PROMPTS[top_i][0],
        "top_prob": round(probs[top_i], 4),
    }


class ClipRelevance:
    """โหลดโมเดลครั้งแรกที่มีรูปเข้ามา (ครั้งแรกจะช้าเพราะต้องดาวน์โหลด ~600 MB)"""

    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self._model = None
        self._processor = None
        self._lock = threading.Lock()

    @staticmethod
    def libraries_available() -> bool:
        return all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers"))

    def _load(self):
        if self._model is not None:
            return
        if not self.libraries_available():
            raise VisionUnavailable("ยังไม่ได้ติดตั้ง torch และ transformers (ดู README หัวข้อส่งรูป)")
        try:
            from transformers import CLIPModel, CLIPProcessor
            self._processor = CLIPProcessor.from_pretrained(self.model_name)
            self._model = CLIPModel.from_pretrained(self.model_name).eval()
        except Exception as e:  # เช่น ออฟไลน์ตอนดาวน์โหลดครั้งแรก
            raise VisionUnavailable(f"โหลดโมเดล {self.model_name} ไม่ได้: {e}") from e

    def warmup(self):
        with self._lock:
            self._load()

    def probabilities(self, image) -> list[float]:
        with self._lock:
            self._load()
            import torch
            inputs = self._processor(text=[p[0] for p in PROMPTS], images=image,
                                     return_tensors="pt", padding=True)
            with torch.no_grad():
                logits = self._model(**inputs).logits_per_image[0]
            return logits.softmax(dim=-1).tolist()

    def analyze(self, image) -> dict:
        return summarize(self.probabilities(image))
