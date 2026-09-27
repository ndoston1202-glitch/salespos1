"""EproPos Admin - sotuvchi paneli: mijozlar (biznes egalari), oylik obuna to'lovlari va faollashtirish kodlari.

Faqat shu kompyuterda ishlaydi (http://127.0.0.1:8200). Ma'lumotlar va MAXFIY KALIT dastur papkasidan tashqarida:
Windows: %APPDATA%\\EproPosAdmin, boshqa tizimlar: ~/.epropos-admin. Maxfiy kalitni yo'qotmang - zaxira nusxa oling
(Sozlamalar -> Zaxira nusxa). Kalitsiz mavjud mijozlar uchun yangi kod yaratib bo'lmaydi."""

import io
import json
import mimetypes
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import obuna  # noqa: E402
import sync  # noqa: E402  (e'lon kanali manzili)

PORT = int(os.environ.get("EPROPOS_ADMIN_PORT", "8200"))
DATA_DIR = os.environ.get("EPROPOS_ADMIN_DATA") or (
    os.path.join(os.environ["APPDATA"], "EproPosAdmin") if os.environ.get("APPDATA")
    else os.path.join(os.path.expanduser("~"), ".epropos-admin"))
DB_PATH = os.path.join(DATA_DIR, "admin.db")
KEY_PATH = os.path.join(DATA_DIR, "vendor.key")
STATIC = os.path.join(HERE, "static")
APP_STATIC = os.path.join(ROOT, "static")  # EproPos uslublari va logosi
WARN_DAYS = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business TEXT NOT NULL, owner TEXT, phone TEXT, address TEXT, shop_id TEXT,
    tariff INTEGER NOT NULL DEFAULT 0, paid_until TEXT, note TEXT,
    created_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    amount INTEGER NOT NULL DEFAULT 0, months INTEGER NOT NULL DEFAULT 0,
    paid_at TEXT NOT NULL, until TEXT NOT NULL, code TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

lock = threading.Lock()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def today():
    fake = os.environ.get("EPROPOS_TODAY")
    return date.fromisoformat(fake) if fake else date.today()


def now():
    return today().isoformat() + datetime.now().strftime(" %H:%M")


def add_months(d, months):
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    days = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(y, m, min(d.day, days[m - 1]))


def load_secret():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(KEY_PATH):
        with open(KEY_PATH, "w") as f:
            f.write(obuna.key_text(obuna.new_secret()))
    with open(KEY_PATH) as f:
        return obuna.key_from_text(f.read())


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clients)")]
    if "suspended" not in cols:
        conn.execute("ALTER TABLE clients ADD COLUMN suspended INTEGER NOT NULL DEFAULT 0")
    return conn


class Publisher:
    """To'xtatilgan do'konlar ro'yxatini imzolab e'lon qiladi (o'zgarganda darhol, keyin har 20 daqiqada).
    Mijozlarning EproPos'i internetga ulanganda shu ro'yxatni tekshiradi."""

    def __init__(self, conn, secret):
        self.conn, self.secret = conn, secret
        self.wake = threading.Event()
        self.last_ok = None
        self.error = None

    def start(self):
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                self.publish()
            except Exception as e:
                self.error = str(e)
            self.wake.wait(1200)
            self.wake.clear()

    def publish(self):
        with lock:
            ids = [r[0] for r in self.conn.execute(
                "SELECT shop_id FROM clients WHERE suspended = 1 AND archived = 0 AND shop_id IS NOT NULL")]
        text = obuna.make_status(self.secret, ids, time.time() * 1000)
        topic = obuna.status_topic(obuna.public_key(self.secret))
        req = urllib.request.Request(f"{sync.RELAY}/{topic}", data=text.encode(), method="POST",
                                     headers={"Title": "EproPos"})
        try:
            with sync._web.open(req, timeout=20) as res:
                res.read()
            self.last_ok, self.error = now(), None
        except OSError as e:
            self.error = f"E'lon qilib bo'lmadi (internet bormi?): {e}"


def settings(conn):
    s = {"vendor_name": "", "vendor_phone": ""}
    s.update({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")})
    return s


def client_view(row):
    c = dict(row)
    c["demo"] = str(c.pop("last_note", None) or "").startswith("Demo")
    if c.get("suspended"):
        c["days_left"] = (date.fromisoformat(c["paid_until"]) - today()).days if c["paid_until"] else None
        c["status"] = "suspended"
    elif c["paid_until"]:
        left = (date.fromisoformat(c["paid_until"]) - today()).days
        c["days_left"] = left
        c["status"] = "active" if left > WARN_DAYS else "warning" if left >= 0 else "expired"
    else:
        c["days_left"] = None
        c["status"] = "new"
    return c


def text(data, key, limit=200, required=False):
    value = str(data.get(key) or "").strip()[:limit]
    if required and not value:
        raise ApiError(400, "To'ldiring: " + key)
    return value


def client_values(data):
    shop = data.get("shop_id")
    shop_id = obuna.normalize_shop_id(shop) if shop else None
    if shop and not shop_id:
        raise ApiError(400, "Do'kon ID noto'g'ri. EproPos -> Sozlamalar -> Obuna sahifasidagi 12 belgili ID (1A2B-3C4D-5E6F)")
    try:
        tariff = max(0, int(float(data.get("tariff") or 0)))
    except ValueError:
        raise ApiError(400, "Oylik narx noto'g'ri")
    return {"business": text(data, "business", 120, True), "owner": text(data, "owner", 120),
            "phone": text(data, "phone", 40), "address": text(data, "address", 200), "shop_id": shop_id,
            "tariff": tariff, "note": text(data, "note", 1000)}


def get_client(conn, cid):
    row = conn.execute("""SELECT c.*, (SELECT note FROM payments p WHERE p.client_id = c.id ORDER BY p.id DESC LIMIT 1)
                          AS last_note FROM clients c WHERE id = ?""", (cid,)).fetchone()
    if not row:
        raise ApiError(404, "Mijoz topilmadi")
    return row


def issue_code(conn, secret, client, until):
    if not client["shop_id"]:
        raise ApiError(400, "Avval mijozning Do'kon ID sini kiriting (EproPos -> Sozlamalar -> Obuna)")
    s = settings(conn)
    return obuna.make_code(secret, client["shop_id"], until, s["vendor_name"], s["vendor_phone"], client["business"])


# --- API

def api(conn, secret, method, path, data):
    if method == "GET" and path == "/api/state":
        rows = [client_view(r) for r in conn.execute("SELECT * FROM clients WHERE archived = 0")]
        month = today().strftime("%Y-%m")
        paid = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE substr(paid_at, 1, 7) = ?", (month,)).fetchone()[0]
        return {"settings": settings(conn), "public_key": obuna.key_text(obuna.public_key(secret)),
                "data_dir": DATA_DIR, "today": today().isoformat(),
                "publish": {"last_ok": publisher.last_ok, "error": publisher.error} if publisher else None,
                "stats": {"total": len(rows),
                          "active": sum(1 for c in rows if c["status"] in ("active", "warning")),
                          "warning": sum(1 for c in rows if c["status"] == "warning"),
                          "expired": sum(1 for c in rows if c["status"] == "expired"),
                          "suspended": sum(1 for c in rows if c["status"] == "suspended"),
                          "monthly": sum(c["tariff"] for c in rows if c["status"] in ("active", "warning")),
                          "paid_this_month": paid}}

    if method == "GET" and path == "/api/clients":
        rows = [client_view(r) for r in conn.execute(
            """SELECT c.*, (SELECT note FROM payments p WHERE p.client_id = c.id ORDER BY p.id DESC LIMIT 1) AS last_note
               FROM clients c WHERE archived = 0 ORDER BY business""")]
        order = {"expired": 0, "suspended": 1, "warning": 2, "new": 3, "active": 4}
        rows.sort(key=lambda c: (order[c["status"]], c["days_left"] if c["days_left"] is not None else 0))
        return rows

    if method == "POST" and path == "/api/clients":
        v = client_values(data)
        demo = str(data.get("demo_until") or "")
        if demo:  # yangi mijozga demo (sinov) muddati - sotuvchi o'zi belgilaydi
            try:
                if date.fromisoformat(demo) < today():
                    raise ValueError
            except ValueError:
                raise ApiError(400, "Demo muddati sanasi noto'g'ri")
            if not v["shop_id"]:
                raise ApiError(400, "Demo kod uchun Do'kon ID kerak (mijozning EproPos'ida: Sozlamalar -> Obuna)")
        cur = conn.execute("""INSERT INTO clients (business, owner, phone, address, shop_id, tariff, note, created_at)
                              VALUES (:business, :owner, :phone, :address, :shop_id, :tariff, :note, :created)""",
                           dict(v, created=now()))
        client = get_client(conn, cur.lastrowid)
        if not demo:
            return client_view(client)
        code = issue_code(conn, secret, client, demo)
        conn.execute("UPDATE clients SET paid_until = ? WHERE id = ?", (demo, client["id"]))
        conn.execute("""INSERT INTO payments (client_id, amount, months, paid_at, until, code, note)
                        VALUES (?, 0, 0, ?, ?, ?, 'Demo (sinov)')""", (client["id"], now(), demo, code))
        return dict(client_view(get_client(conn, client["id"])), code=code)

    m = re.match(r"^/api/clients/(\d+)(/pay|/code|/suspend)?$", path)
    if m:
        client = get_client(conn, int(m.group(1)))
        action = m.group(2)
        if method == "GET" and not action:
            res = client_view(client)
            res["payments"] = [dict(r) for r in conn.execute(
                "SELECT * FROM payments WHERE client_id = ? ORDER BY id DESC", (client["id"],))]
            return res
        if method == "PUT" and not action:
            v = client_values(data)
            conn.execute("""UPDATE clients SET business = :business, owner = :owner, phone = :phone, address = :address,
                            shop_id = :shop_id, tariff = :tariff, note = :note WHERE id = :id""", dict(v, id=client["id"]))
            return client_view(get_client(conn, client["id"]))
        if method == "DELETE" and not action:
            conn.execute("UPDATE clients SET archived = 1 WHERE id = ?", (client["id"],))
            return {"ok": True}
        if method == "POST" and action == "/pay":
            # to'lov: muddat oxirgi to'langan kundan (yoki bugundan, agar o'tib ketgan bo'lsa) uzaytiriladi
            try:
                months = int(data.get("months") or 1)
                amount = int(float(data.get("amount") or 0))
            except ValueError:
                raise ApiError(400, "Summa yoki oylar soni noto'g'ri")
            if not 1 <= months <= 60:
                raise ApiError(400, "Oylar soni 1 dan 60 gacha")
            base = today()
            if client["paid_until"] and date.fromisoformat(client["paid_until"]) > base:
                base = date.fromisoformat(client["paid_until"])
            until = add_months(base, months).isoformat()
            code = issue_code(conn, secret, client, until)
            conn.execute("UPDATE clients SET paid_until = ? WHERE id = ?", (until, client["id"]))
            conn.execute("""INSERT INTO payments (client_id, amount, months, paid_at, until, code, note)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                         (client["id"], amount, months, now(), until, code, text(data, "note", 300)))
            return {"code": code, "until": until, "client": client_view(get_client(conn, client["id"]))}
        if method == "POST" and action == "/suspend":
            on = bool(data.get("suspended"))
            conn.execute("UPDATE clients SET suspended = ? WHERE id = ?", (1 if on else 0, client["id"]))
            if publisher:
                publisher.wake.set()
            res = {"client": client_view(get_client(conn, client["id"]))}
            if not on and client["shop_id"] and client["paid_until"] and date.fromisoformat(client["paid_until"]) >= today():
                # internetsiz do'kon uchun: qo'lda kiritiladigan "davom ettirish" kodi
                s = settings(conn)
                res["code"] = obuna.make_code(secret, client["shop_id"], client["paid_until"], s["vendor_name"],
                                              s["vendor_phone"], client["business"], resume=True)
                res["until"] = client["paid_until"]
            return res
        if method == "POST" and action == "/code":
            # to'lovsiz kod: sinov, bepul muddat yoki kodni qayta yuborish
            until = str(data.get("until") or "")
            try:
                date.fromisoformat(until)
            except ValueError:
                raise ApiError(400, "Sana noto'g'ri")
            code = issue_code(conn, secret, client, until)
            if data.get("save"):
                conn.execute("UPDATE clients SET paid_until = ? WHERE id = ?", (until, client["id"]))
                conn.execute("""INSERT INTO payments (client_id, amount, months, paid_at, until, code, note)
                                VALUES (?, 0, 0, ?, ?, ?, ?)""",
                             (client["id"], now(), until, code, text(data, "note", 300) or "To'lovsiz kod"))
            return {"code": code, "until": until, "client": client_view(get_client(conn, client["id"]))}

    if method == "PUT" and path == "/api/settings":
        for key in ("vendor_name", "vendor_phone"):
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (key, text(data, key, 100)))
        return settings(conn)

    raise ApiError(404, "Topilmadi")


def backup_zip(conn):
    buf = io.BytesIO()
    copy = sqlite3.connect(":memory:")
    conn.backup(copy)
    dump = "\n".join(copy.iterdump())
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("admin.sql", dump)
        z.write(KEY_PATH, "vendor.key")
        z.writestr("OQING.txt", "EproPos Admin zaxira nusxasi.\nvendor.key - MAXFIY kalit, hech kimga bermang.\n"
                                "Tiklash: vendor.key ni ma'lumotlar papkasiga qo'ying, admin.sql ni sqlite3 bilan admin.db ga yuklang.\n")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "EproPosAdmin/1.0"

    def log_message(self, fmt, *args):
        pass

    def send(self, status, body, ctype="application/json; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def static(self, path):
        if path == "/":
            path = "/index.html"
        for base in (STATIC, APP_STATIC):  # admin fayllari, keyin EproPos uslublari/rasmlari
            full = os.path.realpath(os.path.join(base, path.lstrip("/")))
            if full.startswith(os.path.realpath(base) + os.sep) and os.path.isfile(full):
                with open(full, "rb") as f:
                    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                    if ctype.startswith("text/") or ctype.endswith("javascript"):
                        ctype += "; charset=utf-8"
                    return self.send(200, f.read(), ctype)
        self.send(404, b"{}")

    def handle_any(self, method):
        path = urlparse(self.path).path
        # faqat shu kompyuterdan (boshqa sayt brauzer orqali so'rov yubora olmasin)
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self.send(403, b'{"error": "Faqat shu kompyuterdan"}')
        if not path.startswith("/api/"):
            return self.static(path) if method == "GET" else self.send(404, b"{}")
        conn, secret = self.server.conn, self.server.secret
        try:
            if path == "/api/backup":
                with lock:
                    body = backup_zip(conn)
                name = f"epropos-admin-{today().isoformat()}.zip"
                return self.send(200, body, "application/zip", {"Content-Disposition": f'attachment; filename="{name}"'})
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}") if length else {}
            with lock:
                try:
                    res = api(conn, secret, method, path, data)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            self.send(200, json.dumps(res, ensure_ascii=False).encode())
        except ApiError as e:
            self.send(e.status, json.dumps({"error": e.message}, ensure_ascii=False).encode())
        except (ValueError, TypeError) as e:
            self.send(400, json.dumps({"error": f"Noto'g'ri ma'lumot: {e}"}, ensure_ascii=False).encode())

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    def do_PUT(self):
        self.handle_any("PUT")

    def do_DELETE(self):
        self.handle_any("DELETE")


publisher = None


def make_server(port=PORT):
    global publisher
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.conn = connect()
    server.secret = load_secret()
    publisher = Publisher(server.conn, server.secret)
    publisher.start()
    return server


def main():
    url = f"http://127.0.0.1:{PORT}"
    try:
        server = make_server()
    except OSError:  # allaqachon ochiq
        webbrowser.open(url)
        return
    print(f"EproPos Admin: {url}\nMa'lumotlar: {DATA_DIR}")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
