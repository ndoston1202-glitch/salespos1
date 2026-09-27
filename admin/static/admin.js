// EproPos Admin: mijozlar, obuna to'lovlari va faollashtirish kodlari
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => Number(n || 0).toLocaleString("ru-RU").replace(/,/g, " ") + " so'm";
const STATUS = { active: ["ok", "Faol"], warning: ["warn", "Tugayapti"], expired: ["off", "Muddati o'tgan"], new: ["new", "Yangi"],
  suspended: ["off", "⏸ To'xtatilgan"] };
let state = {};

async function api(method, url, body) {
  const res = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Xato: " + res.status);
  return data;
}

function toast(text, err) {
  const el = document.createElement("div");
  el.textContent = text;
  if (err) el.className = "err";
  $("#toast").appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function safe(fn) {
  return async (e) => {
    const btn = e && e.type === "submit" ? $("button:not([type=button])", e.target) : null;
    if (btn) btn.disabled = true;
    try { await fn(e); } catch (err) { toast(err.message, true); } finally { if (btn) btn.disabled = false; }
  };
}

function openModal(html) {
  $("#modal-root").innerHTML = `<div class="modal-bg"><div class="modal">${html}</div></div>`;
  const bg = $(".modal-bg");
  bg.addEventListener("click", (e) => { if (e.target === bg) closeModal(); });
  $$("[data-close]").forEach((b) => b.addEventListener("click", closeModal));
  return $(".modal");
}
function closeModal() { $("#modal-root").innerHTML = ""; }

async function copy(text) {
  try { await navigator.clipboard.writeText(text); } catch {
    const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select();
    document.execCommand("copy"); t.remove();
  }
  toast("Nusxa olindi ✅");
}

function badge(c) {
  if (c.demo && (c.status === "active" || c.status === "warning")) return `<span class="badge demo">Demo</span>`;
  const [cls, label] = STATUS[c.status];
  return `<span class="badge ${cls}">${label}</span>`;
}

function leftText(c) {
  if (c.days_left == null) return "—";
  return c.days_left >= 0 ? `${c.days_left} kun qoldi` : `${-c.days_left} kun o'tdi`;
}

// ------------------------------------------------------------ bosh sahifa

async function viewHome() {
  state = await api("GET", "/api/state");
  const clients = await api("GET", "/api/clients");
  const s = state.stats;
  const urgent = clients.filter((c) => ["expired", "warning", "suspended"].includes(c.status));
  $("#view").innerHTML = `
    ${!state.settings.vendor_name ? `<div class="notice">Avval <a href="#/settings">Sozlamalar</a>da ismingiz va telefoningizni
      yozing — ular mijozning dasturida "to'lov uchun murojaat" sifatida chiqadi.</div>` : ""}
    <div class="stat-grid">
      <div class="stat"><small>Jami mijozlar</small><b>${s.total}</b></div>
      <div class="stat"><small>Faol obunalar</small><b>${s.active}</b></div>
      <div class="stat warn"><small>5 kunda tugaydi</small><b>${s.warning}</b></div>
      <div class="stat bad"><small>Muddati o'tgan</small><b>${s.expired}</b></div>
      <div class="stat bad"><small>To'xtatilgan</small><b>${s.suspended}</b></div>
      <div class="stat"><small>Oylik kutilgan tushum</small><b>${money(s.monthly)}</b></div>
      <div class="stat"><small>Shu oy to'langan</small><b>${money(s.paid_this_month)}</b></div>
    </div>
    <div class="panel">
      <h2>⚠️ E'tibor talab qiladi</h2>
      ${urgent.length ? clientTable(urgent) : `<p class="muted">Hamma obunalar joyida ✅</p>`}
    </div>`;
  bindTable();
}

function clientTable(list) {
  return `<div class="table-scroll"><table class="list clients">
    <thead><tr><th>Biznes</th><th>Egasi / telefon</th><th>Do'kon ID</th><th>Oylik</th><th>Qaysi sanagacha</th><th>Holati</th></tr></thead>
    <tbody>${list.map((c) => `<tr data-id="${c.id}">
      <td><b>${esc(c.business)}</b></td>
      <td>${esc(c.owner || "")}<br><small class="muted">${esc(c.phone || "")}</small></td>
      <td class="mono">${esc(c.shop_id || "—")}</td>
      <td>${money(c.tariff)}</td>
      <td>${esc(c.paid_until || "—")}<br><small class="muted">${leftText(c)}</small></td>
      <td>${badge(c)}</td></tr>`).join("")}</tbody></table></div>`;
}

function bindTable() {
  $$(".clients tr[data-id]").forEach((tr) => tr.addEventListener("click", () => clientModal(+tr.dataset.id)));
}

// ------------------------------------------------------------ mijozlar

async function viewClients() {
  const clients = await api("GET", "/api/clients");
  $("#view").innerHTML = `
    <div class="panel">
      <div class="toolbar"><h2 style="margin:0">Mijozlar</h2>
        <input id="q" placeholder="Qidirish: biznes, egasi, telefon, do'kon ID">
        <button class="btn primary" id="add">+ Mijoz qo'shish</button></div>
      <div id="table"></div>
    </div>`;
  const draw = () => {
    const q = $("#q").value.trim().toLowerCase();
    const list = clients.filter((c) => !q || [c.business, c.owner, c.phone, c.shop_id].join(" ").toLowerCase().includes(q));
    $("#table").innerHTML = list.length ? clientTable(list) : `<p class="muted">Mijoz yo'q</p>`;
    bindTable();
  };
  $("#q").addEventListener("input", draw);
  $("#add").addEventListener("click", () => editModal({}));
  draw();
}

function editModal(c) {
  const m = openModal(`
    <form class="adm-form" id="f">
      <div class="modal-head"><h2>${c.id ? "Mijozni tahrirlash" : "Yangi mijoz"}</h2><button type="button" class="icon-btn" data-close>✕</button></div>
      <label><span>Biznes nomi *</span><input name="business" required value="${esc(c.business || "")}" placeholder="Masalan: Baraka market"></label>
      <div class="grid-2">
        <label><span>Egasi</span><input name="owner" value="${esc(c.owner || "")}"></label>
        <label><span>Telefon</span><input name="phone" value="${esc(c.phone || "")}" placeholder="+998 90 123 45 67"></label>
      </div>
      <label><span>Manzil</span><input name="address" value="${esc(c.address || "")}"></label>
      <div class="grid-2">
        <label><span>Do'kon ID</span><input name="shop_id" class="mono" value="${esc(c.shop_id || "")}" placeholder="1A2B-3C4D-5E6F">
          <small class="muted">Mijozning EproPos'ida: Sozlamalar → Obuna</small></label>
        <label><span>Oylik to'lov (so'm)</span><input name="tariff" type="number" min="0" step="1000" value="${esc(c.tariff || "")}"></label>
      </div>
      <label><span>Izoh</span><textarea name="note" rows="2">${esc(c.note || "")}</textarea></label>
      ${c.id ? "" : `<fieldset class="demo-box"><legend>🎁 Demo (sinov) muddati</legend>
        <div class="grid-2">
          <label><span>Muddat</span><select name="demo">
            <option value="0">Demo yo'q</option>
            ${[3, 7, 14, 30].map((d) => `<option value="${d}" ${d === 7 ? "selected" : ""}>${d} kun</option>`).join("")}
            <option value="date">Boshqa sana...</option></select></label>
          <label class="demo-date hidden"><span>Qaysi sanagacha</span><input name="demo_date" type="date"></label>
        </div>
        <small class="muted" id="demo-hint"></small></fieldset>`}
      <div class="row-btns">${c.id ? `<button type="button" class="btn danger-text" id="del">Arxivga olish</button>` : ""}
        <button class="btn primary">Saqlash</button></div>
    </form>`);
  const f = $("#f", m);
  const demoUntil = () => {
    if (!f.demo || f.demo.value === "0") return "";
    if (f.demo.value === "date") return f.demo_date.value;
    const d = new Date(state.today);
    d.setDate(d.getDate() + Number(f.demo.value));
    return d.toISOString().slice(0, 10);
  };
  if (f.demo) {
    const hint = () => {
      $(".demo-date", m).classList.toggle("hidden", f.demo.value !== "date");
      const until = demoUntil();
      $("#demo-hint", m).textContent = until ? `Demo kodi ${until} gacha yaratiladi va darhol ko'rsatiladi (Do'kon ID kerak).` : "";
    };
    f.demo.addEventListener("change", hint);
    f.demo_date.addEventListener("change", hint);
    hint();
  }
  f.addEventListener("submit", safe(async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(f));
    delete data.demo;
    delete data.demo_date;
    if (!c.id) data.demo_until = demoUntil();
    const saved = await api(c.id ? "PUT" : "POST", c.id ? `/api/clients/${c.id}` : "/api/clients", data);
    toast("Saqlandi ✅");
    await route();
    if (saved.code) showCode(saved, saved.code, saved.paid_until);
    else clientModal(saved.id);
  }));
  const del = $("#del", m);
  if (del) del.addEventListener("click", safe(async () => {
    if (!confirm(`${c.business} arxivga olinsinmi? (ro'yxatdan yo'qoladi)`)) return;
    await api("DELETE", `/api/clients/${c.id}`);
    closeModal();
    route();
  }));
}

async function clientModal(id) {
  const c = await api("GET", `/api/clients/${id}`);
  const m = openModal(`
    <div class="modal-head"><h2>${esc(c.business)}</h2><button type="button" class="icon-btn" data-close>✕</button></div>
    <div class="sync-card">
      <div><small class="muted">Obuna</small><b>${esc(c.paid_until || "hali to'lanmagan")}</b><span class="muted">${leftText(c)}</span></div>
      ${badge(c)}
    </div>
    <p>${esc(c.owner || "")} ${c.phone ? `· <a href="tel:${esc(c.phone)}">${esc(c.phone)}</a>` : ""} ${c.address ? `· ${esc(c.address)}` : ""}</p>
    <p>Do'kon ID: <b class="mono">${esc(c.shop_id || "— kiritilmagan")}</b> · Oylik: <b>${money(c.tariff)}</b></p>
    ${c.note ? `<p class="muted">${esc(c.note)}</p>` : ""}
    <div class="row-btns">
      <button class="btn primary" id="pay">💰 To'lov qabul qilish</button>
      <button class="btn" id="code">🔑 Kod (to'lovsiz)</button>
      <button class="btn" id="edit">✏️ Tahrirlash</button>
      ${c.suspended ? `<button class="btn primary" id="resume">▶️ Davom ettirish</button>`
        : `<button class="btn danger-text" id="suspend">⏸ Vaqtincha to'xtatish</button>`}
    </div>
    ${c.suspended ? `<div class="notice error-notice">Dastur vaqtincha to'xtatilgan. Mijozning EproPos'i internetga
      ulanganda (30 daqiqagacha) bloklanadi.</div>` : ""}
    <h3>To'lovlar tarixi</h3>
    ${c.payments.length ? `<div class="table-scroll"><table class="list">
      <thead><tr><th>Sana</th><th>Summa</th><th>Oy</th><th>Qaysi sanagacha</th><th></th></tr></thead>
      <tbody>${c.payments.map((p) => `<tr><td>${esc(p.paid_at)}</td><td>${money(p.amount)}</td><td>${p.months || "—"}</td>
        <td>${esc(p.until)}${p.note ? `<br><small class="muted">${esc(p.note)}</small>` : ""}</td>
        <td><button class="btn small" data-code="${esc(p.code)}" data-until="${esc(p.until)}">Kod</button></td></tr>`).join("")}</tbody>
    </table></div>` : `<p class="muted">Hali to'lov yo'q</p>`}`);
  $("#edit", m).addEventListener("click", () => editModal(c));
  $("#pay", m).addEventListener("click", () => payModal(c));
  $("#code", m).addEventListener("click", () => freeCodeModal(c));
  const sus = $("#suspend", m);
  if (sus) sus.addEventListener("click", safe(async () => {
    if (!confirm(`${c.business} dasturi vaqtincha to'xtatilsinmi?\n\nMijozning EproPos'i internetga ulanganda ` +
      "(30 daqiqagacha) bloklanadi. Ma'lumotlari o'chmaydi, \"Davom ettirish\" bilan qayta ochiladi.")) return;
    await api("POST", `/api/clients/${c.id}/suspend`, { suspended: true });
    toast("To'xtatildi ⏸");
    route();
    clientModal(c.id);
  }));
  const resume = $("#resume", m);
  if (resume) resume.addEventListener("click", safe(async () => {
    const res = await api("POST", `/api/clients/${c.id}/suspend`, { suspended: false });
    route();
    if (res.code) {
      showCode(res.client, res.code, res.until);
      $(".modal p").insertAdjacentHTML("afterend", `<div class="notice">Dastur internet orqali o'zi ochiladi (30 daqiqagacha).
        Mijozda internet bo'lmasa yoki shoshilinch bo'lsa - shu kodni yuboring.</div>`);
    } else {
      toast("Davom ettirildi ▶️");
      clientModal(c.id);
    }
  }));
  $$("[data-code]", m).forEach((b) => b.addEventListener("click", () => showCode(c, b.dataset.code, b.dataset.until)));
}

function payModal(c) {
  const m = openModal(`
    <form class="adm-form" id="f">
      <div class="modal-head"><h2>💰 To'lov: ${esc(c.business)}</h2><button type="button" class="icon-btn" data-close>✕</button></div>
      ${!c.shop_id ? `<div class="notice error-notice">Avval mijozning Do'kon ID sini kiriting (Tahrirlash)</div>` : ""}
      <label><span>Necha oyga</span><select name="months">
        ${[1, 2, 3, 6, 12].map((n) => `<option value="${n}">${n} oy</option>`).join("")}</select></label>
      <label><span>Summa (so'm)</span><input name="amount" type="number" min="0" step="1000" value="${c.tariff || 0}"></label>
      <label><span>Izoh</span><input name="note" placeholder="Masalan: naqd, Click"></label>
      <p class="muted" id="hint"></p>
      <button class="btn primary big">To'lovni saqlash va kod yaratish</button>
    </form>`);
  const f = $("#f", m);
  const hint = () => {
    f.amount.value = (c.tariff || 0) * f.months.value;
    const from = c.paid_until && c.paid_until > state.today ? c.paid_until : state.today;
    $("#hint", m).textContent = `Obuna ${from} dan ${f.months.value} oyga uzaytiriladi.`;
  };
  f.months.addEventListener("change", hint);
  hint();
  f.addEventListener("submit", safe(async (e) => {
    e.preventDefault();
    const res = await api("POST", `/api/clients/${c.id}/pay`, Object.fromEntries(new FormData(f)));
    showCode(res.client, res.code, res.until);
    if (location.hash !== "#/clients") route();
  }));
}

function freeCodeModal(c) {
  const d = new Date(); d.setDate(d.getDate() + 14);
  const m = openModal(`
    <form class="adm-form" id="f">
      <div class="modal-head"><h2>🔑 To'lovsiz kod</h2><button type="button" class="icon-btn" data-close>✕</button></div>
      <p class="muted">Sinov muddati, bepul davr yoki o'zingizning do'koningiz uchun.</p>
      <label><span>Qaysi sanagacha</span><input name="until" type="date" required value="${d.toISOString().slice(0, 10)}"></label>
      <label style="flex-direction:row;align-items:center;gap:8px"><input type="checkbox" name="save" checked> Mijozning obuna muddatini ham shu sanaga o'zgartirish</label>
      <button class="btn primary big">Kod yaratish</button>
    </form>`);
  $("#f", m).addEventListener("submit", safe(async (e) => {
    e.preventDefault();
    const f = e.target;
    const res = await api("POST", `/api/clients/${c.id}/code`, { until: f.until.value, save: f.save.checked });
    showCode(res.client, res.code, res.until);
  }));
}

function showCode(c, code, until) {
  const msg = `EproPos faollashtirish kodi (${c.business}, ${until} gacha):\n\n${code}\n\nKiritish: EproPos → Sozlamalar → Obuna → kodni qo'yib "Faollashtirish".`;
  const m = openModal(`
    <div class="modal-head"><h2>✅ Kod tayyor</h2><button type="button" class="icon-btn" data-close>✕</button></div>
    <p><b>${esc(c.business)}</b> — <b>${esc(until)}</b> gacha. Kodni mijozga yuboring, u EproPos'da
      <b>Sozlamalar → Obuna</b> sahifasiga kiritadi (muddat tugab bloklangan bo'lsa - to'g'ridan-to'g'ri o'sha oynada).</p>
    <textarea class="code-box" rows="5" readonly>${esc(code)}</textarea>
    <div class="row-btns">
      <button class="btn primary" id="copy">📋 Kodni nusxalash</button>
      <button class="btn" id="copy-msg">📋 Xabar bilan nusxalash</button>
      <a class="btn" target="_blank" rel="noopener" href="https://t.me/share/url?url=${encodeURIComponent(code)}&text=${encodeURIComponent(msg.replace(code, ""))}">✈️ Telegram'da yuborish</a>
    </div>`);
  $("#copy", m).addEventListener("click", () => copy(code));
  $("#copy-msg", m).addEventListener("click", () => copy(msg));
  $(".code-box", m).addEventListener("focus", (e) => e.target.select());
}

// ------------------------------------------------------------ sozlamalar

async function viewSettings() {
  state = await api("GET", "/api/state");
  const s = state.settings;
  $("#view").innerHTML = `
    <div class="panel" style="max-width:720px">
      <h2>Sozlamalar</h2>
      <form class="adm-form" id="f">
        <label><span>Ismingiz yoki kompaniya nomi</span><input name="vendor_name" value="${esc(s.vendor_name)}" placeholder="Masalan: EproPos - Doston"></label>
        <label><span>Telefon (mijoz dasturida "to'lov uchun murojaat" bo'lib chiqadi)</span>
          <input name="vendor_phone" value="${esc(s.vendor_phone)}" placeholder="+998 90 123 45 67"></label>
        <button class="btn primary">Saqlash</button>
      </form>
      <p class="muted">Yangi ism/telefon keyingi yaratilgan kodlarda chiqadi.</p>
      <h3>📡 Vaqtincha to'xtatish xizmati</h3>
      <p class="muted">To'xtatilgan mijozlar ro'yxati internet orqali e'lon qilinadi (shu panel ochiq turganda).
        ${state.publish && state.publish.last_ok ? `Oxirgi e'lon: <b>${esc(state.publish.last_ok)}</b> ✅` : ""}</p>
      ${state.publish && state.publish.error ? `<div class="notice error-notice">${esc(state.publish.error)}</div>` : ""}
      <h3>🔐 Kalitlar va zaxira</h3>
      <p>Kodlar shu kompyuterdagi <b>maxfiy kalit</b> bilan imzolanadi. Uni yo'qotsangiz, mavjud mijozlarga yangi kod bera
        olmaysiz — <b>zaxira nusxani</b> flesh yoki bulutda saqlang va hech kimga bermang.</p>
      <p class="muted">Ma'lumotlar papkasi: <code>${esc(state.data_dir)}</code></p>
      <a class="btn primary" href="/api/backup">⬇️ Zaxira nusxa yuklab olish</a>
      <h3>Ochiq kalit</h3>
      <p class="muted">Bu sir emas. Uni dasturchiga yuborsangiz, EproPos faqat sizning kodlaringizni qabul qiladigan qilib qo'yiladi.</p>
      <div class="key-box">${esc(state.public_key)}</div>
      <div class="row-btns"><button class="btn" id="copy-key">📋 Nusxalash</button></div>
    </div>`;
  $("#f").addEventListener("submit", safe(async (e) => {
    e.preventDefault();
    await api("PUT", "/api/settings", Object.fromEntries(new FormData(e.target)));
    toast("Saqlandi ✅");
  }));
  $("#copy-key").addEventListener("click", () => copy(state.public_key));
}

// ------------------------------------------------------------ yo'naltirish

async function route() {
  const hash = location.hash || "#/";
  $$("#adm-nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === hash));
  try {
    if (hash === "#/clients") await viewClients();
    else if (hash === "#/settings") await viewSettings();
    else await viewHome();
  } catch (e) { toast(e.message, true); }
}
window.addEventListener("hashchange", route);
api("GET", "/api/state").then((s) => { state = s; route(); });
