"""ตรวจเจตนาของข้อความลูกค้าด้วยกฎ (คีย์เวิร์ด/regex) — ไม่ใช้ AI จึงคาดเดาผลได้และทดสอบได้"""
from __future__ import annotations

import re
from typing import Optional

from .budget import normalize

# ---------- ความปลอดภัย (ขอบเขต 1.1.3) ----------
INJECTION = re.compile(
    r"(system ?prompt|prompt|instruction|ignore (all|previous|the|your)|forget (all|previous|your)|"
    r"jailbreak|\bdan\b|developer mode|act as|roleplay|สวมบทบาท|เปลี่ยนบทบาท|"
    r"ลืม(คำสั่ง|กฎ|ทุกอย่าง)|ไม่ต้อง(สนใจ|ทำตาม)(กฎ|คำสั่ง)|ยกเลิกกฎ|ข้ามกฎ|"
    r"คำสั่ง(ก่อนหน้า|ระบบ|ที่ตั้งไว้|ลับ)|ตั้งค่าระบบ|การตั้งค่าของ(คุณ|บอท)|"
    r"โหมด\s*(แอดมิน|admin|ผู้ดูแล|นักพัฒนา|ทดสอบ|dev|debug|พิเศษ|god)|"
    r"(อนุมัติ|สั่งให้|คำสั่งจาก)\s*(ผู้จัดการ|เจ้าของ|แอดมิน)|"
    r"(ตั้ง|แก้)ราคา|(เปลี่ยน|ปรับ)ราคา\S{0,6}(ให้|เป็น|เหลือ)|(set|change|update)\b.{0,25}\bprices?\b|"
    r"คำสั่งที่(คุณ|บอท)?ได้รับ|กฎ(ของคุณ|ของบอท|ที่ได้รับ|ที่ตั้งไว้)|บอกกฎ|ถูกตั้งค่า(ไว้)?ยังไง)",
    re.I,
)
# อ้างตัวเป็นผู้มีอำนาจ (ไม่มีผลใด ๆ กับสิทธิ์ในแชท)
AUTHORITY = re.compile(
    r"(ผม|ฉัน|เรา|นี่|กู|หนู|ดิฉัน|ข้าพเจ้า)\s*(เป็น|คือ)\s*(ผู้จัดการ|เจ้าของร้าน|แอดมิน|admin|ผู้ดูแลระบบ|"
    r"ผู้พัฒนา(บอท|ระบบ)?|developer|พนักงาน(ของ)?ร้าน|ทีมงาน(ของ)?ร้าน|หัวหน้า(ร้าน|สาขา))|"
    r"(ผู้จัดการ|เจ้าของร้าน|แอดมิน)(สั่ง|อนุญาต|อนุมัติ)",
    re.I,
)
PRIVILEGE_ASK = re.compile(r"(อนุมัติ|ลด|ส่วนลด|ข้อมูล|โหมด|ตั้งค่า|คำสั่ง|สิทธิ์|ฟรี|แก้ราคา|เปลี่ยนราคา|ราคาพิเศษ|เปิดเผย|ปลดล็อก)")
OTHER_PERSON = re.compile(r"(เพื่อน|แฟน|คนอื่น|ลูกค้า|ใคร|ญาติ|เขา|เค้า|คนที่ชื่อ|ชื่อ\s*(?!รุ่น|สินค้า|ร้าน|บอท|เครื่อง)[ก-๙a-z]{2,})", re.I)
PERSON_DATA = re.compile(
    r"(เบอร์|ที่อยู่|อีเมล|email|ข้อมูลส่วนตัว|ข้อมูลลูกค้า|ข้อมูลการซื้อ|ข้อมูลของ(เขา|เค้า|เพื่อน|ลูกค้า)|ประวัติ|ออเดอร์|order|คำสั่งซื้อ|"
    r"ซื้อไปแล้ว|ซื้อแล้ว|ซื้ออะไร|ซื้อรุ่นอะไร|ซื้อรุ่นไหน|ซื้อเมื่อ|มาซื้อเมื่อ|ซื้อตัวไหน|สั่งอะไร|สั่งรุ่น)",
    re.I,
)
CUSTOMER_DATA = re.compile(r"(ข้อมูลลูกค้า|ข้อมูลการซื้อ|รายชื่อลูกค้า|ประวัติ(การซื้อ|ลูกค้า)|เบอร์ลูกค้า|ที่อยู่ลูกค้า|ลูกค้าคนอื่น|ลูกค้าท่านอื่น|ใครซื้อ|ใครสั่ง)")
ORDER = re.compile(r"(ออเดอร์|คำสั่งซื้อ|\border\b|เลขพัสดุ|tracking|สถานะ(การ)?สั่ง|ของถึง(ไหน|ยัง)|ส่งของแล้วยัง)", re.I)
PERSONAL_INFO = re.compile(r"(?<!\d)(0\d{1,2}[- ]?\d{3}[- ]?\d{3,4}|\d{13}|\d-\d{4}-\d{5}-\d{2}-\d)(?!\d)")

NEGOTIATE = re.compile(
    r"(ส่วนลด|ลดราคา|ลดได้|ลดให้|ขอลด|ลดหน่อย|ลดอีก|ลดเพิ่ม|ต่อราคา|ต่อรอง|ต่อได้|ลด\s*\d+|โค้ดส่วนลด|โค้ดลด|คูปอง|coupon|"
    r"discount|ของแถม|แถม(?!ยัง)|ราคาพิเศษ|แมตช์ราคา|price ?match|ถูกกว่าร้านอื่น|ร้านอื่นขาย|"
    r"ถูกกว่านี้ได้|ขายถูกกว่า|ราคาส่ง|ลดเหลือ|ขายเหลือ|ฟรีให้|ให้ฟรี|ไม่ลด|ซื้อร้านอื่น|ไปร้านอื่น|ซื้อที่อื่น|"
    r"ขาย\s*(ให้)?\s*\d[\d,]*\s*(บาท)?\s*(ได้|ไหม|มั้ย|ป่ะ|ปะ)|ขอราคา\s*\d)",
    re.I,
)
PROMO = re.compile(r"(โปรโมชั่น|โปรโมชัน|ราคาโปร|มีโปร|โปรอะไร|โปรไหม|โปรมั้ย|ติดโปร|โปรลด|promotion|\bsale\b|ลดราคาอยู่)", re.I)

# ---------- งานทั่วไป ----------
GREETING = re.compile(r"^(สวัสดี|หวัดดี|ดีจ้า|ดีครับ|ดีค่ะ|hello|hi\b|hey|เฮลโหล|ทักครับ|ทักค่ะ)", re.I)
THANKS = re.compile(r"(ขอบคุณ|ขอบใจ|thank|แต๊ง|ขอบคุน)", re.I)
RESET = re.compile(r"^(เริ่มใหม่|reset|ล้างแชท|เริ่มต้นใหม่|ล้างข้อมูล)", re.I)
HELP = re.compile(r"(ช่วยอะไรได้บ้าง|ทำอะไรได้บ้าง\s*$|ใช้ยังไง|วิธีใช้|help|เมนู)", re.I)
HANDOFF = re.compile(r"(คุยกับ\s*(พนักงาน|คน|แอดมิน|เจ้าหน้าที่|ผู้จัดการ)|ขอสาย|ติดต่อพนักงาน|ต้องการพนักงาน|ขอพนักงาน|คนจริง|"
                     r"เบอร์ร้าน|เบอร์โทรร้าน|ติดต่อร้าน|ช่องทางติดต่อ|ติดต่อยังไง|ติดต่อได้ที่ไหน|ไลน์ร้าน|line ร้าน|เพจร้าน)", re.I)
POLICY_MENU = re.compile(r"^(นโยบายร้าน|นโยบาย|ข้อมูลร้าน)$")
GENERIC_POLICY = re.compile(
    r"((ร้าน|ทางร้าน).{0,30}(บริการ|นโยบาย|รับ|ลงโปรแกรม|ลงวินโดว์|ติดตั้ง|ซ่อม|เทิร์น|แลก|เปลี่ยนเครื่อง).{0,30}(ไหม|มั้ย|หรือเปล่า|รึเปล่า|ได้ไหม|ได้มั้ย|\?)|"
    r"(นโยบาย|บริการ|สมาชิก|สะสมแต้ม|แต้ม|ติดฟิล์ม|ฟิล์มกันรอย|บริการหลังการขาย|ทดลองใช้|ทดลองเครื่อง|รับซื้อ).{0,25}(ไหม|มั้ย|ยังไง|อะไร|หรือเปล่า|รึเปล่า|\?|$))"
)

OTHER_STORE = re.compile(r"(ร้านอื่น|ที่อื่น|ร้านค้าอื่น|banana|บานาน่า|\bjib\b|เจไอบี|advice|แอดไวซ์|it ?city|ไอทีซิตี้|"
                         r"power ?buy|เพาเวอร์บาย|shopee|ช้อปปี้|lazada|ลาซาด้า|studio ?7)", re.I)
SALES = re.compile(r"(ขายดี|ยอดขาย|ยอดนิยม|คนซื้อเยอะ|best ?seller|ฮิตสุด|ฮิตที่สุด|นิยมที่สุด|คนนิยม)", re.I)
GUESS = re.compile(r"(เดา|มั่ว|ประมาณเอา|คร่าวๆก็ได้|คร่าว ๆ ก็ได้|ตอบไปก่อน)")
LAPTOP_CONTEXT = re.compile(r"(งบ|โน้ตบุ๊ก|โน๊ตบุ๊ค|โน้ตบุ๊ค|notebook|laptop|เครื่อง|รุ่น|สเปก|สเปค|\bnb\s*\d)", re.I)
OUT_OF_SCOPE = re.compile(
    r"(แต่ง(กลอน|เพลง|นิทาน)|แปลภาษา|แปล(ประโยค|ข้อความ)|"
    r"แก้โจทย์|คิดเลข|ดูดวง|พยากรณ์อากาศ|อากาศ(วันนี้|พรุ่งนี้)|ข่าว(วันนี้|ล่าสุด)|เล่าเรื่องตลก|สูตรอาหาร)", re.I)
# งานเขียน/การบ้าน นับเป็น "นอกขอบเขต" เฉพาะเมื่อเป็นการขอให้บอททำให้ เช่น "ช่วยเขียนโค้ดให้หน่อย"
# ส่วน "ใช้เขียนโปรแกรม" / "ไว้ทำการบ้าน" คือการบอกการใช้งานโน้ตบุ๊ก ไม่ใช่นอกขอบเขต
_WRITE_TASK = r"(?:เขียน\s*(?:โค้ด|โค๊ด|โปรแกรม|code|program|เรียงความ|รายงาน)|(?:ทำ)?การบ้าน)"
_USE_LEAD = re.compile(rf"(?:ใช้|เอาไว้|ไว้|สำหรับ|เพื่อ)\s*(?:ทำ\s*)?{_WRITE_TASK}", re.I)
TASK_REQUEST = re.compile(
    rf"(?:ช่วย|ขอ|อยากให้|รบกวน|สอน)\S{{0,6}}?\s*{_WRITE_TASK}"
    rf"|{_WRITE_TASK}.{{0,40}}?(?:ให้|หน่อย)"
    rf"|{_WRITE_TASK}\s*(?:ภาษา\s*)?(?:python|java|html|css|sql|c\+\+|c#|javascript|php)", re.I)


def out_of_scope(t: str) -> bool:
    """คำขอที่ไม่เกี่ยวกับร้าน (และไม่มีบริบทโน้ตบุ๊กในข้อความ)"""
    if LAPTOP_CONTEXT.search(t):
        return False
    return bool(OUT_OF_SCOPE.search(t) or TASK_REQUEST.search(_USE_LEAD.sub(" ", t)))

NOT_SOLD = {
    "macbook": "MacBook", "mac book": "MacBook", "แมคบุ๊ค": "MacBook", "แมค": "Mac", "imac": "iMac",
    "apple": "Apple", "แอปเปิ้ล": "Apple", "iphone": "iPhone", "ipad": "iPad", "ไอแพด": "iPad",
    "samsung": "Samsung", "galaxy book": "Samsung Galaxy Book", "huawei": "Huawei", "matebook": "Huawei MateBook",
    "surface": "Microsoft Surface", "razer": "Razer", "alienware": "Alienware", "lg gram": "LG gram",
    "xiaomi": "Xiaomi", "chromebook": "Chromebook", "thinkpad": "ThinkPad", "macbook neo": "MacBook Neo",
}

USE_KEYWORDS = {
    "gaming": r"(เล่นเกม|เกมมิ่ง|gaming|game|เกม|valorant|gta|pubg|steam|fps|esport|อีสปอร์ต|roblox|minecraft|genshin|dota|cs2|apex|fortnite)",
    "creative": r"(ตัดต่อ|กราฟิก|ออกแบบ|ดีไซน์|design|photoshop|premiere|lightroom|after ?effects|แต่งรูป|แต่งภาพ|ทำภาพ|ตัดต่อวิดีโอ|ทำวิดีโอ|edit video|video edit|render|เรนเดอร์|3d|สามมิติ|blender|ทำคอนเทนต์|ยูทูบเบอร์|สตรีม)",
    "programming": r"(เขียนโปรแกรม|เขียนโค้ด|โค้ด|โค้ดดิ้ง|coding|code|programming|programmer|โปรแกรมเมอร์|developer|dev\b|python|java|เขียนเว็บ|data ?science|วิศวะคอม|ai/ml|machine learning)",
    "study": r"(เรียน|นักเรียน|นักศึกษา|เอกสาร|ทำงานทั่วไป|งานทั่วไป|ใช้ทั่วไป|ออฟฟิศ|งานออฟฟิศ|word|excel|powerpoint|พิมพ์งาน|ทำรายงาน|เขียนรายงาน|การบ้าน|ดูหนัง|ดูซีรีส์|youtube|ยูทูป|ประชุม|zoom|ออนไลน์|ทำงาน)",
}
USE_DIGIT = {"1": "study", "2": "programming", "3": "gaming", "4": "creative"}

FIELD_KEYWORDS = {
    "weight": r"(น้ำหนัก|หนักกี่|หนักเท่า|หนักแค่ไหน|หนักประมาณ|กี่โล|กี่กิโล|\bkg\b|หนักไหม|หนักมั้ย|หนักมาก)",
    "battery": r"(แบต|battery|ใช้ได้กี่ชั่วโมง|อยู่ได้กี่ชั่วโมง|อยู่ได้นาน)",
    "warranty": r"(ประกัน|warranty|รับประกัน)",
    "stock": r"(มีของ|สต็อก|สต๊อก|stock|ของหมด|พร้อมส่ง|มีสินค้าไหม|ยังมีไหม|ยังมีอยู่ไหม)",
    "upgrade": r"(เพิ่มแรม|อัปแรม|อัพแรม|อัปเกรด|อัพเกรด|upgrade|ใส่แรม|เพิ่ม ?ssd|ใส่ ?ssd|ขยายแรม)",
    "touch": r"(จอสัมผัส|ทัชสกรีน|จอทัช|touch)",
    "office": r"(มี office|office แท้|ms office|microsoft office|office ในเครื่อง|ออฟฟิศแท้|มีออฟฟิศ|office ไหม|office มั้ย)",
    "os": r"(windows|วินโดว์|วินโดวส์|ระบบปฏิบัติการ)",
    "color": r"(มีสีอะไร|สีอะไร|มีกี่สี)",
}
SPEC_ASK = re.compile(r"(สเปก|สเปค|spec|รายละเอียด|ข้อมูลรุ่น|ดูรุ่น|ดูสเปก)", re.I)
PRICE_ASK = re.compile(r"(ราคา|เท่าไหร่|เท่าไร|กี่บาท|price)", re.I)
PRODUCT_Q = re.compile(r"(ราคา|เท่าไหร่|เท่าไร|กี่บาท|สเปก|สเปค|spec|มีไหม|มีมั้ย|มีขาย|ขายไหม|รุ่น)", re.I)
COMPARE = re.compile(r"(เทียบ|เปรียบเทียบ|compare|\bvs\b|ต่างกัน|แตกต่าง|อันไหนดีกว่า|ตัวไหนดีกว่า|รุ่นไหนดีกว่า)", re.I)
MORE = re.compile(r"(ดูรุ่นอื่น|รุ่นอื่น|มีอีกไหม|ขอดูเพิ่ม|ดูเพิ่ม|ตัวอื่น|อันอื่น|รุ่นถัดไป)")
CHEAPER = re.compile(r"(รุ่น.{0,6}ถูกกว่า|ถูกกว่านี้มี|มีที่ถูกกว่า|ขอที่ถูกกว่า|ราคาต่ำกว่านี้|ถูกลงอีก|เอาถูกกว่านี้)")
OVERVIEW = re.compile(r"(ทำอะไรได้บ้าง|ได้เครื่องแบบไหน|ได้แค่ไหน|ซื้ออะไรได้|มีอะไรบ้าง|มีรุ่นไหนบ้าง|ได้อะไรบ้าง)")
QUESTION_CAN = re.compile(r"(ได้ไหม|ได้มั้ย|ได้หรือเปล่า|ไหวไหม|ไหวมั้ย|ได้ป่าว|ได้รึเปล่า|ได้ปะ|ได้เปล่า|ดีไหม|ดีมั้ย|เหมาะไหม|เหมาะมั้ย)")
CHANGE_BUDGET = re.compile(r"(เปลี่ยนงบ|แก้งบ|งบใหม่)")
CHANGE_USE = re.compile(r"(เปลี่ยนการใช้งาน|เปลี่ยนงาน|ใช้งานอื่น)")
START_RECOMMEND = re.compile(r"^(แนะนำตามงบ|แนะนำรุ่น|ช่วยเลือก(เครื่อง|รุ่น)?|อยากได้โน้ตบุ๊ก|อยากซื้อโน้ตบุ๊ก|แนะนำหน่อย)$")
START_OVERVIEW = re.compile(r"^(งบนี้ทำอะไรได้บ้าง)$")
START_COMPARE = re.compile(r"^(เทียบรุ่น|เปรียบเทียบรุ่น)$")
PORTABLE = re.compile(r"(พกพา|น้ำหนักเบา|เบาๆ|เบา ๆ|บางเบา|พกไป|ถือไป|เบาที่สุด|ตัวเบา)")
BIG_SCREEN = re.compile(r"(จอใหญ่|จอ\s*1[678](\.\d)?\s*(นิ้ว|\")?\s*ขึ้นไป)")
SMALL_SCREEN = re.compile(r"(จอเล็ก|จอไม่ใหญ่|จอ\s*1[34](\.\d)?\s*(นิ้ว|\")?\s*(ลงมา|หรือเล็กกว่า))")
SCREEN_EXACT = re.compile(r"จอ\s*(1[3-8](?:\.\d)?)\s*(?:นิ้ว|\"|in)?")
OLED_PREF = re.compile(r"\boled\b", re.I)
GPU_QUERY = re.compile(r"rtx\s*(\d{4})(\s*ti)?", re.I)
ORDINAL = [
    (re.compile(r"(รุ่น|อัน|ตัว|เครื่อง)\s*(แรก|ที่\s*1\b|ที่หนึ่ง|หนึ่ง)"), 0),
    (re.compile(r"(รุ่น|อัน|ตัว|เครื่อง)\s*(ที่\s*2\b|ที่สอง|สอง)"), 1),
    (re.compile(r"(รุ่น|อัน|ตัว|เครื่อง)\s*(ที่\s*3\b|ที่สาม|สาม|สุดท้าย)"), 2),
]
THIS_ONE = re.compile(r"(รุ่นนี้|ตัวนี้|เครื่องนี้|อันนี้|รุ่นนั้น|ตัวนั้น)")
PRODUCT_ID = re.compile(r"\bnb\s*-?\s*(\d{1,3})\b", re.I)
COMPARE_FIRST_TWO = re.compile(r"(2|สอง)\s*(รุ่น|อัน|ตัว)\s*(แรก|นี้)?")


def norm(text: str) -> str:
    return normalize(text)


def find_uses(t: str) -> list[str]:
    # ตัดรหัสรุ่นที่มีทั้งตัวอักษรและตัวเลขออกก่อน (เช่น 83s6001gta มีคำว่า gta ซ่อนอยู่)
    t = re.sub(r"(?<![a-z0-9])(?=[a-z0-9-]*\d)(?=[a-z0-9-]*[a-z])[a-z0-9-]{4,}(?![a-z0-9])", " ", t)
    found = [u for u, pat in USE_KEYWORDS.items() if re.search(pat, t, re.I)]
    # "ทำงาน" อย่างเดียวถือเป็นงานเอกสาร แต่ถ้าเจองานเฉพาะทางอื่นด้วยให้ตัด study ออก
    if "study" in found and len(found) > 1 and not re.search(r"(เรียน|เอกสาร|ออฟฟิศ)", t):
        found.remove("study")
    return found


def find_brand(t: str, brands: list[str]) -> Optional[str]:
    from .catalog import BRANDS_TH
    for th, en in BRANDS_TH.items():
        if th in t:
            return en
    for b in brands:
        if re.search(rf"(?<![a-z]){b.lower()}(?![a-z])", t):
            return b
    return None


def only_brand_mentioned(t: str, brand: str) -> bool:
    rest = re.sub(rf"(?<![a-z]){brand.lower()}(?![a-z])", " ", t)
    return not re.search(r"[a-z]{3,}\d|\d+[a-z]+|[a-z]{4,}", rest)


def find_not_sold(t: str) -> Optional[str]:
    for k, label in sorted(NOT_SOLD.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", t):
            return label
    return None


def find_fields(t: str) -> list[str]:
    return [f for f, pat in FIELD_KEYWORDS.items() if re.search(pat, t, re.I)]


def find_ordinal(t: str) -> Optional[int]:
    for pat, idx in ORDINAL:
        if pat.search(t):
            return idx
    return None


def find_product_ids(t: str) -> list[str]:
    return [f"NB{int(n):03d}" for n in PRODUCT_ID.findall(t)]


def is_pii_request(t: str) -> bool:
    if CUSTOMER_DATA.search(t):
        return True
    return bool(OTHER_PERSON.search(t) and PERSON_DATA.search(t))

IMAGE_HELP = re.compile(r"(ส่งรูป|แนบรูป|ส่งภาพ|แนบภาพ|ใส่รูป|อัปรูป|อัพรูป|อัปโหลดรูป|อัพโหลดรูป|ส่งไฟล์รูป)")
