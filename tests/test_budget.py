import pytest

from bot.budget import parse_budget

CASES = [
    ("งบ 20000", None, 20000),
    ("20,000 บาท", None, 20000),
    ("20k", None, 20000),
    ("2 หมื่น", None, 20000),
    ("สองหมื่น", None, 20000),
    ("หมื่นห้า", None, 15000),
    ("สองหมื่นห้า", None, 25000),
    ("สองหมื่นห้าพัน", None, 25000),
    ("2หมื่น5", None, 25000),
    ("2.5 หมื่น", None, 25000),
    ("25k", None, 25000),
    ("สามหมื่นสอง", None, 32000),
    ("๒๐๐๐๐", None, 20000),
    ("งบ2หมื่นอ่ะ", None, 20000),
    ("ไม่เกิน 18000", None, 18000),
    ("ต่ำกว่า 3 หมื่น", None, 30000),
    ("15-20k", 15000, 20000),
    ("15k-20k", 15000, 20000),
    ("ระหว่าง 15000 ถึง 20000", 15000, 20000),
    ("15,000 - 20,000 บาท", 15000, 20000),
    ("2-3 หมื่น", 20000, 30000),
    ("หมื่นห้าถึงสองหมื่น", 15000, 20000),
    ("3 หมื่นขึ้นไป", 30000, None),
    ("ตั้งแต่ 40000", 40000, None),
    ("RTX 4050 งบ 35000", None, 35000),
    ("จอ 15.6 นิ้ว งบ 2 หมื่น", None, 20000),
]


@pytest.mark.parametrize("text,lo,hi", CASES)
def test_budget_values(text, lo, hi):
    b = parse_budget(text)
    assert b is not None, text
    assert (b.min, b.max) == (lo, hi), text


@pytest.mark.parametrize("text", [
    "NB012", "0812345678", "081-234-5678", "เครื่อง 144Hz", "ram 16gb", "i5-1334U",
    "อยากได้จอ 4k", "ร้านแสนดี", "rtx5060 ราคาเท่าไหร่", "สวัสดีครับ",
])
def test_not_a_budget(text):
    assert parse_budget(text) is None, text


def test_cheapest_and_unlimited():
    assert parse_budget("ขอรุ่นถูกที่สุด").cheapest
    assert parse_budget("ไม่จำกัดงบ").unlimited


@pytest.mark.parametrize("text,lo,hi", [
    ("งบ 100,000-200,000 บาท", 100000, 200000),
    ("งบ 3000-500000", 3000, 500000),
    ("เทียบรุ่น งบ 30,000-100,000 บาท", 30000, 100000),
    ("งบ 150000-169990", 150000, 169990),
])
def test_six_digit_ranges_are_not_mistaken_for_phone_numbers(text, lo, hi):
    b = parse_budget(text)
    assert b and (b.min, b.max) == (lo, hi)


@pytest.mark.parametrize("text", ["โทร 081-234-5678 งบ 25000", "เบอร์ 0812345678 งบ 25000", "02 123 4567 งบ 25000"])
def test_phone_numbers_still_ignored(text):
    b = parse_budget(text)
    assert b and b.max == 25000 and b.min is None
