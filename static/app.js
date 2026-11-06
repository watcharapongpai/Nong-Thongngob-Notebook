// หน้าแชทของน้องตรงงบ — แสดงผลด้วย textContent เท่านั้น (กันโค้ดแปลกปลอมจากข้อความ)
(() => {
  const chat = document.getElementById("chat");
  const chips = document.getElementById("chips");
  const form = document.getElementById("composer");
  const input = document.getElementById("msg");
  const sendBtn = document.getElementById("send");
  const restartBtn = document.getElementById("restart");
  const fileInput = document.getElementById("file");
  const attachBtn = document.querySelector(".attach");
  const preview = document.getElementById("preview");
  const previewImg = document.getElementById("previewImg");
  const previewName = document.getElementById("previewName");
  const clearImg = document.getElementById("clearImg");
  const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
  const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"];
  let pendingFile = null;
  let pendingUrl = null;

  const newId = () =>
    (window.crypto && crypto.randomUUID)
      ? crypto.randomUUID()
      : "s-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  let sessionId = newId();
  let busy = false;

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  };
  const baht = (n) => Number(n).toLocaleString("en-US") + " บาท";
  const scrollDown = () => { chat.scrollTop = chat.scrollHeight; };

  function addUser(text) {
    const row = el("div", "row user");
    row.appendChild(el("div", "bubble", text));
    chat.appendChild(row);
    scrollDown();
  }

  // ฟองข้อความของลูกค้าที่มีรูป คืนค่ากล่องไว้ใส่ป้ายคะแนนความเกี่ยวข้องภายหลัง
  function addUserImage(url, text) {
    const row = el("div", "row user");
    const stack = el("div", "ustack");
    const img = el("img", "uimg");
    img.src = url;
    img.alt = "รูปที่ส่ง";
    img.addEventListener("load", scrollDown);
    stack.appendChild(img);
    if (text) stack.appendChild(el("div", "bubble", text));
    row.appendChild(stack);
    chat.appendChild(row);
    scrollDown();
    return stack;
  }

  function setPending(file) {
    if (!file) return;
    if (!IMAGE_TYPES.includes(file.type)) {
      renderBot({ text: "รองรับเฉพาะรูป JPG, PNG, WEBP หรือ GIF ครับ", quick_replies: [] });
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      renderBot({ text: "รูปใหญ่เกินไปครับ รองรับไฟล์ไม่เกิน 5 MB", quick_replies: [] });
      return;
    }
    pendingFile = file;
    pendingUrl = URL.createObjectURL(file);
    previewImg.src = pendingUrl;
    previewName.textContent = file.name || "รูปจากคลิปบอร์ด";
    preview.hidden = false;
    input.focus();
  }

  function clearPending(revoke) {
    if (revoke && pendingUrl) URL.revokeObjectURL(pendingUrl);
    pendingFile = null;
    pendingUrl = null;
    fileInput.value = "";
    preview.hidden = true;
  }

  function botRow() {
    const row = el("div", "row bot");
    row.appendChild(el("div", "avatar", "ตง"));
    const stack = el("div", "stack");
    row.appendChild(stack);
    chat.appendChild(row);
    return stack;
  }

  function showTyping() {
    const row = el("div", "row bot typing");
    row.appendChild(el("div", "avatar", "ตง"));
    const b = el("div", "bubble");
    for (let i = 0; i < 3; i++) b.appendChild(el("span"));
    row.appendChild(b);
    chat.appendChild(row);
    scrollDown();
    return row;
  }

  function renderCard(c) {
    const card = el("article", "pcard" + (c.actions && c.actions.length ? "" : " detail"));
    const top = el("div", "ptop");
    top.appendChild(el("span", "pid", "รหัส " + c.id));
    if (c.label) top.appendChild(el("span", "badge warn", c.label));
    card.appendChild(top);
    card.appendChild(el("h4", "pname", c.name));

    const price = el("div", "price");
    if (c.promo) {
      price.appendChild(el("span", "now", baht(c.promo)));
      price.appendChild(el("s", null, baht(c.price)));
      price.appendChild(el("span", "tag", "ราคาโปร"));
    } else {
      price.appendChild(el("span", "now", baht(c.price)));
    }
    card.appendChild(price);

    const specs = el("ul", "specs");
    (c.specs || []).forEach((s) => specs.appendChild(el("li", null, s)));
    card.appendChild(specs);

    if (c.reasons && c.reasons.length) {
      const why = el("div", "why");
      why.appendChild(el("div", "label", "จุดเด่นสำหรับการใช้งานนี้"));
      const ul = el("ul");
      c.reasons.forEach((r) => ul.appendChild(el("li", null, r)));
      why.appendChild(ul);
      card.appendChild(why);
    }
    if (c.notes && c.notes.length) {
      const ul = el("ul", "caveats");
      c.notes.forEach((r) => ul.appendChild(el("li", null, r)));
      card.appendChild(ul);
    }
    if (c.suitable && c.suitable.length) {
      const suit = el("div", "suit");
      suit.appendChild(el("div", "label", "ผ่านเกณฑ์ร้านสำหรับ"));
      const box = el("div", "chips-mini");
      c.suitable.forEach((s) => box.appendChild(el("span", null, s)));
      suit.appendChild(box);
      card.appendChild(suit);
    }
    (c.actions || []).forEach((a) => {
      const b = el("button", "link", a.label + " →");
      b.type = "button";
      b.addEventListener("click", () => send(a.message));
      card.appendChild(b);
    });
    return card;
  }

  function renderCompare(cmp) {
    const wrap = el("div", "cmp");
    const table = el("table");
    const thead = el("thead");
    const hr = el("tr");
    cmp.headers.forEach((h) => hr.appendChild(el("th", null, h)));
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = el("tbody");
    cmp.rows.forEach((r) => {
      const tr = el("tr");
      r.forEach((cell) => tr.appendChild(el("td", null, cell)));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  // ตารางสเปกให้ติ๊กเลือกรุ่น (เรียงตามหัวคอลัมน์ และกรองตามการใช้งานได้) แล้วส่งเป็นข้อความชื่อรุ่น
  const CELL_CLASS = { model: "pk-model", cpu: "pk-cpu", ram: "nw", ssd: "nw", office: "nw", gpu: "pk-gpu", screen: "pk-screen" };

  function renderPicker(pk) {
    const box = el("div", "picker");
    const head = el("div", "pk-head");
    head.appendChild(el("div", "pk-title", pk.title));
    const filterBar = el("div", "pk-filters");
    head.appendChild(filterBar);
    const countLine = el("div", "pk-count");
    head.appendChild(countLine);
    head.appendChild(el("div", "pk-hint", "เลื่อนตารางไปทางซ้าย-ขวาเพื่อดูสเปกครบทุกช่อง"));
    box.appendChild(head);

    const wrap = el("div", "pk-wrap");
    const table = el("table", "pk-table");
    const thead = el("thead");
    const htr = el("tr");
    const tbody = el("tbody");
    table.append(thead, tbody);
    wrap.appendChild(table);
    box.appendChild(wrap);

    const btn = el("button", "pk-submit");
    btn.type = "button";
    box.appendChild(btn);

    const chosen = [];
    const filters = new Set(); // เลือกได้หลายเกณฑ์ แสดงเฉพาะรุ่นที่ผ่านทุกเกณฑ์ที่เลือก
    let sortKey = null;
    let sortDir = 1;
    let locked = false;

    const priceCell = (it) => {
      const td = el("td", "pk-price nw");
      td.appendChild(el("div", "now", baht(it.price)));
      if (it.regular) td.appendChild(el("s", null, baht(it.regular)));
      return td;
    };

    function updateButton() {
      btn.disabled = locked || chosen.length !== pk.max;
      btn.textContent = `${pk.button} (${chosen.length}/${pk.max})`;
    }

    function renderRows() {
      let rows = pk.items.filter((it) => [...filters].every((f) => it.tags.includes(f)));
      countLine.textContent = filters.size
        ? `ผ่านเกณฑ์ ${[...filters].join(" + ")}: ${rows.length} จาก ${pk.items.length} รุ่น`
        : `แสดงทั้งหมด ${pk.items.length} รุ่น · เลือกเกณฑ์ได้หลายข้อ`;
      if (sortKey) rows = [...rows].sort((a, b) => (a.sort[sortKey] - b.sort[sortKey]) * sortDir || a.price - b.price);
      tbody.replaceChildren();
      if (!rows.length) {
        const tr = el("tr");
        const td = el("td", "pk-empty",
          filters.size > 1 ? "ไม่มีรุ่นที่ผ่านทุกเกณฑ์ที่เลือกในงบนี้ ลองเอาเกณฑ์ออกบางข้อ หรือเปลี่ยนช่วงงบ"
                           : "ไม่มีรุ่นที่ผ่านเกณฑ์นี้ในงบที่เลือก");
        td.colSpan = pk.columns.length + 1;
        tr.appendChild(td);
        tbody.appendChild(tr);
      }
      rows.forEach((it) => {
        const tr = el("tr");
        const on = chosen.includes(it.value);
        if (on) tr.classList.add("on");
        const tdc = el("td", "pk-check");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = on;
        cb.disabled = locked || (!on && chosen.length >= pk.max);
        cb.setAttribute("aria-label", "เลือก " + it.label);
        tdc.appendChild(cb);
        tr.appendChild(tdc);
        pk.columns.forEach((col) => {
          if (col.key === "price") return tr.appendChild(priceCell(it));
          if (col.key === "suit") {
            const td = el("td", "pk-suit");
            if (!it.tags.length) td.textContent = "-";
            it.tags.forEach((t) => td.appendChild(el("span", null, t)));
            return tr.appendChild(td);
          }
          const td = el("td", CELL_CLASS[col.key] || null, it.cells[col.key] ?? "-");
          if (col.key === "gpu" && it.gpu_kind) {
            td.appendChild(el("span", "pk-kind" + (it.gpu_kind === "ในตัว" ? "" : " dgpu"), it.gpu_kind));
          }
          tr.appendChild(td);
        });
        const toggle = () => {
          if (locked) return;
          const i = chosen.indexOf(it.value);
          if (i >= 0) chosen.splice(i, 1);
          else if (chosen.length < pk.max) chosen.push(it.value);
          renderRows();
          updateButton();
        };
        cb.addEventListener("change", toggle);
        tr.addEventListener("click", (e) => { if (e.target !== cb) toggle(); });
        tbody.appendChild(tr);
      });
    }

    // หัวตาราง (กดเพื่อเรียงลำดับ)
    htr.appendChild(el("th", "pk-check", "เลือก"));
    pk.columns.forEach((col) => {
      const th = el("th", col.key === "model" ? "pk-model" : null, col.label);
      if (col.sort) {
        th.classList.add("sortable");
        th.title = "กดเพื่อเรียงลำดับ";
        th.addEventListener("click", () => {
          sortDir = sortKey === col.key ? -sortDir : 1;
          sortKey = col.key;
          htr.querySelectorAll("th").forEach((x) => x.removeAttribute("data-dir"));
          th.setAttribute("data-dir", sortDir > 0 ? "asc" : "desc");
          renderRows();
        });
      }
      htr.appendChild(th);
    });
    thead.appendChild(htr);

    // ปุ่มกรองตามการใช้งาน (กดได้หลายปุ่ม = ต้องผ่านทุกเกณฑ์ที่เลือก, "ทั้งหมด" = ล้างตัวกรอง)
    const allBtn = el("button", "pk-filter on", "ทั้งหมด");
    allBtn.type = "button";
    allBtn.setAttribute("aria-pressed", "true");
    const syncFilterButtons = () => {
      filterBar.querySelectorAll("button[data-f]").forEach((x) => {
        const on = filters.has(x.dataset.f);
        x.classList.toggle("on", on);
        x.setAttribute("aria-pressed", String(on));
      });
      allBtn.classList.toggle("on", filters.size === 0);
      allBtn.setAttribute("aria-pressed", String(filters.size === 0));
    };
    allBtn.addEventListener("click", () => { filters.clear(); syncFilterButtons(); renderRows(); });
    filterBar.appendChild(allBtn);
    (pk.filters || []).forEach((f) => {
      const b = el("button", "pk-filter", f);
      b.type = "button";
      b.dataset.f = f;
      b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", () => {
        if (filters.has(f)) filters.delete(f);
        else filters.add(f);
        syncFilterButtons();
        renderRows();
      });
      filterBar.appendChild(b);
    });

    btn.addEventListener("click", () => {
      if (chosen.length !== pk.max || busy) return;
      let msg = pk.template;
      chosen.forEach((v, i) => { msg = msg.replace(`{${i}}`, v); });
      locked = true;
      box.classList.add("done");
      renderRows();
      updateButton();
      send(msg);
    });

    renderRows();
    updateButton();
    return box;
  }

  // ช่องกรอกช่วงงบเอง (ตั้งแต่ / ถึง) แล้วส่งเป็นข้อความตามแม่แบบที่ระบบให้มา
  const fmtNum = (n) => Number(n).toLocaleString("en-US");
  function renderBudgetForm(f) {
    const box = el("form", "bform");
    box.noValidate = true;
    box.appendChild(el("div", "bf-title", f.title));
    const row = el("div", "bf-row");
    const field = (label, placeholder) => {
      const lab = el("label", "bf-field");
      lab.appendChild(el("span", null, label));
      const inp = document.createElement("input");
      inp.inputMode = "numeric";
      inp.autocomplete = "off";
      inp.placeholder = placeholder;
      inp.addEventListener("input", () => {
        const digits = inp.value.replace(/\D/g, "").replace(/^0+/, "").slice(0, 6);
        inp.value = digits ? fmtNum(digits) : "";
        err.textContent = "";
      });
      lab.appendChild(inp);
      row.appendChild(lab);
      return inp;
    };
    const lo = field(f.lo_label, "เช่น 25,000");
    row.appendChild(el("span", "bf-dash", "–"));
    const hi = field(f.hi_label, "เช่น 35,000");
    const go = el("button", "bf-go", f.button);
    go.type = "submit";
    row.appendChild(go);
    box.appendChild(row);
    const err = el("div", "bf-err");
    err.setAttribute("role", "alert");
    box.appendChild(err);
    box.appendChild(el("div", "bf-hint", f.hint));

    box.addEventListener("submit", (e) => {
      e.preventDefault();
      if (busy || box.classList.contains("done")) return;
      let a = Number(lo.value.replace(/\D/g, "")) || null;
      let b = Number(hi.value.replace(/\D/g, "")) || null;
      if (!a && !b) { err.textContent = "กรอกงบอย่างน้อย 1 ช่องครับ"; lo.focus(); return; }
      if ([a, b].some((v) => v !== null && (v < f.min || v > f.max))) {
        err.textContent = `กรอกงบเป็นจำนวนบาทระหว่าง ${fmtNum(f.min)}–${fmtNum(f.max)} เช่น 25,000`;
        return;
      }
      if (a && b && a > b) { [a, b] = [b, a]; lo.value = fmtNum(a); hi.value = fmtNum(b); }
      const key = a && b ? "both" : a ? "lo" : "hi";
      const msg = f.templates[key].replace("{lo}", a ? fmtNum(a) : "").replace("{hi}", b ? fmtNum(b) : "");
      box.classList.add("done");
      [lo, hi, go].forEach((x) => (x.disabled = true));
      send(msg);
    });
    return box;
  }

  function renderChips(list) {
    chips.replaceChildren();
    (list || []).forEach((q) => {
      const b = el("button", "chip", q.label);
      b.type = "button";
      b.addEventListener("click", () => send(q.message));
      chips.appendChild(b);
    });
  }

  function renderBot(r) {
    const stack = botRow();
    if (r.text) stack.appendChild(el("div", "bubble", r.text));
    if (r.cards && r.cards.length) {
      const wrap = el("div", "cards");
      r.cards.forEach((c) => wrap.appendChild(renderCard(c)));
      stack.appendChild(wrap);
    }
    if (r.compare) stack.appendChild(renderCompare(r.compare));
    if (r.picker) stack.appendChild(renderPicker(r.picker));
    if (r.form) stack.appendChild(renderBudgetForm(r.form));
    renderChips(r.quick_replies);
    scrollDown();
  }

  async function post(payload) {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, ...payload }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  function setBusy(v) {
    busy = v;
    input.disabled = v;
    sendBtn.disabled = v;
    attachBtn.classList.toggle("disabled", v);
    chips.querySelectorAll("button").forEach((b) => (b.disabled = v));
  }

  async function sendImage(text) {
    if (busy || !pendingFile) return;
    text = (text || "").trim();
    const file = pendingFile;
    addUserImage(pendingUrl, text);
    clearPending(false);  // URL ยังใช้แสดงรูปในแชท
    input.value = "";
    setBusy(true);
    const typing = showTyping();
    try {
      const fd = new FormData();
      fd.append("session_id", sessionId);
      fd.append("message", text);
      fd.append("image", file);
      const res = await fetch("/api/chat-image", { method: "POST", body: fd });
      const r = await res.json();
      typing.remove();
      renderBot(r);
    } catch (e) {
      typing.remove();
      renderBot({ text: "ส่งรูปไม่สำเร็จครับ ลองใหม่อีกครั้ง", quick_replies: [] });
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  async function send(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    addUser(text);
    input.value = "";
    setBusy(true);
    const typing = showTyping();
    try {
      const r = await post({ message: text });
      typing.remove();
      renderBot(r);
    } catch (e) {
      typing.remove();
      renderBot({ text: "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ครับ ลองส่งใหม่อีกครั้ง", quick_replies: [] });
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  async function start() {
    chat.replaceChildren();
    renderChips([]);
    sessionId = newId();
    try {
      renderBot(await post({ event: "start" }));
    } catch (e) {
      renderBot({ text: "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ครับ ตรวจสอบว่ารัน python app.py อยู่", quick_replies: [] });
    }
    input.focus();
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (pendingFile) sendImage(input.value);
    else send(input.value);
  });
  restartBtn.addEventListener("click", () => { clearPending(true); start(); });
  fileInput.addEventListener("change", () => setPending(fileInput.files[0]));
  clearImg.addEventListener("click", () => clearPending(true));
  // วางรูปจากคลิปบอร์ด (Ctrl+V) ในช่องพิมพ์
  input.addEventListener("paste", (e) => {
    const f = [...(e.clipboardData?.files || [])].find((x) => x.type.startsWith("image/"));
    if (f) { e.preventDefault(); setPending(f); }
  });
  // ลากรูปมาวางในหน้าแชท
  const app = document.querySelector(".app");
  app.addEventListener("dragover", (e) => { e.preventDefault(); app.classList.add("dragging"); });
  app.addEventListener("dragleave", (e) => { if (e.target === app || !app.contains(e.relatedTarget)) app.classList.remove("dragging"); });
  app.addEventListener("drop", (e) => {
    e.preventDefault();
    app.classList.remove("dragging");
    const f = [...(e.dataTransfer?.files || [])].find((x) => x.type.startsWith("image/"));
    if (f) setPending(f);
  });
  start();
})();
