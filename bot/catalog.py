"""โหลดข้อมูลสินค้าจาก products.csv และค้นหาสินค้า — ข้อมูลทุกตัวที่บอทตอบมาจากที่นี่"""
from __future__ import annotations

import csv
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import rules

BRANDS_TH = {
    "เอซุส": "ASUS", "อัสซุส": "ASUS", "อซุส": "ASUS", "เลอโนโว": "LENOVO", "เลโนโว": "LENOVO",
    "เอเซอร์": "ACER", "เอเซอ": "ACER", "เดล": "DELL", "เดลล์": "DELL", "เอชพี": "HP",
    "เอ็มเอสไอ": "MSI", "กิกะไบต์": "GIGABYTE", "กิกะไบท์": "GIGABYTE",
}

# คำทั่วไปที่ไม่ใช้ระบุรุ่น
STOP_TOKENS = {
    "gb", "tb", "hz", "ram", "ssd", "cpu", "gpu", "intel", "amd", "ai", "oled", "ips", "fhd",
    "wuxga", "office", "windows", "win", "notebook", "laptop", "nb", "the", "and", "vs", "or",
    "k", "ddr4", "ddr5", "rtx", "gtx", "core", "ryzen", "ultra", "i3", "i5", "i7", "i9",
    "gaming", "game", "เกม", "spec", "price", "pc", "gray", "grey", "black", "silver", "blue",
    "white", "green", "luna", "inch", "max", "min", "plus", "lite", "go", "air", "pro", "s", "x",
    "thin", "edge", "flip", "duo", "ai+", "เกมมิ่ง",
}


@dataclass
class Product:
    id: str
    brand: str
    model: str
    price: int
    promo: Optional[int]
    cpu: str
    ram_gb: int
    ram_detail: str
    storage_gb: int
    storage_type: str
    gpu: str
    gpu_type: str
    screen_inch: float
    resolution: str
    refresh_hz: Optional[int]
    panel: str
    os: str
    office_included: str
    notes: str
    weight_kg: str
    battery_wh: str
    warranty_years: str
    stock_status: str
    source_url: str
    collected_at: str
    passes: dict = field(default_factory=dict)
    fails: dict = field(default_factory=dict)
    tokens: list = field(default_factory=list)
    seq: list = field(default_factory=list)  # คำในชื่อรุ่นตามลำดับ (ไม่รวมสี) ใช้จับคู่ชื่อซีรีส์

    @property
    def name(self) -> str:
        return f"{self.brand} {self.model}"

    @property
    def eff_price(self) -> int:
        return self.promo if self.promo else self.price

    @property
    def storage_label(self) -> str:
        if self.storage_gb >= 1024 and self.storage_gb % 1024 == 0:
            return f"{self.storage_gb // 1024}TB"
        return f"{self.storage_gb}GB"

    @property
    def screen_label(self) -> str:
        size = f"{self.screen_inch:g}\""
        parts = [size, self.resolution]
        if self.refresh_hz:
            parts.append(f"{self.refresh_hz}Hz")
        if self.panel:
            parts.append(self.panel)
        return " ".join(p for p in parts if p)

    @property
    def series_key(self) -> str:
        return " ".join(re.split(r"[\s-]+", self.model)[:3])

    def suitable_labels(self) -> list[str]:
        return [rules.USE_CASES[u]["label"] for u in rules.USE_ORDER if self.passes.get(u)]

    def spec_lines(self) -> list[str]:
        return [
            f"CPU: {self.cpu}",
            f"RAM: {self.ram_gb}GB · SSD {self.storage_label}",
            f"การ์ดจอ: {self.gpu}" + (" (การ์ดจอแยก)" if self.gpu_type == "dedicated" else " (ในตัว)"),
            f"จอ: {self.screen_label}",
        ]

    def spec_summary(self) -> str:
        return " | ".join([self.cpu, f"RAM {self.ram_gb}GB", f"SSD {self.storage_label}",
                           self.gpu, f"จอ {self.screen_label}"])


def _int(v: str) -> Optional[int]:
    v = (v or "").strip()
    return int(float(v)) if v else None


class Catalog:
    def __init__(self, products: list[Product]):
        self.products = products
        self.by_id = {p.id: p for p in products}
        self.brands = sorted({p.brand for p in products})
        df = Counter()
        for p in products:
            p.tokens = _model_tokens(p)
            p.seq = _seq_tokens(f"{p.brand} {p.model.split(' - ')[0]}")
            df.update(set(p.tokens))
        n = len(products)
        self.idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}
        self.df = df
        for p in products:
            for u in rules.USE_ORDER:
                ok, fails = rules.check(p, u)
                p.passes[u] = ok
                p.fails[u] = fails

    @classmethod
    def from_csv(cls, path: str | Path) -> "Catalog":
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        products = []
        for r in rows:
            products.append(Product(
                id=r["product_id"].strip(), brand=r["brand"].strip(), model=r["model"].strip(),
                price=int(r["price_thb"]), promo=_int(r.get("promo_price_thb")),
                cpu=r["cpu"].strip(), ram_gb=int(r["ram_gb"]), ram_detail=r.get("ram_detail", "").strip(),
                storage_gb=int(r["storage_gb"]), storage_type=r.get("storage_type", "SSD").strip(),
                gpu=r["gpu"].strip(), gpu_type=r["gpu_type"].strip().lower(),
                screen_inch=float(r["screen_inch"]), resolution=r.get("resolution", "").strip(),
                refresh_hz=_int(r.get("refresh_hz")), panel=r.get("panel", "").strip(),
                os=r.get("os", "").strip(), office_included=r.get("office_included", "").strip().lower(),
                notes=r.get("notes", "").strip(), weight_kg=r.get("weight_kg", "").strip(),
                battery_wh=r.get("battery_wh", "").strip(), warranty_years=r.get("warranty_years", "").strip(),
                stock_status=r.get("stock_status", "").strip(), source_url=r.get("source_url", "").strip(),
                collected_at=r.get("collected_at", "").strip(),
            ))
        return cls(products)

    @property
    def data_date(self) -> str:
        dates = {p.collected_at for p in self.products if p.collected_at}
        return max(dates) if dates else ""

    def get(self, pid: str) -> Optional[Product]:
        return self.by_id.get(pid.upper())

    def find_series(self, text: str, min_run: int = 2) -> list[Product]:
        """หาสินค้าจากชื่อซีรีส์ที่พิมพ์เรียงคำ เช่น "lenovo ideapad slim 5" หรือ "msi modern 16s"

        ให้คะแนนจากจำนวนคำที่ตรงกับชื่อรุ่นแบบเรียงติดกัน จึงแยก SLIM 5 ออกจาก SLIM 3 ได้
        คืนทุกรุ่นย่อยที่ตรงที่สุด เรียงจากราคาถูกไปแพง
        """
        q = _seq_tokens(_thai_brands_to_en(text))
        if len(q) < min_run:
            return []
        scored = [(_longest_run(q, p.seq), p) for p in self.products]
        best = max((r for r, _ in scored), default=0)
        if best < min_run:
            return []
        return sorted((p for r, p in scored if r == best), key=lambda p: (p.eff_price, p.id))

    def search(self, text: str, limit: int = 6) -> list[Product]:
        """ค้นหารุ่นจากชื่อ/รหัสรุ่นที่ลูกค้าพิมพ์ คืนค่ารายการที่ตรงที่สุด"""
        series = self.find_series(text)
        if series:
            return series[:limit]
        q = _query_tokens(text)
        if not q:
            return []
        scored = []
        for p in self.products:
            s, distinctive = 0.0, False
            ptoks = set(p.tokens)
            for t in q:
                hit = t in ptoks or (len(t) >= 5 and any(pt.startswith(t) for pt in ptoks))
                if hit:
                    s += self.idf.get(t, 1.0) if t in ptoks else 2.0
                    if t.lower() != p.brand.lower() and (self.df.get(t, 1) <= 20 or len(t) >= 5):
                        distinctive = True
            if s > 0 and distinctive:
                scored.append((s, p))
        if not scored:
            return []
        scored.sort(key=lambda x: (-x[0], x[1].eff_price))
        best = scored[0][0]
        return [p for s, p in scored if s >= best * 0.85][:limit]

    def unknown_model_token(self, text: str) -> Optional[str]:
        """คืนคำที่ดูเหมือนชื่อรุ่นแต่ไม่พบในข้อมูลร้าน"""
        all_tokens = set(self.df)
        for t in _query_tokens(text):
            if len(t) >= 3 and re.search(r"[a-z]", t) and t not in all_tokens \
                    and not any(pt.startswith(t) for pt in all_tokens):
                return t
        return None


def _thai_brands_to_en(text: str) -> str:
    t = text.lower()
    for th, en in BRANDS_TH.items():
        t = t.replace(th, f" {en.lower()} ")
    return t


def _seq_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+]+", text.lower())


def _tok_eq(q: str, p: str) -> bool:
    return q == p or (len(q) >= 4 and p.startswith(q))


def _longest_run(q: list[str], s: list[str]) -> int:
    """ความยาวช่วงคำที่ตรงกันติดต่อกันยาวที่สุดระหว่างคำค้นกับชื่อรุ่น"""
    best = 0
    for i in range(len(q)):
        for j in range(len(s)):
            k = 0
            while i + k < len(q) and j + k < len(s) and _tok_eq(q[i + k], s[j + k]):
                k += 1
            best = max(best, k)
    return best


def _model_tokens(p: Product) -> list[str]:
    toks = re.findall(r"[a-z0-9+]+", f"{p.brand} {p.model}".lower())
    return [t for t in toks if t]


def _query_tokens(text: str) -> list[str]:
    t = text.lower()
    for th, en in BRANDS_TH.items():
        t = t.replace(th, f" {en.lower()} ")
    toks = re.findall(r"[a-z0-9+]+", t)
    toks = [x for x in toks if x not in STOP_TOKENS and not re.fullmatch(r"\d{1,2}|\d{4,7}", x)]
    # รวมคำติดกัน เช่น "legion 5" -> "legion5"
    words = re.findall(r"[a-z0-9+]+", t)
    for a, b in zip(words, words[1:]):
        if re.fullmatch(r"[a-z]+", a) and re.fullmatch(r"\d{1,2}", b):
            toks.append(a + b)
    return toks
