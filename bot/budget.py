"""แปลงข้อความงบประมาณภาษาไทยให้เป็นตัวเลข (ทำงานแบบกฎตายตัว ไม่ใช้ AI เดา)

ตัวอย่างที่รองรับ: "งบ 20000", "20,000", "20k", "2 หมื่น", "สองหมื่นห้า", "หมื่นห้า",
"2.5 หมื่น", "ไม่เกิน 18000", "15-20k", "ระหว่าง 15000 ถึง 20000", "2-3 หมื่น",
"3 หมื่นขึ้นไป", "ถูกที่สุด", "ไม่จำกัดงบ"
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

MIN_BUDGET = 3_000
MAX_BUDGET = 500_000

THAI_DIGIT_TRANS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
WORD_NUM = {
    "หนึ่ง": 1, "เอ็ด": 1, "นึง": 1, "สอง": 2, "สาม": 3, "สี่": 4, "ห้า": 5,
    "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9,
}
UNIT_VAL = {"แสน": 100_000, "หมื่น": 10_000, "พัน": 1_000}

_NUMW = r"(?:\d+(?:\.\d+)?|หนึ่ง|เอ็ด|นึง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)"
_DIGIT1 = r"(?:[1-9](?![\d.])|หนึ่ง|นึง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)"
_UNIT = r"(?:แสน|หมื่น|พัน)"
# เช่น "สองหมื่นห้าพัน", "2 หมื่น 5", "หมื่นห้า", "แสนนึง"
_THAI_AMOUNT = re.compile(
    rf"(?:{_NUMW}\s*)?{_UNIT}(?:\s*(?:{_NUMW}\s*)?{_UNIT})*(?:\s*{_DIGIT1}(?!\s*{_UNIT}))?"
)
_RANGE_SHORT = re.compile(
    r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(k|เค|หมื่น|พัน|แสน)(?![a-z])"
)
# "2.5k / 4k" มักหมายถึงความละเอียดจอ จึงนับเป็นงบเฉพาะตัวเลขตั้งแต่ 5k ขึ้นไป
_K_AMOUNT = re.compile(r"(?<![\d.])((?:[5-9]|\d{2,3})(?:\.\d+)?)\s*(?:k|เค)(?![a-z])")
# เบอร์โทร/เลขบัตร (มีขอบเขตตัวเลข จะได้ไม่ไปตัดเลขงบอย่าง "100000-200000" ทิ้ง)
_PERSONAL = re.compile(r"(?<!\d)0\d{1,2}[- ]?\d{3}[- ]?\d{3,4}(?!\d)|\d{13}|\d-\d{4}-\d{5}-\d{2}-\d")
# ตัวเลขที่เป็นสเปก ไม่ใช่งบ เช่น RTX 4050, 16GB, 144Hz, i5-1334U, รหัสรุ่น
_SPEC_PATTERNS = [
    r"(?:rtx|gtx|rx|mx|arc|radeon|ryzen(?:\s*ai)?(?:\s*max\+?)?|core(?:\s*ultra)?|ultra|snapdragon|i[3579]|x[1-9]|n)\s*-?\s*\d+[a-z0-9]*",
    r"\d+(?:\.\d+)?\s*(?:gb|tb|hz|mhz|ghz|mah|wh|kg|กก|กิโล|นิ้ว|inch|\"|nits|%|ชั่วโมง|ชม|ปี|เดือน|วัน|รุ่น|เครื่อง|คน|ตัว)",
    r"nb\s*-?\s*\d+",
    r"[a-z]+\d+[a-z0-9-]*",
    r"\d+[a-z]+[a-z0-9-]*",
]
_PLAIN = re.compile(r"(?<![\d<.])(\d{4,6})(?![\d>.])")
_TOKEN = re.compile(r"<(\d+)>")

_MAX_WORDS = r"(ไม่เกิน|ไม่ถึง|ต่ำกว่า|น้อยกว่า|ภายใน|ไม่เกินกว่า|สูงสุด|max)"
_MIN_BEFORE = r"(ตั้งแต่|มากกว่า|อย่างน้อย|เกินกว่า|min)"
_MIN_AFTER = r"(ขึ้นไป|up|\+)"
_APPROX = r"(ประมาณ|ราวๆ|ราว ๆ|ราว|แถวๆ|แถว ๆ|เกือบ|±)"
_CHEAPEST = r"(ถูกที่สุด|ถูกสุด|ราคาถูกที่สุด|ราคาประหยัด|ประหยัดสุด|งบน้อย|งบจำกัด|งบไม่เยอะ|งบไม่มาก)"
_UNLIMITED = r"(ไม่จำกัดงบ|งบไม่จำกัด|งบเท่าไหร่ก็ได้|ไม่มีงบ|ไม่สนราคา)"


@dataclass
class Budget:
    min: Optional[int] = None
    max: Optional[int] = None
    cheapest: bool = False
    unlimited: bool = False
    approx: bool = False

    def contains(self, price: int) -> bool:
        return (self.min is None or price >= self.min) and (self.max is None or price <= self.max)

    def label(self) -> str:
        if self.unlimited:
            return "ไม่จำกัดงบ"
        if self.min is not None and self.max is not None:
            return f"งบ {self.min:,}–{self.max:,} บาท"
        if self.max is not None:
            return f"งบไม่เกิน {self.max:,} บาท"
        if self.min is not None:
            return f"งบ {self.min:,} บาทขึ้นไป"
        if self.cheapest:
            return "เน้นรุ่นราคาถูกที่สุด"
        return "ยังไม่ระบุงบ"


def normalize(text: str) -> str:
    t = text.translate(THAI_DIGIT_TRANS).lower()
    t = re.sub(r"[​-‍﻿]", "", t)
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
    t = t.replace("–", "-").replace("—", "-").replace("~", "-")
    return re.sub(r"\s+", " ", t).strip()


def _thai_amount_value(expr: str) -> Optional[int]:
    total = 0.0
    last_unit = None
    for m in re.finditer(rf"({_NUMW})?\s*({_UNIT})|({_NUMW})", expr):
        num_s, unit_s, tail_s = m.group(1), m.group(2), m.group(3)
        if unit_s:
            n = _num(num_s) if num_s else 1
            last_unit = UNIT_VAL[unit_s]
            total += n * last_unit
        elif tail_s and last_unit:
            total += _num(tail_s) * (last_unit / 10)
    return int(round(total)) if total else None


def _num(s: str) -> float:
    return float(WORD_NUM[s]) if s in WORD_NUM else float(s)


def _tokenize_amounts(t: str) -> str:
    """แทนที่จำนวนเงินทุกแบบด้วยโทเคน <ตัวเลข> เพื่อให้หาเงื่อนไขช่วง/สูงสุดได้ง่าย"""
    def range_short(m):
        mult = 1000 if m.group(3) in ("k", "เค") else UNIT_VAL[m.group(3)]
        return f" <{int(float(m.group(1)) * mult)}>-<{int(float(m.group(2)) * mult)}> "

    t = _PERSONAL.sub(" ", t)
    t = _RANGE_SHORT.sub(range_short, t)
    t = _K_AMOUNT.sub(lambda m: f" <{int(float(m.group(1)) * 1000)}> ", t)

    def thai(m):
        if re.fullmatch(r"\s*(แสน|พัน)\s*", m.group(0)):  # เช่น "แสนดี" ไม่ใช่จำนวนเงิน
            return m.group(0)
        v = _thai_amount_value(m.group(0))
        return f" <{v}> " if v else m.group(0)

    t = _THAI_AMOUNT.sub(thai, t)
    for p in _SPEC_PATTERNS:
        t = re.sub(p, " ", t)

    def plain(m):
        v = int(m.group(1))
        return f" <{v}> " if MIN_BUDGET <= v <= MAX_BUDGET else m.group(0)

    t = _PLAIN.sub(plain, t)
    return re.sub(r"\s+", " ", t)


def parse_budget(text: str) -> Optional[Budget]:
    t = normalize(text)
    if re.search(_UNLIMITED, t):
        return Budget(unlimited=True)
    cheapest = bool(re.search(_CHEAPEST, t))
    tok = _tokenize_amounts(t)
    vals = [(int(m.group(1)), m.start(), m.end()) for m in _TOKEN.finditer(tok)]
    vals = [v for v in vals if MIN_BUDGET <= v[0] <= MAX_BUDGET]
    if not vals:
        return Budget(cheapest=True) if cheapest else None

    # ช่วงราคา: <a> - <b>, <a> ถึง <b>, ระหว่าง <a> กับ <b>
    for (a, _, a_end), (b, b_start, _) in zip(vals, vals[1:]):
        between = tok[a_end:b_start]
        if re.fullmatch(r"\s*(-|ถึง|to|กับ|และ|ถึงไม่เกิน|-ไม่เกิน)\s*(บาท\s*)?", between) or \
                re.fullmatch(r"\s*บาท\s*(-|ถึง|to)\s*", between):
            lo, hi = sorted((a, b))
            return Budget(min=lo, max=hi, cheapest=cheapest)

    v, start, end = vals[0]
    before = tok[max(0, start - 25):start]
    after = tok[end:end + 15]
    approx = bool(re.search(_APPROX, before))
    if re.search(_MAX_WORDS, before[-20:]):
        return Budget(max=v, cheapest=cheapest, approx=approx)
    if re.match(r"\s*(บาท)?\s*" + _MIN_AFTER, after) or re.search(_MIN_BEFORE + r"\s*(งบ)?\s*$", before):
        return Budget(min=v, cheapest=cheapest)
    return Budget(max=v, cheapest=cheapest, approx=approx)
