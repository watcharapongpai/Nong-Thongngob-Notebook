"""ตัวจัดการบทสนทนาของน้องตรงงบ

หลักการ (ขอบเขตงาน):
- 1.1.1 ทุกชื่อรุ่น ราคา และสเปกในคำตอบ ดึงจาก products.csv ผ่าน Catalog เท่านั้น
        ข้อมูลที่ไม่มี (ช่องว่าง) ตอบว่า "ยังไม่มีข้อมูลในระบบ" เสมอ
- 1.1.2 มีปุ่มตัวเลือก (quick replies) ตัวอย่างวิธีพิมพ์ และถามทีละขั้น
- 1.1.3 คำขอส่วนลด/ข้อมูลลูกค้าคนอื่น/คำสั่งแทรก/นโยบายที่ไม่มี ถูกดักก่อนเสมอ
        และคำตอบสร้างจากแม่แบบ จึงไม่มีทางให้ส่วนลดหรือแต่งนโยบายเอง
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import nlu, rules
from .budget import MAX_BUDGET, MIN_BUDGET, Budget, parse_budget
from .catalog import Catalog, Product

THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
OVER_BUDGET_RATIO = 1.10  # เสนอรุ่นเกินงบได้ไม่เกิน 10% เมื่อในงบมีไม่ถึง 2 รุ่น
CARDS_PER_PAGE = 3
PICKER_MAX = 40  # จำนวนรุ่นสูงสุดในรายการให้ติ๊กเลือกเทียบ
MAX_MESSAGE_CHARS = 500
SESSION_TTL_SEC = 3 * 3600

BUDGET_CHIPS = [
    ("ไม่เกิน 20,000", "งบไม่เกิน 20,000 บาท"),
    ("20,000–30,000", "งบ 20,000-30,000 บาท"),
    ("30,000–45,000", "งบ 30,000-45,000 บาท"),
    ("45,000–60,000", "งบ 45,000-60,000 บาท"),
    ("60,000 ขึ้นไป", "งบ 60,000 บาทขึ้นไป"),
]
USE_MESSAGES = {
    "study": "ใช้เรียน/ทำงานเอกสาร",
    "programming": "ใช้เขียนโปรแกรม",
    "gaming": "ใช้เล่นเกม",
    "creative": "ใช้ตัดต่อ/กราฟิก",
}
PRIVACY_NOTE = ("เพื่อความปลอดภัย ไม่ต้องส่งเบอร์โทร เลขบัตรประชาชน หรือข้อมูลส่วนตัวในแชทนี้นะครับ "
                "น้องตรงงบไม่ได้ใช้และไม่ได้บันทึกข้อมูลเหล่านี้")
AUTH_NOTE = "น้องตรงงบยืนยันตัวตนผ่านแชทไม่ได้ จึงให้ข้อมูลและราคาแบบเดียวกับลูกค้าทุกท่านครับ"
IMAGE_KIND_TEXT = {
    "laptop": "ดูเหมือนรูปโน้ตบุ๊ก",
    "gaming": "ดูเหมือนรูปโน้ตบุ๊กแนวเกมมิ่ง",
    "box": "ดูเหมือนรูปกล่องหรือสติกเกอร์สเปกของโน้ตบุ๊ก",
    "screenshot": "ดูเหมือนภาพหน้าจอสเปกหรือหน้าสินค้าโน้ตบุ๊ก",
    "problem": "ดูเหมือนรูปโน้ตบุ๊กที่มีปัญหาหรือหน้าจอแจ้งข้อผิดพลาด",
}
IMAGE_VERDICT_TEXT = {"relevant": "เกี่ยวข้อง", "uncertain": "ไม่แน่ใจ", "irrelevant": "ไม่เกี่ยวข้อง"}
FIELD_LABELS = {"weight": "น้ำหนัก", "battery": "แบตเตอรี่", "warranty": "ระยะประกัน", "stock": "สถานะสินค้าในสต็อก"}
FIELD_ATTR = {"weight": "weight_kg", "battery": "battery_wh", "warranty": "warranty_years", "stock": "stock_status"}


def baht(n: int) -> str:
    return f"{n:,} บาท"


def thai_date(iso: str) -> str:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{d} {THAI_MONTHS[mo - 1]} {y + 543}"


@dataclass
class Session:
    budget: Optional[Budget] = None
    use: Optional[str] = None
    uses_mentioned: list = field(default_factory=list)
    prefs: dict = field(default_factory=dict)
    ranked: list = field(default_factory=list)
    offset: int = 0
    shown: list = field(default_factory=list)
    focus: Optional[str] = None
    awaiting: Optional[str] = None
    last_seen: float = field(default_factory=time.time)

    def reset(self):
        self.__init__()


def reply(text: str, cards=None, compare=None, chips=None, picker=None, form=None) -> dict:
    return {
        "text": text.strip(),
        "cards": cards or [],
        "compare": compare,
        "picker": picker,
        "form": form,
        "quick_replies": [{"label": a, "message": b} for a, b in (chips or [])],
    }


class ChatBot:
    def __init__(self, catalog: Catalog, shop: dict):
        self.catalog = catalog
        self.shop = shop
        self.shop_name = shop.get("shop_name", "ร้าน")
        self.bot_name = shop.get("bot_name", "บอท")
        self.policies = shop.get("policies", {})
        self.data_date = thai_date(catalog.data_date)
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()

    @classmethod
    def from_files(cls, products_csv: str | Path, shop_json: str | Path) -> "ChatBot":
        with open(shop_json, encoding="utf-8") as f:
            shop = json.load(f)
        return cls(Catalog.from_csv(products_csv), shop)

    # ------------------------------------------------------------------ sessions
    def session(self, sid: str) -> Session:
        now = time.time()
        with self.lock:
            if len(self.sessions) > 200:
                for k in [k for k, v in self.sessions.items() if now - v.last_seen > SESSION_TTL_SEC]:
                    del self.sessions[k]
            s = self.sessions.setdefault(sid, Session())
            s.last_seen = now
            return s

    def welcome(self, sid: str) -> dict:
        s = self.session(sid)
        s.reset()
        return self._welcome()

    def reply(self, sid: str, message: str) -> dict:
        s = self.session(sid)
        return self.handle(message or "", s)

    def reply_image(self, sid: str, analysis: Optional[dict], caption: str = "",
                    error: Optional[str] = None) -> dict:
        """ตอบเมื่อลูกค้าส่งรูป analysis มาจาก bot.vision (None = ระบบตรวจรูปยังไม่พร้อม)"""
        s = self.session(sid)
        return self.handle_image(analysis, caption or "", s, error)

    # ------------------------------------------------------------------ main
    def handle(self, raw: str, s: Session) -> dict:
        raw = raw.strip()
        if not raw:
            return self._help()
        if len(raw) > MAX_MESSAGE_CHARS:
            return reply(f"ข้อความยาวเกินไปครับ รบกวนพิมพ์สั้น ๆ ไม่เกิน {MAX_MESSAGE_CHARS} ตัวอักษร "
                         "เช่น “งบ 25,000 ใช้เรียน”", chips=self._main_chips())
        t = nlu.norm(raw)
        notes = [PRIVACY_NOTE] if nlu.PERSONAL_INFO.search(t) else []

        if nlu.RESET.search(t):
            s.reset()
            return self._welcome()

        # ---- ขอบเขต 1.1.3: ดักคำขอที่ร้านไม่อนุญาตก่อนทุกอย่าง ----
        authority = nlu.AUTHORITY.search(t)
        if nlu.INJECTION.search(t) or (authority and nlu.PRIVILEGE_ASK.search(t)):
            return self._refuse_injection(t, s, notes)
        if notes and self._policy_topic(t) == "ordering":
            # ลูกค้าส่งเบอร์/ข้อมูลตัวเองมาเพื่อสั่งซื้อ: เตือนเรื่องข้อมูลส่วนตัว แล้วตอบนโยบายการสั่งซื้อ
            return self._policy("ordering", t, s, notes)
        if nlu.is_pii_request(t):
            return self._refuse_pii(notes)
        if nlu.ORDER.search(t):
            return self._order(notes)
        if nlu.NEGOTIATE.search(t):
            return self._negotiate(t, s, notes)
        if authority:
            notes.append(AUTH_NOTE)
        if nlu.HANDOFF.search(t):
            return self._handoff(notes)
        if nlu.SALES.search(t):
            return self._no_sales_data(notes)
        if nlu.OTHER_STORE.search(t) and re.search(r"ถูก|แพง|ราคา|เทียบ|ต่าง", t):
            return self._other_store(notes)
        if nlu.out_of_scope(t):
            return self._out_of_scope(notes)
        if nlu.GUESS.search(t):
            notes.append(f"{self.bot_name}ไม่เดาข้อมูลครับ ตอบได้เฉพาะที่มีในข้อมูลสินค้าและนโยบายของร้าน")

        # ---- เมนูจากปุ่ม ----
        if nlu.START_RECOMMEND.match(t):
            s.awaiting = "budget"
            return self._ask_budget(notes)
        if nlu.START_OVERVIEW.match(t):
            s.awaiting = "overview"
            return self._ask_budget(notes, overview=True)
        if nlu.START_COMPARE.match(t):
            return self._compare_start(s, notes)
        if nlu.POLICY_MENU.match(t):
            return self._policy_menu(notes)
        if nlu.IMAGE_HELP.search(t):
            return reply(self._join(notes,
                f"ส่งรูปได้ครับ กดปุ่มรูปภาพข้างช่องพิมพ์ หรือวาง/ลากรูปมาที่หน้าแชท (JPG, PNG, WEBP, GIF ไม่เกิน 5MB)\n"
                f"{self.bot_name}จะตรวจว่ารูปเกี่ยวกับโน้ตบุ๊กหรือไม่ แต่ยังอ่านชื่อรุ่นหรือตัวอักษรจากรูปไม่ได้ "
                "ถ้าอยากได้คำแนะนำ พิมพ์งบกับการใช้งานมาพร้อมรูปได้เลย\n"
                "รูปจะถูกตรวจแล้วทิ้งทันที ไม่มีการบันทึก และไม่ควรส่งรูปบัตรประชาชนหรือเอกสารส่วนตัว"),
                chips=self._main_chips())
        if nlu.CHANGE_BUDGET.search(t):
            s.budget, s.awaiting = None, "budget"
            return self._ask_budget(notes)
        if nlu.CHANGE_USE.search(t):
            s.use, s.awaiting = None, "use"
            return self._ask_use(notes)

        # ---- นโยบายร้าน ----
        topic = self._policy_topic(t)
        if topic:
            return self._policy(topic, t, s, notes)

        # ---- ข้อมูลที่ใช้ร่วมกันหลายขั้น ----
        budget_in_msg = parse_budget(t)
        uses_in_msg = nlu.find_uses(t)
        fields = nlu.find_fields(t)
        if nlu.PORTABLE.search(t):
            fields = [f for f in fields if f != "weight"]

        # ---- ขั้นตอนเทียบรุ่น: เลือกงบแล้วแสดงรายการรุ่นให้ติ๊กเลือก ----
        if budget_in_msg and not nlu.find_product_ids(t) and (
                s.awaiting == "compare_budget" or (nlu.COMPARE.search(t) and not re.search(r"[a-z]{3,}", t))):
            return self._compare_picker(budget_in_msg, s, notes)

        # ---- สินค้าที่ร้านไม่มีขาย ----
        not_sold = nlu.find_not_sold(t)
        if not_sold:
            return self._not_sold(not_sold, t, s, notes, budget_in_msg, uses_in_msg)

        # ---- เปรียบเทียบ ----
        if nlu.COMPARE.search(t):
            r = self._compare(t, s, notes)
            if r:
                return r

        # ---- อ้างถึงสินค้าเฉพาะรุ่น ----
        prods, bad_ids = self._resolve_products(t, s)
        if bad_ids:
            return reply(self._join(notes, f"ไม่พบรหัสสินค้า {', '.join(bad_ids)} ในระบบครับ "
                                         f"(รหัสสินค้าที่มี: {self.catalog.products[0].id}–{self.catalog.products[-1].id})"),
                         chips=self._main_chips())
        if prods:
            if len(prods) == 1:
                p = prods[0]
                if fields:
                    return self._field_answer(p, fields, s, notes)
                if nlu.SPEC_ASK.search(t):
                    return self._detail(p, s, notes)
                if uses_in_msg and not budget_in_msg:
                    return self._suitability(p, uses_in_msg, s, notes)
                if nlu.PROMO.search(t) or nlu.PRICE_ASK.search(t):
                    return self._product_promo(p, s, notes, t)
                return self._detail(p, s, notes)
            if budget_in_msg or uses_in_msg:
                s.prefs["only_ids"] = [p.id for p in prods]
                s.prefs["only_label"] = "รุ่นตามที่ค้นหา"
            else:
                return self._choices(prods, s, notes)

        focus = self.catalog.get(s.focus) if s.focus else None
        if focus and fields:
            return self._field_answer(focus, fields, s, notes)
        if focus and uses_in_msg and nlu.QUESTION_CAN.search(t) and not budget_in_msg and len(t) <= 40:
            return self._suitability(focus, uses_in_msg, s, notes)
        if fields and not (budget_in_msg or uses_in_msg):
            return self._field_no_context(fields, notes)

        if nlu.PROMO.search(t) and not budget_in_msg and not uses_in_msg:
            return self._promos(s, notes)

        # ---- เติมช่องข้อมูลเพื่อแนะนำรุ่น ----
        changed = False
        if budget_in_msg:
            s.budget = budget_in_msg
            changed = True
        if uses_in_msg:
            s.uses_mentioned = uses_in_msg
            s.use = next(u for u in rules.DEMAND_PRIORITY if u in uses_in_msg)
            changed = True
        elif s.awaiting == "use" and t in nlu.USE_DIGIT:
            s.use = nlu.USE_DIGIT[t]
            s.uses_mentioned = [s.use]
            changed = True
        new_prefs = self._extract_prefs(t)
        if new_prefs:
            s.prefs.update(new_prefs)
            changed = True

        if nlu.MORE.search(t) and s.ranked and not changed:
            return self._more(s, notes)
        if nlu.CHEAPER.search(t) and s.use and s.budget:
            s.prefs["sort"] = "price"
            changed = True

        overview = bool(nlu.OVERVIEW.search(t)) or s.awaiting == "overview"
        if changed or (overview and s.budget):
            return self._recommend_flow(t, s, notes, overview=overview and not uses_in_msg)

        if nlu.HELP.search(t):
            return self._help(notes)
        if nlu.GREETING.search(t):
            return self._welcome(notes)
        if nlu.THANKS.search(t):
            return reply(self._join(notes, f"ยินดีครับ ถ้ามีอะไรให้{self.bot_name}ช่วยเพิ่ม พิมพ์มาได้เลยนะครับ"),
                         chips=self._main_chips())
        if nlu.GENERIC_POLICY.search(t):
            return self._policy_unknown(notes)
        if nlu.PRODUCT_Q.search(t):
            tok = self.catalog.unknown_model_token(t)
            if tok:
                return self._model_not_found(tok, notes)
        return self._fallback(s, notes)

    # ------------------------------------------------------------------ images
    def handle_image(self, analysis: Optional[dict], caption: str, s: Session,
                     error: Optional[str] = None) -> dict:
        caption = caption.strip()[:MAX_MESSAGE_CHARS]
        if error:
            return self._with_caption(error + " ลองส่งรูปใหม่ หรือพิมพ์คำถามเป็นข้อความได้เลยครับ", caption, s, None)
        if analysis is None:
            return self._with_caption("ตอนนี้ระบบตรวจรูปยังไม่พร้อมใช้งานครับ รบกวนพิมพ์คำถามเป็นข้อความแทน",
                                      caption, s, None)
        verdict, kind = analysis["verdict"], analysis.get("kind", "")
        info = {"verdict": verdict, "label": IMAGE_VERDICT_TEXT[verdict]}
        lines = []
        if "personal_doc" in analysis.get("flags", []):
            lines.append("รูปนี้อาจมีบัตรหรือเอกสารส่วนตัว ไม่ต้องส่งรูปลักษณะนี้นะครับ ระบบไม่ได้บันทึกรูปที่ส่งมา")
        chips = None
        if verdict == "relevant":
            lines.append(f"ได้รับรูปแล้วครับ — {IMAGE_KIND_TEXT.get(kind, 'ดูเหมือนรูปที่เกี่ยวกับโน้ตบุ๊ก')}")
            if not caption:
                lines.append(f"{self.bot_name}ยังอ่านชื่อรุ่น ราคา หรือสเปกจากรูปไม่ได้ จึงยังบอกไม่ได้ว่าเป็นรุ่นไหนครับ")
                if kind in ("box", "screenshot"):
                    lines.append("พิมพ์ชื่อรุ่นหรือรหัสรุ่นจากรูปมาได้เลย น้องตรงงบจะเช็กว่าร้านมีรุ่นนั้นไหม")
                elif kind == "problem":
                    pol = self.policies.get("repair", {})
                    ans = (pol.get("answer") or "").strip()
                    lines.append(f"{pol.get('label', 'บริการซ่อม')}: {ans}" if ans
                                 else "ร้านยังไม่มีข้อมูลเรื่องบริการซ่อมในระบบครับ")
                else:
                    lines.append("ถ้าอยากได้เครื่องแบบนี้ บอกงบกับการใช้งาน หรือพิมพ์ชื่อรุ่นมาได้เลยครับ")
                chips = ([("ดูรุ่นเล่นเกม", USE_MESSAGES["gaming"])] if kind == "gaming" else []) + self._main_chips()[:3]
        elif verdict == "uncertain":
            lines.append(f"ได้รับรูปแล้วครับ แต่{self.bot_name}ไม่แน่ใจว่ารูปนี้เกี่ยวกับโน้ตบุ๊กหรือไม่")
            if not caption:
                lines.append("ช่วยพิมพ์อธิบายเพิ่มหน่อยได้ไหมครับ เช่น ชื่อรุ่น หรือสิ่งที่อยากถาม")
        else:
            lines.append(f"รูปนี้ไม่ใช่เรื่องที่{self.bot_name}ช่วยค้นหาได้ครับ "
                         f"({self.bot_name}ช่วยได้เฉพาะเรื่องโน้ตบุ๊กของร้าน)")
        return self._with_caption("\n".join(lines), caption, s, info, chips)

    def _with_caption(self, image_text: str, caption: str, s: Session, info: Optional[dict],
                      chips=None) -> dict:
        """ถ้ามีข้อความแนบมากับรูป ให้ตอบข้อความนั้นตามปกติ (ผ่านตัวดักความปลอดภัยเหมือนเดิม)"""
        if caption:
            r = self.handle(caption, s)
            r["text"] = image_text + "\n\n" + r["text"]
        else:
            r = reply(image_text, chips=chips or self._main_chips())
        r["image"] = info
        return r

    # ------------------------------------------------------------------ helpers
    def _join(self, notes: list[str], *parts: str) -> str:
        return "\n\n".join([*notes, *[p for p in parts if p]])

    @property
    def contact(self) -> str:
        return (self.shop.get("contact") or "").strip()

    def _contact_line(self) -> str:
        """คืนบรรทัดช่องทางติดต่อ ถ้าร้านไม่มีช่องทางติดต่อจะคืนค่าว่าง (ไม่พูดถึงพนักงาน)"""
        return f"ติดต่อพนักงานได้ที่: {self.contact}" if self.contact else ""

    def _policy_text(self, key: str) -> str:
        return (self.policies.get(key, {}).get("answer") or "").strip()

    def _main_chips(self):
        chips = [("แนะนำตามงบ", "แนะนำตามงบ"), ("งบนี้ทำอะไรได้บ้าง", "งบนี้ทำอะไรได้บ้าง"),
                 ("เทียบรุ่น", "เทียบรุ่น"), ("นโยบายร้าน", "นโยบายร้าน")]
        if self.contact:
            chips.append(("คุยกับพนักงาน", "คุยกับพนักงาน"))
        return chips

    def _use_chips(self, counts: Optional[dict] = None):
        chips = []
        for i, u in enumerate(rules.USE_ORDER, 1):
            label = f"{i}) {rules.USE_CASES[u]['label']}"
            if counts is not None:
                label += f" ({counts.get(u, 0)})"
            chips.append((label, USE_MESSAGES[u]))
        return chips

    def _card(self, p: Product, use: Optional[str] = None, label: Optional[str] = None,
              detail: bool = False) -> dict:
        card = {
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "promo": p.promo,
            "label": label,
            "specs": p.spec_lines(),
            "reasons": rules.highlights(p, use) if use else [],
            "notes": rules.caveats(p, use) if use else [],
            "suitable": p.suitable_labels(),
            "actions": [] if detail else [{"label": "ดูสเปกเต็ม", "message": f"ดูสเปก {self._full(p)}"}],
        }
        if detail:
            extra = [f"ระบบปฏิบัติการ: {p.os or 'ไม่มีข้อมูล'}"]
            office = {"yes": "มี (ตามข้อมูลสินค้า)", "no": "ไม่ได้ระบุในรายการสินค้า"}.get(p.office_included, "ไม่มีข้อมูล")
            extra.append(f"Office ในเครื่อง: {office}")
            extra.append(f"แรม: {p.ram_detail or str(p.ram_gb) + 'GB'}")
            if p.notes:
                extra.append(f"รายละเอียดเพิ่มเติม: {p.notes}")
            missing = [FIELD_LABELS[f] for f, a in FIELD_ATTR.items() if not getattr(p, a)]
            if missing:
                extra.append(f"ยังไม่มีข้อมูลในระบบ: {', '.join(missing)}")
            card["specs"] = p.spec_lines() + extra
            card["notes"] = [f"ไม่ผ่านเกณฑ์{rules.USE_CASES[u]['label']}: {', '.join(p.fails[u])}"
                             for u in rules.USE_ORDER if not p.passes[u]]
        return card

    @staticmethod
    def _full(p: Product) -> str:
        """ชื่อรุ่นเต็มไม่รวมสี (ไม่ซ้ำกันในร้าน) ใช้แสดงและใช้ส่งต่อเมื่อกดปุ่ม"""
        return f"{p.brand} {p.model.split(' - ')[0]}"

    @staticmethod
    def _short(p: Product) -> str:
        return f"{p.brand} {p.series_key}"

    def _pair(self, a: Product, b: Product) -> tuple[str, str]:
        """ชื่อสั้นของสองรุ่นที่เทียบกัน ถ้าชื่อสั้นซ้ำกันใช้ชื่อเต็ม"""
        sa, sb = self._short(a), self._short(b)
        return (self._full(a), self._full(b)) if sa == sb else (sa, sb)

    def _spec_chip(self, p: Product) -> tuple[str, str]:
        return (f"ดูสเปก {p.model.split(' - ')[0]}", f"ดูสเปก {self._full(p)}")

    # ------------------------------------------------------------------ welcome / help
    def _welcome(self, notes=None) -> dict:
        text = (f"สวัสดีครับ {self.bot_name} ผู้ช่วยอัตโนมัติของร้าน{self.shop_name} ยินดีให้บริการครับ\n\n"
                f"{self.bot_name}ช่วยได้ 4 เรื่อง:\n"
                "1) แนะนำโน้ตบุ๊กตามงบและการใช้งาน (เรียน เขียนโปรแกรม เล่นเกม ตัดต่อ)\n"
                "2) ดูสเปก / เทียบรุ่น\n"
                "3) ตอบคำถามเรื่องนโยบายร้าน\n"
                "4) ส่งรูปมาถามได้ (ปุ่มรูปภาพข้างช่องพิมพ์) น้องตรงงบจะตรวจว่ารูปเกี่ยวกับโน้ตบุ๊กไหม "
                "แต่ยังอ่านชื่อรุ่นจากรูปไม่ได้\n\n"
                "พิมพ์บอกได้เลย เช่น “งบ 25,000 ใช้เรียน” หรือ “งบ 3 หมื่นเล่นเกมได้ไหม” หรือกดปุ่มด้านล่างครับ")
        return reply(self._join(notes or [], text), chips=self._main_chips())

    def _help(self, notes=None) -> dict:
        return self._welcome(notes)

    def _fallback(self, s: Session, notes) -> dict:
        if s.awaiting in ("budget", "overview", "compare_budget"):
            return reply(self._join(notes, "ขอโทษครับ น้องตรงงบยังไม่เข้าใจงบประมาณที่พิมพ์มา "
                                           "ลองพิมพ์เป็นตัวเลข เช่น “25000”, “2 หมื่น” หรือ “20-30k” หรือกดปุ่มด้านล่างครับ"),
                         chips=BUDGET_CHIPS,
                         form=self._budget_form("compare" if s.awaiting == "compare_budget" else "recommend"))
        if s.awaiting == "use":
            return self._ask_use(notes, prefix="ขอโทษครับ ยังไม่เข้าใจการใช้งานที่พิมพ์มา")
        text = (f"ขอโทษครับ {self.bot_name}ยังไม่เข้าใจข้อความนี้ "
                f"{self.bot_name}ตอบได้เฉพาะเรื่องโน้ตบุ๊กและนโยบายของร้าน{self.shop_name} ครับ\n"
                "ลองพิมพ์แบบนี้: “งบ 25,000 ใช้เรียน”, “ดูสเปก msi modern 16s”, “เทียบ ideapad slim 5 กับ msi modern 16s” หรือกดปุ่มด้านล่างครับ")
        return reply(self._join(notes, text), chips=self._main_chips())

    # ------------------------------------------------------------------ slot prompts
    def _ask_budget(self, notes, overview=False, prefix="") -> dict:
        q = "บอกงบประมาณได้เลยครับ" if overview else "งบประมาณประมาณเท่าไหร่ครับ"
        text = (f"{prefix}\n{q} พิมพ์เป็นตัวเลขก็ได้ เช่น “25000” หรือ “2 หมื่น” "
                "กดเลือกช่วงราคาด้านล่าง หรือกรอกช่วงงบเองในช่อง “กำหนดช่วงงบเอง” ครับ")
        return reply(self._join(notes, text), chips=BUDGET_CHIPS, form=self._budget_form("recommend"))

    def _ask_use(self, notes, prefix="", counts=None) -> dict:
        text = (f"{prefix}\nอยากใช้ทำอะไรเป็นหลักครับ? กดปุ่มด้านล่าง หรือพิมพ์เลข 1–4\n"
                "1) เรียน/ทำงานเอกสาร  2) เขียนโปรแกรม  3) เล่นเกม  4) ตัดต่อ/กราฟิก")
        return reply(self._join(notes, text), chips=self._use_chips(counts))

    # ------------------------------------------------------------------ preferences
    def _extract_prefs(self, t: str) -> dict:
        p = {}
        brand = nlu.find_brand(t, self.catalog.brands)
        if brand and nlu.only_brand_mentioned(t, brand):
            p["brand"] = brand
        if nlu.PORTABLE.search(t):
            p["screen_max"], p["portable"] = 14.0, True
        if nlu.BIG_SCREEN.search(t):
            p["screen_min"] = 16.0
        elif nlu.SMALL_SCREEN.search(t):
            p["screen_max"] = 14.0
        else:
            m = nlu.SCREEN_EXACT.search(t)
            if m:
                p["screen_exact"] = float(m.group(1))
        if nlu.OLED_PREF.search(t):
            p["oled"] = True
        if re.search(nlu.FIELD_KEYWORDS["office"], t, re.I):
            p["office"] = True
        g = nlu.GPU_QUERY.search(t)
        if g:
            p["gpu"] = f"rtx {g.group(1)}" + (" ti" if g.group(2) else "")
        return p

    def _apply_prefs(self, items: list[Product], prefs: dict) -> tuple[list[Product], list[str]]:
        out, desc = items, []
        if prefs.get("only_ids"):
            out = [p for p in out if p.id in prefs["only_ids"]]
            desc.append(prefs.get("only_label", "รุ่นที่ค้นหา"))
        if prefs.get("brand"):
            out = [p for p in out if p.brand == prefs["brand"]]
            desc.append(f"แบรนด์ {prefs['brand']}")
        if prefs.get("screen_max"):
            out = [p for p in out if p.screen_inch <= prefs["screen_max"]]
            desc.append(f"จอไม่เกิน {prefs['screen_max']:g} นิ้ว")
        if prefs.get("screen_min"):
            out = [p for p in out if p.screen_inch >= prefs["screen_min"]]
            desc.append(f"จอ {prefs['screen_min']:g} นิ้วขึ้นไป")
        if prefs.get("screen_exact"):
            out = [p for p in out if abs(p.screen_inch - prefs["screen_exact"]) <= 0.35]
            desc.append(f"จอ {prefs['screen_exact']:g} นิ้ว")
        if prefs.get("oled"):
            out = [p for p in out if "oled" in p.panel.lower()]
            desc.append("จอ OLED")
        if prefs.get("office"):
            out = [p for p in out if p.office_included == "yes"]
            desc.append("มี Office ในเครื่อง")
        if prefs.get("gpu"):
            g = prefs["gpu"]
            out = [p for p in out if g in p.gpu.lower() and (g.endswith("ti") or " ti" not in p.gpu.lower())]
            desc.append(g.upper())
        return out, desc

    # ------------------------------------------------------------------ recommendation
    def _recommend_flow(self, t: str, s: Session, notes, overview: bool) -> dict:
        if s.budget is None:
            s.awaiting = "budget"
            prefix = f"รับทราบครับ ใช้{rules.USE_CASES[s.use]['label']}" if s.use else "รับทราบครับ"
            return self._ask_budget(notes, prefix=prefix)
        if s.use is None or overview:
            s.awaiting = "use"
            return self._overview(s, notes)
        s.awaiting = None
        asked_can = bool(nlu.QUESTION_CAN.search(t))
        return self._recommend(s, notes, asked_can)

    def _in_budget(self, items, b: Budget):
        if b.unlimited or (b.min is None and b.max is None):
            return list(items)
        return [p for p in items if b.contains(p.eff_price)]

    def _overview(self, s: Session, notes) -> dict:
        b = s.budget
        pool, pdesc = self._apply_prefs(self.catalog.products, s.prefs)
        inb = self._in_budget(pool, b)
        pref_txt = f" (เงื่อนไข: {', '.join(pdesc)})" if pdesc else ""
        if not inb:
            cheapest = min(pool or self.catalog.products, key=lambda p: p.eff_price)
            gap = cheapest.eff_price - (b.max or 0)
            label = f"เกินงบ {baht(gap)}" if b.max and gap > 0 else "ใกล้เคียงที่สุด"
            text = (f"{b.label()}{pref_txt} ยังไม่มีโน้ตบุ๊กในร้านครับ\n"
                    f"รุ่นที่ราคาถูกที่สุดคือ {cheapest.name} ราคา {baht(cheapest.eff_price)}"
                    + (f" ({label})" if b.max else "") +
                    "\nลองปรับงบ กดเลือกช่วงราคาด้านล่าง หรือกรอกช่วงงบใหม่ในช่อง “กำหนดช่วงงบเอง” ได้ครับ")
            s.shown, s.focus = [cheapest.id], cheapest.id
            return reply(self._join(notes, text), cards=[self._card(cheapest, label=label)], chips=BUDGET_CHIPS,
                         form=self._budget_form("recommend"))
        lines = [f"{b.label()}{pref_txt} มีโน้ตบุ๊กในร้าน {len(inb)} รุ่น แยกตามเกณฑ์การใช้งานของร้านได้แบบนี้ครับ:"]
        counts = {}
        for u in rules.USE_ORDER:
            ok = [p for p in inb if p.passes[u]]
            counts[u] = len(ok)
            label = rules.USE_CASES[u]["label"]
            if ok:
                lines.append(f"• {label}: {len(ok)} รุ่น (เริ่มต้น {baht(min(p.eff_price for p in ok))})")
            else:
                anyok = [p for p in pool if p.passes[u]]
                if anyok:
                    lines.append(f"• {label}: ยังไม่มีในงบนี้ (รุ่นที่ผ่านเกณฑ์ถูกที่สุด {baht(min(p.eff_price for p in anyok))})")
                else:
                    lines.append(f"• {label}: ยังไม่มีรุ่นที่ผ่านเกณฑ์")
        if s.prefs.get("portable"):
            lines.append("หมายเหตุ: ระบบยังไม่มีข้อมูลน้ำหนัก จึงกรองเป็นรุ่นจอไม่เกิน 14 นิ้วแทนครับ")
        return self._ask_use(notes, prefix="\n".join(lines), counts=counts)

    def _diversify(self, items: list[Product]) -> list[Product]:
        first, rest, seen = [], [], set()
        for p in items:
            key = (p.brand, p.series_key)
            (rest if key in seen else first).append(p)
            seen.add(key)
        return first + rest

    def _recommend(self, s: Session, notes, asked_can: bool = False) -> dict:
        use, b = s.use, s.budget
        label = rules.USE_CASES[use]["label"]
        cands = [p for p in self.catalog.products if p.passes[use]]
        filtered, pdesc = self._apply_prefs(cands, s.prefs)
        pref_note = ""
        if pdesc and not filtered:
            pref_note = f"ไม่มีรุ่นที่ตรงเงื่อนไข ({', '.join(pdesc)}) และผ่านเกณฑ์{label} จึงแสดงรุ่นที่ใกล้เคียงโดยไม่กรองเงื่อนไขนี้ครับ"
            filtered, pdesc = cands, []
        inb = self._in_budget(filtered, b)
        by_price = s.prefs.get("sort") == "price" or (b.cheapest and b.max is None)
        if by_price:
            ordered = sorted(inb, key=lambda p: (p.eff_price, -rules.score(p, use)))
        else:
            ordered = self._diversify(sorted(inb, key=lambda p: (-rules.score(p, use), p.eff_price)))
        s.ranked, s.offset = [p.id for p in ordered], 0
        picks = ordered[:CARDS_PER_PAGE]
        cards = [self._card(p, use) for p in picks]

        extra_text = ""
        if b.max is not None and len(inb) < 2:
            over = sorted([p for p in filtered if b.max < p.eff_price <= b.max * OVER_BUDGET_RATIO],
                          key=lambda p: p.eff_price)[:1]
            for p in over:
                cards.append(self._card(p, use, label=f"เกินงบ {baht(p.eff_price - b.max)}"))
        if not cards:
            nearest = min(filtered, key=lambda p: self._distance(p, b)) if filtered else None
            if nearest:
                d = self._distance(nearest, b)
                lab = (f"เกินงบ {baht(d)}" if b.max is not None and nearest.eff_price > b.max
                       else f"ต่ำกว่างบขั้นต่ำ {baht(d)}" if b.min is not None and nearest.eff_price < b.min
                       else "ใกล้เคียงที่สุด")
                cards.append(self._card(nearest, use, label=lab))
            others = [rules.USE_CASES[u]["label"] for u in rules.USE_ORDER
                      if u != use and any(p.passes[u] for p in self._in_budget(self.catalog.products, b))]
            head = (f"{b.label()} ยังไม่มีรุ่นที่ผ่านเกณฑ์{label}ของร้านครับ"
                    + (f"\nรุ่นที่ผ่านเกณฑ์และใกล้งบที่สุดคือ {nearest.name} ราคา {baht(nearest.eff_price)} ({cards[0]['label']})" if nearest else ""))
            if others:
                extra_text = f"ถ้าใช้งานแบบ {', '.join(others)} งบนี้มีรุ่นให้เลือกครับ"
        else:
            if asked_can and inb:
                head = f"ได้ครับ {b.label()} มีรุ่นที่ผ่านเกณฑ์{label}ของร้าน {len(inb)} รุ่น"
            elif inb:
                head = f"{b.label()} สำหรับ{label}: มีรุ่นที่ผ่านเกณฑ์ {len(inb)} รุ่น"
            else:
                head = f"{b.label()} ยังไม่มีรุ่นที่ผ่านเกณฑ์{label}ในงบพอดี แต่มีรุ่นที่เกินงบไม่เกิน 10% ครับ"
            if inb:
                head += (" เรียงจากราคาถูกที่สุดครับ" if by_price
                         else f" {self.bot_name}คัดรุ่นที่สเปกดีที่สุดในงบมาให้ {len(picks)} รุ่นครับ")
                n_over = len(cards) - len(picks)
                if n_over > 0:
                    head += f" และมีรุ่นที่เกินงบไม่เกิน 10% ให้ดูเพิ่มอีก {n_over} รุ่น"
        parts = [head]
        if len(s.uses_mentioned) > 1:
            parts.append(f"(ใช้เกณฑ์ของงานที่ต้องการสเปกสูงสุด คือ{label})")
        if pdesc:
            parts.append(f"เงื่อนไขเพิ่มเติม: {', '.join(pdesc)}")
        if s.prefs.get("portable"):
            parts.append("ระบบยังไม่มีข้อมูลน้ำหนัก จึงกรองเป็นรุ่นจอไม่เกิน 14 นิ้วแทนครับ")
        if pref_note:
            parts.append(pref_note)
        if extra_text:
            parts.append(extra_text)
        parts.append(f"ราคาตามข้อมูลร้าน ณ วันที่ {self.data_date}")
        s.shown = [c["id"] for c in cards]
        s.focus = cards[0]["id"] if len(cards) == 1 else None
        chips = []
        if len(cards) >= 2:
            chips.append(("เทียบ 2 รุ่นแรก", "เทียบ 2 รุ่นแรก"))
        if len(ordered) > CARDS_PER_PAGE:
            chips.append(("ดูรุ่นอื่น", "ดูรุ่นอื่น"))
        if not by_price and len(inb) > CARDS_PER_PAGE:
            chips.append(("รุ่นที่ถูกกว่านี้", "ขอรุ่นที่ถูกกว่านี้"))
        chips += [("เปลี่ยนงบ", "เปลี่ยนงบ"), ("เปลี่ยนการใช้งาน", "เปลี่ยนการใช้งาน"), ("เริ่มใหม่", "เริ่มใหม่")]
        return reply(self._join(notes, "\n".join(parts)), cards=cards, chips=chips)

    @staticmethod
    def _distance(p: Product, b: Budget) -> int:
        if b.max is not None and p.eff_price > b.max:
            return p.eff_price - b.max
        if b.min is not None and p.eff_price < b.min:
            return b.min - p.eff_price
        return 0

    def _more(self, s: Session, notes) -> dict:
        s.offset += CARDS_PER_PAGE
        ids = s.ranked[s.offset:s.offset + CARDS_PER_PAGE]
        if not ids:
            s.offset = max(0, len(s.ranked) - CARDS_PER_PAGE)
            return reply(self._join(notes, "แสดงครบทุกรุ่นที่ผ่านเกณฑ์ในงบนี้แล้วครับ ลองเปลี่ยนงบหรือการใช้งานได้ครับ"),
                         chips=[("เปลี่ยนงบ", "เปลี่ยนงบ"), ("เปลี่ยนการใช้งาน", "เปลี่ยนการใช้งาน"), ("เริ่มใหม่", "เริ่มใหม่")])
        prods = [self.catalog.get(i) for i in ids]
        cards = [self._card(p, s.use) for p in prods]
        s.shown, s.focus = ids, (ids[0] if len(ids) == 1 else None)
        start = s.offset + 1
        text = f"รุ่นถัดไป (อันดับ {start}–{start + len(ids) - 1} จากทั้งหมด {len(s.ranked)} รุ่น)\nราคาตามข้อมูลร้าน ณ วันที่ {self.data_date}"
        chips = []
        if len(cards) >= 2:
            chips.append(("เทียบ 2 รุ่นแรก", "เทียบ 2 รุ่นแรก"))
        if s.offset + CARDS_PER_PAGE < len(s.ranked):
            chips.append(("ดูรุ่นอื่น", "ดูรุ่นอื่น"))
        chips += [("เปลี่ยนงบ", "เปลี่ยนงบ"), ("เริ่มใหม่", "เริ่มใหม่")]
        return reply(self._join(notes, text), cards=cards, chips=chips)

    # ------------------------------------------------------------------ products
    def _resolve_products(self, t: str, s: Session) -> tuple[list[Product], list[str]]:
        ids = nlu.find_product_ids(t)
        if ids:
            found = [self.catalog.get(i) for i in ids]
            bad = [i for i, p in zip(ids, found) if p is None]
            return [p for p in found if p], bad
        o = nlu.find_ordinal(t)
        if o is not None and o < len(s.shown):
            return [self.catalog.get(s.shown[o])], []
        if nlu.THIS_ONE.search(t):
            if s.focus:
                return [self.catalog.get(s.focus)], []
            if len(s.shown) == 1:
                return [self.catalog.get(s.shown[0])], []
        return self.catalog.search(t), []

    def _detail(self, p: Product, s: Session, notes) -> dict:
        s.focus, s.shown = p.id, [p.id]
        suit = p.suitable_labels()
        text = (f"รายละเอียด {self._full(p)} ครับ\n"
                f"เหมาะกับ (ตามเกณฑ์ร้าน): {', '.join(suit) if suit else 'ยังไม่ผ่านเกณฑ์การใช้งานใดของร้าน'}\n"
                f"ราคาตามข้อมูลร้าน ณ วันที่ {self.data_date}")
        chips = [("เล่นเกมได้ไหม", "รุ่นนี้เล่นเกมได้ไหม"), ("หนักกี่โล", "รุ่นนี้หนักกี่โล"),
                 ("รุ่นใกล้เคียงงบเดียวกัน", f"งบไม่เกิน {self._round_up(p.eff_price):,} บาท"),
                 ("เริ่มใหม่", "เริ่มใหม่")]
        return reply(self._join(notes, text), cards=[self._card(p, detail=True)], chips=chips)

    @staticmethod
    def _round_up(n: int, step: int = 1000) -> int:
        return ((n + step - 1) // step) * step

    def _choices(self, prods: list[Product], s: Session, notes) -> dict:
        s.shown, s.focus = [p.id for p in prods], None
        lines = ["พบหลายรุ่นที่ตรงกับคำค้น เลือกรุ่นที่ต้องการได้เลยครับ:"]
        lines += [f"• {p.name} — {baht(p.eff_price)}" for p in prods]
        chips = [self._spec_chip(p) for p in prods[:6]]
        return reply(self._join(notes, "\n".join(lines)), chips=chips)

    def _suitability(self, p: Product, uses: list[str], s: Session, notes) -> dict:
        s.focus, s.shown = p.id, [p.id]
        lines = [p.name]
        chips = []
        for u in [u for u in rules.USE_ORDER if u in uses]:
            label = rules.USE_CASES[u]["label"]
            if p.passes[u]:
                lines.append(f"✓ ผ่านเกณฑ์{label}ของร้าน — " + ", ".join(rules.highlights(p, u)))
            else:
                lines.append(f"✗ ยังไม่ผ่านเกณฑ์{label}ของร้าน — " + ", ".join(p.fails[u]))
                chips.append((f"หารุ่น{label}ราคาใกล้เคียง",
                              f"งบไม่เกิน {self._round_up(int(p.eff_price * OVER_BUDGET_RATIO)):,} บาท {USE_MESSAGES[u]}"))
        lines.append("(เกณฑ์ของร้านดูจากสเปกในข้อมูลสินค้า เช่น RAM, SSD, การ์ดจอ และจอ)")
        chips += [("ดูสเปกเต็ม", f"ดูสเปก {self._full(p)}"), ("เริ่มใหม่", "เริ่มใหม่")]
        return reply(self._join(notes, "\n".join(lines)), chips=chips)

    def _field_answer(self, p: Product, fields: list[str], s: Session, notes) -> dict:
        s.focus, s.shown = p.id, [p.id]
        lines = [p.name]
        missing = False
        for f in fields:
            if f in FIELD_ATTR:
                val = getattr(p, FIELD_ATTR[f])
                if val:
                    lines.append(f"{FIELD_LABELS[f]}: {val}")
                else:
                    lines.append(f"ข้อมูล{FIELD_LABELS[f]}ของรุ่นนี้ยังไม่มีในระบบครับ")
                    missing = True
            elif f == "upgrade":
                lines.append(f"ข้อมูลแรมในระบบ: {p.ram_detail or str(p.ram_gb) + 'GB'} · SSD {p.storage_label}")
                lines.append("ระบบไม่มีข้อมูลยืนยันว่าอัปเกรดแรม/SSD ได้หรือไม่ครับ")
                missing = True
            elif f == "touch":
                lines.append("เป็นจอสัมผัส (Touchscreen) ตามข้อมูลสินค้า" if "touch" in p.notes.lower()
                             else "ข้อมูลสินค้าไม่ได้ระบุว่าเป็นจอสัมผัสครับ")
            elif f == "office":
                lines.append({"yes": "มี Office Home 2024 ในเครื่องตามข้อมูลสินค้า"
                                     + (f" ({p.notes})" if "office" in p.notes.lower() else ""),
                              "no": f"รายการสินค้าไม่ได้ระบุว่ามี Office ครับ (ระบุเฉพาะ {p.os})"}
                             .get(p.office_included, "ยังไม่มีข้อมูลเรื่อง Office ของรุ่นนี้ในระบบครับ"))
            elif f == "os":
                lines.append(f"ระบบปฏิบัติการ: {p.os or 'ไม่มีข้อมูล'}")
            elif f == "color":
                color = p.model.split(" - ")[-1] if " - " in p.model else ""
                lines.append(f"สีของรุ่นนี้ตามข้อมูลสินค้า: {color}" if color else "ยังไม่มีข้อมูลสีของรุ่นนี้ในระบบครับ")
                lines.append("ระบบไม่มีข้อมูลสีอื่นของรุ่นนี้ครับ")
        if missing and self._contact_line():
            lines.append(self._contact_line())
        chips = [("ดูสเปกเต็ม", f"ดูสเปก {self._full(p)}"), ("เริ่มใหม่", "เริ่มใหม่")]
        return reply(self._join(notes, "\n".join(lines)), chips=chips)

    def _field_no_context(self, fields: list[str], notes) -> dict:
        lines = []
        for f in fields:
            if f in ("weight", "battery", "warranty", "stock"):
                lines.append(f"ระบบยังไม่มีข้อมูล{FIELD_LABELS[f]}ของสินค้าครับ")
        if not lines:
            lines.append("บอกชื่อรุ่นที่สนใจได้เลยครับ เช่น “msi modern 16s มี office ไหม”")
        elif self._contact_line():
            lines.append(self._contact_line())
        return reply(self._join(notes, "\n".join(lines)), chips=self._main_chips())

    def _product_promo(self, p: Product, s: Session, notes, t: str = "") -> dict:
        s.focus, s.shown = p.id, [p.id]
        if p.promo:
            text = (f"{p.name}\nราคาปกติ {baht(p.price)} ราคาโปร {baht(p.promo)} "
                    f"(ต่างกัน {baht(p.price - p.promo)}) ตามข้อมูลร้าน ณ วันที่ {self.data_date}")
        else:
            text = f"{p.name}\nราคา {baht(p.price)} (ไม่มีราคาโปร) ตามข้อมูลร้าน ณ วันที่ {self.data_date}"
        claimed = [int(x.replace(",", "")) for x in
                   re.findall(r"(?:ราคา|ขาย|เหลือ|แค่)\s*(\d[\d,]*)(?![\d.a-z])|(\d[\d,]*)\s*(?:บาท|฿)", t) for x in x if x]
        claimed += [int(float(x) * 1000) for x in re.findall(r"(\d+(?:\.\d+)?)\s*k\b", t)]
        wrong = [c for c in claimed if c > 0 and c not in (p.price, p.promo)]
        if wrong:
            text += f"\nราคาที่ถามมา ({wrong[0]:,} บาท) ไม่ตรงกับข้อมูลของร้านครับ"
        return reply(self._join(notes, text), chips=[("ดูสเปกเต็ม", f"ดูสเปก {self._full(p)}"), ("เริ่มใหม่", "เริ่มใหม่")])

    def _promos(self, s: Session, notes) -> dict:
        pool = [p for p in self.catalog.products if p.promo]
        scope = []
        if s.budget:
            pool = self._in_budget(pool, s.budget)
            scope.append(s.budget.label())
        if s.use:
            pool = [p for p in pool if p.passes[s.use]]
            scope.append(rules.USE_CASES[s.use]["label"])
        scope_txt = f" ({', '.join(scope)})" if scope else ""
        if not pool:
            return reply(self._join(notes, f"ยังไม่มีรุ่นที่มีราคาโปรในข้อมูลร้าน{scope_txt}ครับ"), chips=self._main_chips())
        pool.sort(key=lambda p: -(p.price - p.promo))
        top = pool[:5]
        lines = [f"รุ่นที่มีราคาโปรในข้อมูลร้าน{scope_txt}: {len(pool)} รุ่น — ต่างจากราคาปกติมากที่สุด {len(top)} อันดับ:"]
        lines += [f"• {p.name}: {p.price:,} → {baht(p.promo)} (ต่างกัน {baht(p.price - p.promo)})" for p in top]
        lines.append(f"ราคาตามข้อมูลร้าน ณ วันที่ {self.data_date}")
        s.shown, s.focus = [p.id for p in top], None
        chips = [self._spec_chip(p) for p in top[:4]] + [("แนะนำตามงบ", "แนะนำตามงบ")]
        return reply(self._join(notes, "\n".join(lines)), chips=chips)

    # ------------------------------------------------------------------ compare
    def _compare_start(self, s: Session, notes, prefix: str = "") -> dict:
        s.awaiting = "compare_budget"
        text = (f"{prefix}\nเลือกช่วงงบของรุ่นที่อยากเทียบก่อนครับ (กดปุ่มช่วงงบด้านล่าง หรือกรอกช่วงงบเองในช่อง “กำหนดช่วงงบเอง”) "
                f"แล้ว{self.bot_name}จะแสดงรายชื่อรุ่นในงบนั้นให้ติ๊กเลือก 2 รุ่น\n"
                "หรือพิมพ์ชื่อรุ่นเทียบเองก็ได้ เช่น “เทียบ LENOVO IDEAPAD SLIM 5 กับ MSI MODERN 16S”")
        chips = ([("เทียบ 2 รุ่นแรก", "เทียบ 2 รุ่นแรก")] if len(s.shown) >= 2 else []) + BUDGET_CHIPS
        return reply(self._join(notes, text), chips=chips, form=self._budget_form())

    def _budget_form(self, mode: str = "compare") -> dict:
        """ช่องกรอกช่วงงบเอง (ตั้งแต่/ถึง) หน้าเว็บจะส่งกลับมาเป็นข้อความตาม templates
        mode="compare" ใช้ตอนเลือกรุ่นมาเทียบ, mode="recommend" ใช้ตอนแนะนำตามงบ/ดูภาพรวม"""
        prices = [p.eff_price for p in self.catalog.products]
        lead = "เทียบรุ่น " if mode == "compare" else ""
        return {
            "title": "กำหนดช่วงงบเอง",
            "lo_label": "ตั้งแต่ (บาท)",
            "hi_label": "ถึง (บาท)",
            "button": "แสดงรุ่นในช่วงนี้" if mode == "compare" else "ใช้ช่วงงบนี้",
            "hint": f"ราคาในร้านอยู่ระหว่าง {min(prices):,}–{max(prices):,} บาท · เว้นว่างได้ 1 ช่อง",
            "min": MIN_BUDGET,
            "max": MAX_BUDGET,
            "templates": {
                "both": lead + "งบ {lo}-{hi} บาท",
                "lo": lead + "งบ {lo} บาทขึ้นไป",
                "hi": lead + "งบไม่เกิน {hi} บาท",
            },
        }

    def _compare_help(self, s: Session, notes) -> dict:
        return self._compare_start(s, notes, prefix="ยังหารุ่นที่จะเทียบไม่ครบ 2 รุ่นครับ")

    def _picker_item(self, p: Product) -> dict:
        """หนึ่งแถวในตารางสเปกสำหรับติ๊กเลือก (ข้อมูลทุกช่องมาจาก products.csv)"""
        return {
            "value": self._full(p),
            "label": self._full(p),
            "price": p.eff_price,
            "regular": p.price if p.promo else None,
            "tags": p.suitable_labels(),
            "gpu_kind": "การ์ดจอแยก" if p.gpu_type == "dedicated" else "ในตัว",
            "cells": {
                "model": self._full(p),
                "cpu": p.cpu,
                "ram": f"{p.ram_gb}GB",
                "ssd": p.storage_label,
                "gpu": p.gpu,
                "screen": p.screen_label,
                "office": self._office_txt(p),
            },
            # ค่าสำหรับเรียงลำดับเมื่อกดหัวคอลัมน์ (CPU/การ์ดจอเรียงตามระดับในเกณฑ์ร้าน)
            "sort": {
                "price": p.eff_price,
                "cpu": rules.cpu_tier(p.cpu),
                "ram": p.ram_gb,
                "ssd": p.storage_gb,
                "gpu": rules.gpu_tier(p.gpu, p.gpu_type),
                "screen": p.screen_inch,
            },
        }

    def _compare_picker(self, b: Budget, s: Session, notes) -> dict:
        items = sorted(self._in_budget(self.catalog.products, b), key=lambda p: (p.eff_price, p.id))
        s.budget = b
        if len(items) < 2:
            s.awaiting = "compare_budget"
            return reply(self._join(notes, f"{b.label()} มีโน้ตบุ๊กในร้านไม่ถึง 2 รุ่น จึงยังเทียบไม่ได้ครับ "
                                           "ลองเลือกช่วงงบอื่น หรือขยายช่วงงบในช่องด้านล่าง"),
                         chips=BUDGET_CHIPS, form=self._budget_form())
        s.awaiting = None
        shown = items[:PICKER_MAX]
        picker = {
            "title": f"{b.label()} · {len(items)} รุ่น",
            "max": 2,
            "button": "เทียบรุ่นที่เลือก",
            "template": "เทียบ {0} กับ {1}",
            "columns": [
                {"key": "model", "label": "รุ่น"},
                {"key": "price", "label": "ราคา", "sort": True},
                {"key": "cpu", "label": "CPU", "sort": True},
                {"key": "ram", "label": "RAM", "sort": True},
                {"key": "ssd", "label": "SSD", "sort": True},
                {"key": "gpu", "label": "การ์ดจอ", "sort": True},
                {"key": "screen", "label": "จอ", "sort": True},
                {"key": "office", "label": "Office"},
                {"key": "suit", "label": "เหมาะกับ"},
            ],
            "filters": [rules.USE_CASES[u]["label"] for u in rules.USE_ORDER],
            "items": [self._picker_item(p) for p in shown],
        }
        text = (f"{b.label()} มีโน้ตบุ๊กในร้าน {len(items)} รุ่น (เรียงจากราคาถูก) "
                "ดูสเปกในตาราง (กดหัวคอลัมน์เพื่อเรียงลำดับ หรือกดปุ่มกรองตามการใช้งาน เลือกได้หลายข้อ เช่น เขียนโปรแกรม + เล่นเกม) "
                "แล้วติ๊กเลือก 2 รุ่นที่อยากเทียบ กดปุ่ม “เทียบรุ่นที่เลือก” ได้เลยครับ")
        if len(items) > PICKER_MAX:
            text += f"\nแสดง {PICKER_MAX} รุ่นแรก ถ้าไม่เจอรุ่นที่ต้องการ กด “เปลี่ยนช่วงงบ” แล้วกำหนดช่วงงบให้แคบลง"
        return reply(self._join(notes, text), picker=picker,
                     chips=[("เปลี่ยนช่วงงบ", "เทียบรุ่น"), ("แนะนำตามงบ", "แนะนำตามงบ")])

    def _compare(self, t: str, s: Session, notes) -> Optional[dict]:
        ids = nlu.find_product_ids(t)
        prods = [p for p in (self.catalog.get(i) for i in ids) if p]
        groups = []  # (คำที่พิมพ์, รุ่นที่เลือก, รุ่นย่อยทั้งหมดที่ตรง)
        if len(prods) < 2:
            body = re.sub(nlu.COMPARE.pattern, " ", t)
            for part in re.split(r"กับ|\bvs\.?\b|และ|,|/|หรือ", body):
                if nlu.PRODUCT_ID.search(part) or not re.search(r"[a-z]", part):
                    continue
                matches = self.catalog.find_series(part) or self.catalog.search(part)
                if matches and matches[0] not in prods:
                    prods.append(matches[0])
                    groups.append((part.strip(), matches[0], matches))
        if len(prods) < 2 and len(s.shown) >= 2 and (nlu.COMPARE_FIRST_TWO.search(t) or (not groups and not ids)):
            prods = [self.catalog.get(i) for i in s.shown[:2]]
            groups = []
        if len(prods) < 2:
            return self._compare_help(s, notes)
        a, b = prods[0], prods[1]
        rows = [
            ["รหัส", a.id, b.id],
            ["ราคา", self._price_txt(a), self._price_txt(b)],
            ["CPU", a.cpu, b.cpu],
            ["RAM", f"{a.ram_gb}GB", f"{b.ram_gb}GB"],
            ["SSD", a.storage_label, b.storage_label],
            ["การ์ดจอ", self._gpu_txt(a), self._gpu_txt(b)],
            ["จอ", a.screen_label, b.screen_label],
            ["Office", self._office_txt(a), self._office_txt(b)],
            ["เหมาะกับ (เกณฑ์ร้าน)", ", ".join(a.suitable_labels()) or "-", ", ".join(b.suitable_labels()) or "-"],
        ]
        na, nb = self._pair(a, b)
        diffs = []
        if a.eff_price != b.eff_price:
            cheap = a if a.eff_price < b.eff_price else b
            diffs.append(f"ราคาต่างกัน {baht(abs(a.eff_price - b.eff_price))} ({na if cheap is a else nb} ถูกกว่า)")
        if a.gpu_type != b.gpu_type:
            dg = a if a.gpu_type == "dedicated" else b
            diffs.append(f"{na if dg is a else nb} มีการ์ดจอแยก ({dg.gpu}) อีกรุ่นใช้การ์ดจอในตัว")
        elif a.gpu != b.gpu:
            diffs.append(f"การ์ดจอต่างกัน: {na} {a.gpu} / {nb} {b.gpu}")
        if a.ram_gb != b.ram_gb:
            diffs.append(f"RAM: {na} {a.ram_gb}GB / {nb} {b.ram_gb}GB")
        if a.storage_gb != b.storage_gb:
            diffs.append(f"SSD: {na} {a.storage_label} / {nb} {b.storage_label}")
        for u in rules.USE_ORDER:
            if a.passes[u] != b.passes[u]:
                yes = a if a.passes[u] else b
                diffs.append(f"เฉพาะ {na if yes is a else nb} ที่ผ่านเกณฑ์{rules.USE_CASES[u]['label']}")
        variant_lines, alt_chips = [], []
        for part, picked, matches in groups:
            if len(matches) < 2 or picked not in (a, b):
                continue
            other = b if picked is a else a
            cheapest = picked.eff_price == min(m.eff_price for m in matches)
            others = [m for m in matches if m is not picked][:4]
            variant_lines.append(
                f"“{part.upper()}” มี {len(matches)} รุ่นย่อยในร้าน เลือก {self._full(picked)}"
                + (" (ราคาถูกที่สุด)" if cheapest else "") + " มาเทียบ รุ่นย่อยอื่น: "
                + ", ".join(f"{m.model.split(' - ')[0]} ({m.cpu}, RAM {m.ram_gb}GB, {baht(m.eff_price)})" for m in others))
            alt_chips += [(f"{m.model.split(' - ')[0]} · {m.eff_price:,} บาท",
                           f"เทียบ {self._full(m)} กับ {self._full(other)}") for m in others]
        text = (f"เทียบ {self._full(a)} กับ {self._full(b)}\n"
                + ("ความต่างหลัก ๆ:\n" + "\n".join(f"• {d}" for d in diffs) if diffs else "สองรุ่นนี้สเปกหลักใกล้เคียงกันครับ")
                + ("\n" + "\n".join(variant_lines) if variant_lines else "")
                + f"\nราคาตามข้อมูลร้าน ณ วันที่ {self.data_date}")
        s.shown, s.focus, s.awaiting = [a.id, b.id], None, None
        chips = alt_chips[:4] + [self._spec_chip(a), self._spec_chip(b), ("เทียบรุ่นอื่น", "เทียบรุ่น"),
                                 ("เริ่มใหม่", "เริ่มใหม่")]
        return reply(self._join(notes, text), compare={"headers": ["", a.name, b.name], "rows": rows}, chips=chips)

    def _price_txt(self, p: Product) -> str:
        return f"{p.price:,} → {baht(p.promo)} (ราคาโปร)" if p.promo else baht(p.price)

    @staticmethod
    def _gpu_txt(p: Product) -> str:
        return f"{p.gpu} ({'แยก' if p.gpu_type == 'dedicated' else 'ในตัว'})"

    @staticmethod
    def _office_txt(p: Product) -> str:
        return {"yes": "มี", "no": "ไม่ได้ระบุ"}.get(p.office_included, "ไม่มีข้อมูล")

    # ------------------------------------------------------------------ policies / safety
    def _policy_topic(self, t: str) -> Optional[str]:
        for key, pol in self.policies.items():
            if pol.get("label") and nlu.norm(pol["label"]) in t:
                return key
            for kw in pol.get("keywords", []):
                if nlu.norm(kw) in t:
                    return key
        return None

    def _policy_menu(self, notes) -> dict:
        labels = [pol["label"] for pol in self.policies.values() if (pol.get("answer") or "").strip()]
        text = "อยากทราบนโยบายเรื่องไหนครับ? กดเลือกด้านล่าง หรือพิมพ์คำถามได้เลย เช่น “ผ่อนได้ไหม”"
        return reply(self._join(notes, text), chips=[(l, l) for l in labels])

    def _policy(self, topic: str, t: str, s: Session, notes) -> dict:
        pol = self.policies[topic]
        ans = (pol.get("answer") or "").strip()
        lines = []
        if topic == "warranty":
            prods, _ = self._resolve_products(t, s)
            p = prods[0] if len(prods) == 1 else (self.catalog.get(s.focus) if s.focus else None)
            if p and not p.warranty_years:
                lines.append(f"ระบบยังไม่มีข้อมูลระยะประกันของ {p.name} ครับ")
        if ans:
            lines.append(f"{pol['label']}: {ans}")
        else:
            lines.append(f"ร้านยังไม่มีข้อมูลเรื่อง{pol['label']}ในระบบครับ {self.bot_name}จึงตอบแทนร้านไม่ได้")
            if self._contact_line():
                lines.append(self._contact_line())
        return reply(self._join(notes, "\n".join(lines)), chips=[("นโยบายอื่น", "นโยบายร้าน"), ("แนะนำตามงบ", "แนะนำตามงบ")])

    def _policy_unknown(self, notes) -> dict:
        text = "\n".join(x for x in [
            f"ร้านยังไม่มีข้อมูลนโยบายเรื่องนี้ในระบบครับ {self.bot_name}จึงตอบแทนร้านไม่ได้ "
            "(ตอบได้เฉพาะนโยบายที่ร้านกำหนดไว้ กด “นโยบายร้าน” เพื่อดูหัวข้อทั้งหมด)",
            self._contact_line()] if x)
        return reply(self._join(notes, text), chips=[("นโยบายร้าน", "นโยบายร้าน"), ("แนะนำตามงบ", "แนะนำตามงบ")])

    def _refuse_injection(self, t: str, s: Session, notes) -> dict:
        lines = [f"{self.bot_name}เป็นผู้ช่วยอัตโนมัติของร้าน{self.shop_name} ทำงานตามกฎของร้านเท่านั้นครับ "
                 "ไม่สามารถเปลี่ยนบทบาท เปิดโหมดพิเศษ เปิดเผยการตั้งค่าระบบ หรือรับคำสั่งจากผู้ที่อ้างว่าเป็นพนักงาน/ผู้จัดการผ่านแชทได้"]
        if nlu.NEGOTIATE.search(t) or re.search(r"ลด|ส่วนลด|ฟรี|ราคาพิเศษ", t):
            lines.append("และไม่สามารถให้ส่วนลดหรือราคาพิเศษได้ ราคาที่แจ้งได้มีเฉพาะราคาและราคาโปรในข้อมูลของร้านเท่านั้นครับ")
        lines.append("ถ้าต้องการให้ช่วยเลือกโน้ตบุ๊ก บอกงบกับการใช้งานได้เลยครับ")
        return reply(self._join(notes, "\n".join(lines)), chips=self._main_chips())

    def _refuse_pii(self, notes) -> dict:
        lines = [f"{self.bot_name}ไม่มีข้อมูลลูกค้าหรือประวัติการซื้อของใคร และไม่สามารถเปิดเผยข้อมูลของบุคคลอื่นได้ครับ"]
        privacy = self._policy_text("privacy")
        if privacy:
            lines.append(f"นโยบายข้อมูลส่วนบุคคลของร้าน: {privacy}")
        if self._contact_line():
            lines.append(self._contact_line())
        return reply(self._join(notes, "\n".join(lines)), chips=self._main_chips())

    def _order(self, notes) -> dict:
        lines = [f"{self.bot_name}ไม่มีข้อมูลคำสั่งซื้อหรือการจัดส่งของลูกค้าในระบบครับ"]
        ordering = self._policy_text("ordering")
        if ordering:
            lines.append(ordering)
        if self._contact_line():
            lines.append(self._contact_line())
        return reply(self._join(notes, "\n".join(lines)), chips=self._main_chips())

    def _negotiate(self, t: str, s: Session, notes) -> dict:
        lines = [f"{self.bot_name}ไม่สามารถให้ส่วนลด อนุมัติราคาพิเศษ หรือรับปากเรื่องของแถมได้ครับ "
                 "ราคาที่แจ้งได้มีเฉพาะราคาและราคาโปรที่อยู่ในข้อมูลของร้านเท่านั้น"]
        if "แถม" in t:
            lines.append("ระบบยังไม่มีข้อมูลของแถมครับ")
        prods, _ = self._resolve_products(t, s)
        p = prods[0] if len(prods) == 1 else (self.catalog.get(s.focus) if s.focus else None)
        if p:
            lines.append(f"{p.name}: " + (f"ราคาปกติ {baht(p.price)} ราคาโปร {baht(p.promo)}" if p.promo
                                                 else f"ราคา {baht(p.price)} (ไม่มีราคาโปรในระบบ)"))
        pricing = self._policy_text("pricing")
        if pricing:
            lines.append(f"นโยบายราคาของร้าน: {pricing}")
        if self._contact_line():
            lines.append(self._contact_line())
        chips = [("ดูรุ่นที่มีราคาโปร", "ดูรุ่นที่มีราคาโปร"), ("แนะนำตามงบ", "แนะนำตามงบ")]
        return reply(self._join(notes, "\n".join(lines)), chips=chips)

    def _handoff(self, notes) -> dict:
        if self.contact:
            text = f"ได้เลยครับ ติดต่อพนักงานของร้าน{self.shop_name} ได้ที่: {self.contact}"
        else:
            text = (f"ขออภัยครับ ร้าน{self.shop_name} ไม่มีช่องทางติดต่อพนักงานผ่านระบบนี้\n"
                    f"{self.bot_name}ช่วยได้เรื่องเลือกโน้ตบุ๊กตามงบ ดูสเปก เทียบรุ่น และตอบนโยบายร้านครับ")
        return reply(self._join(notes, text), chips=self._main_chips())

    def _not_sold(self, label: str, t: str, s: Session, notes, budget_in_msg, uses_in_msg) -> dict:
        """สินค้าที่ร้านไม่มีขาย: บอกว่าไม่มีอย่างเดียว ไม่เสนอรุ่นหรือแบรนด์อื่นแทน"""
        s.awaiting = None
        return reply(self._join(notes, f"ร้าน{self.shop_name} ไม่มี {label} ในรายการสินค้าครับ"),
                     chips=self._main_chips())

    def _no_sales_data(self, notes) -> dict:
        text = (f"ระบบไม่มีข้อมูลยอดขายหรือความนิยมของสินค้าครับ {self.bot_name}จึงบอกไม่ได้ว่ารุ่นไหนขายดี\n"
                "แต่ช่วยคัดรุ่นที่สเปกดีที่สุดตามงบและการใช้งานให้ได้ บอกงบได้เลยครับ")
        return reply(self._join(notes, text), chips=self._main_chips())

    def _other_store(self, notes) -> dict:
        lines = [f"{self.bot_name}ไม่มีข้อมูลราคาหรือสินค้าของร้านอื่น จึงเปรียบเทียบให้ไม่ได้ครับ"]
        pricing = self._policy_text("pricing")
        if pricing:
            lines.append(f"นโยบายราคาของร้าน: {pricing}")
        return reply(self._join(notes, "\n".join(lines)), chips=self._main_chips())

    def _out_of_scope(self, notes) -> dict:
        text = (f"เรื่องนี้อยู่นอกขอบเขตที่{self.bot_name}ช่วยได้ครับ "
                f"{self.bot_name}ตอบได้เฉพาะเรื่องโน้ตบุ๊กและนโยบายของร้าน{self.shop_name} "
                "เช่น “งบ 25,000 ใช้เรียน” หรือ “ดูสเปก msi modern 16s”")
        return reply(self._join(notes, text), chips=self._main_chips())

    def _model_not_found(self, tok: str, notes) -> dict:
        text = (f"ไม่พบรุ่น “{tok.upper()}” ในข้อมูลสินค้าของร้านครับ "
                "ลองพิมพ์ชื่อรุ่นให้ละเอียดขึ้น เช่น “msi modern 16s” "
                f"หรือบอกงบกับการใช้งานให้{self.bot_name}ช่วยเลือกก็ได้ครับ")
        return reply(self._join(notes, text), chips=self._main_chips())
