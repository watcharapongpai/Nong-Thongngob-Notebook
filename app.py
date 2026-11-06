"""เว็บแชทบอท "น้องตรงงบ" — ร้านตรงงบ Notebook

รัน:  python app.py   แล้วเปิด http://127.0.0.1:8000
"""
import os
import re
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from bot import vision
from bot.engine import ChatBot

BASE = Path(__file__).resolve().parent
SID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

app = Flask(__name__)
app.json.ensure_ascii = False
app.config["MAX_CONTENT_LENGTH"] = vision.MAX_BYTES + 512 * 1024  # รูปไม่เกิน 5 MB + ข้อความ
app.config["ANALYZER"] = vision.ClipRelevance()  # ตัวตรวจรูป (ชุดทดสอบเปลี่ยนเป็นตัวจำลองได้)

bot = ChatBot.from_files(BASE / "data" / "products.csv", BASE / "data" / "shop_info.json")


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'"
    )
    return resp


@app.get("/")
def index():
    return render_template("index.html", shop_name=bot.shop_name, bot_name=bot.bot_name,
                           data_date=bot.data_date)


@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    sid = str(data.get("session_id", ""))
    if not SID_RE.match(sid):
        return jsonify(error="invalid session"), 400
    if data.get("event") == "start":
        return jsonify(bot.welcome(sid))
    message = data.get("message", "")
    if not isinstance(message, str):
        return jsonify(error="invalid message"), 400
    # ไม่มีการบันทึกข้อความแชทลงไฟล์หรือฐานข้อมูล
    return jsonify(bot.reply(sid, message))


@app.post("/api/chat-image")
def chat_image():
    sid = str(request.form.get("session_id", ""))
    if not SID_RE.match(sid):
        return jsonify(error="invalid session"), 400
    caption = str(request.form.get("message", ""))
    file = request.files.get("image")
    data = file.read(vision.MAX_BYTES + 1) if file else b""
    try:
        image = vision.load_image(data)  # ตรวจชนิด/ขนาดไฟล์ รูปอยู่ในหน่วยความจำเท่านั้น ไม่บันทึกลงดิสก์
    except vision.ImageError as e:
        return jsonify(bot.reply_image(sid, None, caption, error=str(e)))
    try:
        analysis = app.config["ANALYZER"].analyze(image)
    except vision.VisionUnavailable as e:
        app.logger.warning("ระบบตรวจรูปยังไม่พร้อม: %s", e)
        analysis = None
    return jsonify(bot.reply_image(sid, analysis, caption))


@app.errorhandler(413)
def too_large(_e):
    return jsonify(text="รูปใหญ่เกินไปครับ รองรับไฟล์ไม่เกิน 5 MB", cards=[], compare=None,
                   quick_replies=[], image=None), 413


@app.get("/healthz")
def healthz():
    return jsonify(ok=True, products=len(bot.catalog.products), data_date=bot.data_date,
                   vision_libraries=vision.ClipRelevance.libraries_available())


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    shown = "127.0.0.1" if host in ("0.0.0.0", "127.0.0.1") else host
    print(f"\n  {bot.bot_name} พร้อมแล้ว — เปิดเบราว์เซอร์ที่ http://{shown}:{port}")
    if vision.ClipRelevance.libraries_available():
        print("  ระบบตรวจรูป: พร้อม (รูปแรกอาจช้า เพราะต้องโหลดโมเดล)\n")
    else:
        print("  ระบบตรวจรูป: ยังไม่เปิด — ติดตั้งตาม README หัวข้อ 'ส่งรูปเพื่อสอบถาม'\n")
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
