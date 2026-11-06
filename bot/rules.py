"""เกณฑ์ของร้านในการจับคู่ "การใช้งาน" กับ "สเปก" — ทีมแก้ไขค่าตรงนี้ได้ที่เดียว

ทุกเกณฑ์ใช้เฉพาะข้อมูลที่มีใน products.csv เท่านั้น และต้องเขียนอธิบายไว้ในรายงานด้วย
"""
from __future__ import annotations

import math
import re

USE_ORDER = ["study", "programming", "gaming", "creative"]

USE_CASES = {
    "study": {
        "label": "เรียน/ทำงานเอกสาร",
        "min_ram": 8,
        "min_storage": 256,
        "need_dgpu": False,
        "need_display_or_dgpu": False,
    },
    "programming": {
        "label": "เขียนโปรแกรม",
        "min_ram": 16,
        "min_storage": 512,
        "need_dgpu": False,
        "need_display_or_dgpu": False,
    },
    "gaming": {
        "label": "เล่นเกม",
        "min_ram": 16,
        "min_storage": 0,
        "need_dgpu": True,
        "need_display_or_dgpu": False,
    },
    "creative": {
        "label": "ตัดต่อ/กราฟิก",
        "min_ram": 16,
        "min_storage": 512,
        "need_dgpu": False,
        # ต้องมีการ์ดจอแยก หรือ จอ OLED หรือจอที่ระบุขอบเขตสี 100% (DCI-P3/sRGB)
        "need_display_or_dgpu": True,
    },
}

# ถ้าลูกค้าบอกหลายการใช้งาน ใช้เกณฑ์ของงานที่ต้องการสเปกสูงสุด
DEMAND_PRIORITY = ["gaming", "creative", "programming", "study"]


def cpu_tier(cpu: str) -> int:
    c = cpu.lower()
    if re.search(r"\bn\d{3}\b|core 3 n\d+", c):
        return 1
    if re.search(r"ryzen (ai )?max|ultra x?9|\bi9\b|ryzen (ai )?9|core 9", c):
        return 5
    if re.search(r"ultra x?7|\bi7\b|ryzen (ai )?7|core 7", c):
        return 4
    if re.search(r"ultra 5|\bi5\b|ryzen (ai )?5|core 5|snapdragon", c):
        return 3
    return 2  # i3 / Ryzen 3 / Core 3


def gpu_tier(gpu: str, gpu_type: str) -> float:
    if gpu_type != "dedicated":
        return 0.0
    m = re.search(r"rtx\s*(\d{4})\s*(ti)?", gpu.lower())
    if not m:
        return 1.0
    table = {"3050": 1.0, "4050": 2.0, "5050": 2.5, "4060": 3.0, "5060": 3.0,
             "4070": 3.5, "5070": 4.0, "5080": 6.0, "5090": 7.0}
    tier = table.get(m.group(1), 2.0)
    return tier + (1.0 if m.group(2) else 0.0)


def has_color_display(p) -> bool:
    return "oled" in p.panel.lower() or bool(re.search(r"(dci-p3|srgb) 100%", p.notes.lower()))


def is_high_res(p) -> bool:
    r = p.resolution.lower()
    if re.search(r"2\.5k|2\.8k|3k|3\.2k|4k|wqxga|qhd|uhd", r):
        return True
    m = re.search(r"(\d{4})x(\d{3,4})", r)
    return bool(m and int(m.group(1)) >= 2560)


def check(p, use: str) -> tuple[bool, list[str]]:
    """คืนค่า (ผ่านเกณฑ์ไหม, เหตุผลที่ไม่ผ่าน)"""
    rule = USE_CASES[use]
    fails = []
    if p.ram_gb < rule["min_ram"]:
        fails.append(f"RAM {p.ram_gb}GB (เกณฑ์ร้าน {rule['min_ram']}GB ขึ้นไป)")
    if p.storage_gb < rule["min_storage"]:
        fails.append(f"SSD {p.storage_label} (เกณฑ์ร้าน {rule['min_storage']}GB ขึ้นไป)")
    if rule["need_dgpu"] and p.gpu_type != "dedicated":
        fails.append("ไม่มีการ์ดจอแยก")
    if rule["need_display_or_dgpu"] and p.gpu_type != "dedicated" and not has_color_display(p):
        fails.append("ไม่มีการ์ดจอแยก และจอไม่ใช่ OLED/ไม่ได้ระบุขอบเขตสี 100%")
    return (not fails, fails)


def score(p, use: str) -> float:
    ram_pts = 1 + math.log2(max(p.ram_gb, 4) / 8)
    sto_pts = 0.5 * math.log2(max(p.storage_gb, 128) / 128)
    cpu = cpu_tier(p.cpu)
    gpu = gpu_tier(p.gpu, p.gpu_type)
    hz = p.refresh_hz or 0
    if use == "study":
        return cpu + ram_pts + sto_pts + (0.5 if p.office_included == "yes" else 0)
    if use == "programming":
        return cpu * 1.5 + ram_pts * 1.5 + sto_pts + (0.3 if p.screen_inch >= 14 else 0)
    if use == "gaming":
        return gpu * 3 + cpu + ram_pts + (0.5 if hz >= 120 else 0) + (0.5 if hz >= 165 else 0)
    # creative
    return (cpu + ram_pts * 1.5 + sto_pts + gpu * 1.5
            + (1.5 if "oled" in p.panel.lower() else 0)
            + (1.0 if re.search(r"(dci-p3|srgb) 100%", p.notes.lower()) else 0)
            + (0.5 if is_high_res(p) else 0))


def highlights(p, use: str) -> list[str]:
    """จุดเด่นที่เกี่ยวกับการใช้งาน (ทุกข้อมาจากข้อมูลสินค้า)"""
    out = []
    if use == "gaming":
        out.append(f"การ์ดจอแยก {p.gpu}")
        if p.refresh_hz and p.refresh_hz >= 120:
            out.append(f"จอ {p.refresh_hz}Hz")
        out.append(f"RAM {p.ram_gb}GB")
    elif use == "creative":
        if has_color_display(p):
            extra = []
            if re.search(r"(dci-p3|srgb) 100%", p.notes.lower()):
                extra.append(re.search(r"(dci-p3|srgb) 100%", p.notes, re.I).group(0))
            out.append(f"จอ {p.panel or ''} {p.resolution}".replace("  ", " ").strip()
                       + (f" ({', '.join(extra)})" if extra else ""))
        if p.gpu_type == "dedicated":
            out.append(f"การ์ดจอแยก {p.gpu}")
        out.append(f"RAM {p.ram_gb}GB · SSD {p.storage_label}")
    elif use == "programming":
        out.append(f"RAM {p.ram_gb}GB · SSD {p.storage_label}")
        out.append(f"CPU {p.cpu}")
    else:  # study
        out.append(f"RAM {p.ram_gb}GB · SSD {p.storage_label}")
        if p.office_included == "yes":
            out.append("มี Office Home 2024 ในเครื่อง (ตามข้อมูลสินค้า)")
    return out[:3]


def caveats(p, use: str) -> list[str]:
    """ข้อสังเกตจากข้อมูลจริง (ไม่เกิน 2 ข้อ)"""
    out = []
    for other in ("programming", "gaming"):
        if other != use:
            ok, fails = check(p, other)
            if not ok and other == "gaming" and use in ("study", "programming"):
                out.append("ไม่ผ่านเกณฑ์เล่นเกมของร้าน (" + ", ".join(fails) + ")")
                break
    if p.storage_gb < 512 and use != "study":
        out.append(f"SSD {p.storage_label}")
    elif p.storage_gb < 512:
        out.append(f"SSD {p.storage_label} (พื้นที่น้อยกว่ารุ่น 512GB)")
    if not p.refresh_hz and use in ("gaming", "creative"):
        out.append("ไม่มีข้อมูลรีเฟรชเรตของจอ")
    if p.office_included == "no" and use == "study":
        out.append("ไม่มี Office ในรายการสินค้า")
    return out[:2]
