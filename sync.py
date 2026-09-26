"""Kompyuter (asosiy baza) va telefonlar o'rtasida sinxronlash.

Har bir qurilma (tugun) o'z bazasiga ega va kompyutersiz ham to'liq ishlaydi. Bir tarmoqqa tushganda
o'zgarishlar almashiladi:
  * ID lar to'qnashmasligi uchun har bir tugun o'z oralig'idan raqam beradi: tugun N -> N * SPAN dan boshlab
    (kompyuter N=0). Yangi qator ID sini SyncConnection o'zi qo'yadi.
  * Har bir qator o'zgarishi trigger orqali sync_changes jadvaliga yoziladi (seq - tartib raqami, hlc - vaqt+tugun).
  * Ziddiyat: bir qator ikki joyda o'zgargan bo'lsa - eng oxirgi o'zgarish (hlc katta) qoladi.
  * Ombor qoldig'i va qaytarish summalari almashuvdan keyin harakatlardan qayta hisoblanadi - sotuvlar yo'qolmaydi.
  * Turli tarmoqlarda: kompyuter internetga tunnel orqali chiqadi (tunnel.py), uning o'zgaruvchan manzili
    "internet kodi" nomli yashirin kanalga e'lon qilinadi (relay_publish), telefon uni o'sha yerdan oladi.
"""

import ipaddress
import json
import os
import random
import secrets
import re
import socket
import sqlite3
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SPAN = 10 ** 12          # har bir tugun uchun ID oralig'i
MAX_PHONE_NODE = 8000    # 8000 * 10^12 < 2^53 (JavaScript butun sonlari chegarasi)
BATCH = 1000

# (jadval, asosiy kalit) - bog'liqlik tartibida (ota jadval oldin)
SYNC_TABLES = [
    ("settings", "key"), ("users", "id"), ("categories", "id"), ("products", "id"), ("customers", "id"),
    ("suppliers", "id"), ("finance_types", "id"), ("orders", "id"), ("order_items", "id"),
    ("order_returns", "id"), ("debts", "id"), ("debt_payments", "id"), ("purchases", "id"),
    ("purchase_items", "id"), ("stock_docs", "id"), ("stock_moves", "id"), ("finance_entries", "id"),
    ("balance_adjustments", "id"), ("audit_log", "id"),
]
TABLE_PK = dict(SYNC_TABLES)
TABLE_ORDER = {t: i for i, (t, _) in enumerate(SYNC_TABLES)}
ID_TABLES = {t for t, pk in SYNC_TABLES if pk == "id"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sync_changes (
    tbl TEXT NOT NULL, pk TEXT NOT NULL, seq INTEGER NOT NULL, hlc TEXT NOT NULL,
    origin TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (tbl, pk)
);
CREATE INDEX IF NOT EXISTS idx_sync_seq ON sync_changes(seq);
-- almashuv paytida: qaysi tugundan kelgani va asl vaqti (triggerlar shuni yozadi)
CREATE TABLE IF NOT EXISTS sync_ctx (id INTEGER PRIMARY KEY CHECK (id = 1), hlc TEXT, origin TEXT);
-- kompyuterga ulangan telefonlar
CREATE TABLE IF NOT EXISTS sync_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT, node TEXT NOT NULL, name TEXT, token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL, last_sync TEXT, last_ip TEXT, active INTEGER NOT NULL DEFAULT 1
);
"""

INSERT_RE = re.compile(r"^(\s*INSERT(?:\s+OR\s+\w+)?\s+INTO\s+)(\w+)(\s*\()(.*?)(\)\s*VALUES\s*\()", re.I | re.S)


class SyncConnection(sqlite3.Connection):
    """INSERT larda ID ni shu tugun oralig'idan o'zi qo'yadi (AUTOINCREMENT boshqa tugun ID lariga sakrab ketmasin)."""

    sync_node = None

    def execute(self, sql, parameters=()):
        if self.sync_node is not None and "INSERT" in sql[:40].upper():
            m = INSERT_RE.match(sql)
            if m and m.group(2) in ID_TABLES:
                cols = [c.strip().lower() for c in m.group(4).split(",")]
                if "id" not in cols:
                    new_id = next_id(self, m.group(2))
                    sql = f"{m.group(1)}{m.group(2)}{m.group(3)}id, {m.group(4)}{m.group(5)}?, " + sql[m.end():]
                    parameters = (new_id, *parameters)
        return super().execute(sql, parameters)


def next_id(conn, table):
    base = conn.sync_node * SPAN
    row = sqlite3.Connection.execute(
        conn, f"SELECT MAX(id) FROM {table} WHERE id > ? AND id < ?", (base, base + SPAN)).fetchone()
    return (row[0] or base) + 1


def meta(conn, key, default=None):
    row = sqlite3.Connection.execute(conn, "SELECT value FROM sync_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn, key, value):
    sqlite3.Connection.execute(
        conn, "INSERT INTO sync_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, None if value is None else str(value)))


def _columns(conn, table):
    return [r[1] for r in sqlite3.Connection.execute(conn, f"PRAGMA table_info({table})")]


def create_triggers(conn):
    hlc = ("COALESCE((SELECT hlc FROM sync_ctx WHERE id = 1), "
           "strftime('%Y-%m-%dT%H:%M:%f', 'now') || '#' || (SELECT printf('%04d', value) FROM sync_meta WHERE key = 'node'))")
    origin = "COALESCE((SELECT origin FROM sync_ctx WHERE id = 1), 'local')"
    for table, pk in SYNC_TABLES:
        cond_new = " WHEN NEW.key NOT LIKE '\\_%' ESCAPE '\\'" if table == "settings" else ""
        cond_old = " WHEN OLD.key NOT LIKE '\\_%' ESCAPE '\\'" if table == "settings" else ""
        for event, ref, deleted, cond in (("INSERT", "NEW", 0, cond_new), ("UPDATE", "NEW", 0, cond_new),
                                          ("DELETE", "OLD", 1, cond_old)):
            name = f"sync_{event.lower()}_{table}"
            conn.execute(f"DROP TRIGGER IF EXISTS {name}")
            conn.execute(
                f"""CREATE TRIGGER {name} AFTER {event} ON {table}{cond} BEGIN
                    INSERT INTO sync_changes (tbl, pk, seq, hlc, origin, deleted)
                    VALUES ('{table}', {ref}.{pk}, (SELECT COALESCE(MAX(seq), 0) + 1 FROM sync_changes), {hlc}, {origin}, {deleted})
                    ON CONFLICT(tbl, pk) DO UPDATE SET seq = excluded.seq, hlc = excluded.hlc,
                        origin = excluded.origin, deleted = excluded.deleted;
                END""")


def init(conn, role):
    """Sinxronlash jadvallari, tugun raqami va triggerlar. role: "hub" (kompyuter) yoki "phone"."""
    conn.executescript(SCHEMA)
    if meta(conn, "node") is None:
        set_meta(conn, "node", random.randint(1, MAX_PHONE_NODE) if role == "phone" else 0)
    set_meta(conn, "role", role)
    conn.sync_node = int(meta(conn, "node"))
    create_triggers(conn)


def backfill(conn):
    """Sinxronlash yoqilishidan oldingi qatorlar ham birinchi almashuvga kirsin (bir marta)."""
    if meta(conn, "backfilled"):
        return
    seq = sqlite3.Connection.execute(conn, "SELECT COALESCE(MAX(seq), 0) FROM sync_changes").fetchone()[0]
    stamp = sqlite3.Connection.execute(
        conn, "SELECT strftime('%Y-%m-%dT%H:%M:%f', 'now') || '#' || printf('%04d', ?)", (conn.sync_node,)).fetchone()[0]
    for table, pk in SYNC_TABLES:
        where = " AND key NOT LIKE '\\_%' ESCAPE '\\'" if table == "settings" else ""
        for (key,) in sqlite3.Connection.execute(
                conn, f"""SELECT {pk} FROM {table} t WHERE NOT EXISTS
                          (SELECT 1 FROM sync_changes c WHERE c.tbl = '{table}' AND c.pk = t.{pk}){where}""").fetchall():
            seq += 1
            sqlite3.Connection.execute(
                conn, "INSERT INTO sync_changes (tbl, pk, seq, hlc, origin, deleted) VALUES (?, ?, ?, ?, 'local', 0)",
                (table, str(key), seq, stamp))
    set_meta(conn, "backfilled", 1)


def max_seq(conn):
    return sqlite3.Connection.execute(conn, "SELECT COALESCE(MAX(seq), 0) FROM sync_changes").fetchone()[0]


def collect(conn, since, limit=BATCH, only_local=False, exclude_origin=None):
    """seq > since bo'lgan o'zgarishlar. Qaytaradi: (o'zgarishlar, oxirgi ko'rilgan seq, yana bormi)."""
    sql = "SELECT tbl, pk, seq, hlc, origin, deleted FROM sync_changes WHERE seq > ?"
    args = [since]
    if only_local:
        sql += " AND origin = 'local'"
    scanned = sqlite3.Connection.execute(conn, sql + " ORDER BY seq LIMIT ?", args + [limit]).fetchall()
    out = []
    for tbl, pk, seq, hlc, origin, deleted in scanned:
        if exclude_origin is not None and origin == str(exclude_origin):
            continue
        row = None
        if not deleted:
            cur = sqlite3.Connection.execute(conn, f"SELECT * FROM {tbl} WHERE {TABLE_PK[tbl]} = ?", (pk,))
            found = cur.fetchone()
            if found is None:
                continue
            row = dict(zip([d[0] for d in cur.description], found))
        out.append({"t": tbl, "pk": pk, "hlc": hlc, "del": deleted, "row": row})
    last = scanned[-1][2] if scanned else since
    return out, last, len(scanned) == limit


def apply(conn, changes, origin):
    """Boshqa tugundan kelgan o'zgarishlarni qo'llaydi (eng oxirgi o'zgarish yutadi). Qo'llangan qatorlar sonini qaytaradi."""
    applied = 0
    products, orders = set(), set()
    ex = lambda sql, args=(): sqlite3.Connection.execute(conn, sql, args)
    local_cols = {}
    for ch in sorted(changes, key=lambda c: TABLE_ORDER.get(c.get("t"), 999)):
        table, pk, hlc = ch.get("t"), str(ch.get("pk")), str(ch.get("hlc") or "")
        if table not in TABLE_PK or not hlc:
            continue
        key = TABLE_PK[table]
        if table == "settings" and pk.startswith("_"):
            continue
        cur = ex("SELECT hlc FROM sync_changes WHERE tbl = ? AND pk = ?", (table, pk)).fetchone()
        if cur and cur[0] >= hlc:
            continue  # bu yerdagi o'zgarish yangiroq (yoki aynan shu)
        ex("INSERT INTO sync_ctx (id, hlc, origin) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET hlc = excluded.hlc, "
           "origin = excluded.origin", (hlc, str(origin)))
        if ch.get("del"):
            ex(f"DELETE FROM {table} WHERE {key} = ?", (pk,))
        else:
            row = ch.get("row") or {}
            cols = local_cols.setdefault(table, _columns(conn, table))
            names = [c for c in cols if c in row]
            if key not in names:
                continue
            sets = ", ".join(f"{c} = excluded.{c}" for c in names if c != key) or f"{key} = excluded.{key}"
            ex(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))}) "
               f"ON CONFLICT({key}) DO UPDATE SET {sets}", [row[c] for c in names])
            if table == "stock_moves":
                products.add(row.get("product_id"))
            elif table in ("order_returns", "order_items"):
                orders.add(row.get("order_id"))
            elif table == "orders":
                orders.add(row.get("id"))
        if table == "products":
            products.add(int(pk))
        applied += 1
    ex("DELETE FROM sync_ctx")
    recompute(conn, products, orders)
    return applied


def recompute(conn, products, orders):
    """Qoldiq = barcha harakatlar yig'indisi; qaytarilgan summa/miqdor = qaytarishlar yig'indisi."""
    ex = lambda sql, args=(): sqlite3.Connection.execute(conn, sql, args)
    for pid in products:
        if pid is None:
            continue
        ex("""UPDATE products SET stock = (SELECT ROUND(COALESCE(SUM(qty), 0), 3) FROM stock_moves WHERE product_id = ?)
              WHERE id = ? AND stock != (SELECT ROUND(COALESCE(SUM(qty), 0), 3) FROM stock_moves WHERE product_id = ?)""",
           (pid, pid, pid))
    for oid in orders:
        if oid is None:
            continue
        rets = ex("SELECT amount, items FROM order_returns WHERE order_id = ?", (oid,)).fetchall()
        ex("UPDATE orders SET returned = ? WHERE id = ? AND returned != ?", (sum(r[0] for r in rets), oid, sum(r[0] for r in rets)))
        qty = {}
        for _, items in rets:
            try:
                for line in json.loads(items or "[]"):
                    qty[line.get("item_id")] = qty.get(line.get("item_id"), 0) + float(line.get("qty") or 0)
            except (ValueError, TypeError, AttributeError):
                pass
        for item_id, in ex("SELECT id FROM order_items WHERE order_id = ?", (oid,)).fetchall():
            q = round(qty.get(item_id, 0), 3)
            ex("UPDATE order_items SET returned_qty = ? WHERE id = ? AND returned_qty != ?", (q, item_id, q))


def wipe_for_clone(conn):
    """Yangi telefon kompyuterga birinchi ulanganda: namuna ma'lumotlar o'chadi, hammasi kompyuterdan olinadi."""
    for table, _ in reversed(SYNC_TABLES):
        if table == "settings":
            conn.execute("DELETE FROM settings WHERE key NOT LIKE '\\_%' ESCAPE '\\'")
        else:
            conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM sessions")
    conn.execute("DELETE FROM sync_changes")


def is_fresh(conn):
    """Telefonda hali o'z ma'lumoti yo'q (faqat boshlang'ich administrator)."""
    ex = lambda sql: sqlite3.Connection.execute(conn, sql).fetchone()[0]
    return ex("SELECT COUNT(*) FROM orders") == 0 and ex("SELECT COUNT(*) FROM products") == 0 \
        and ex("SELECT COUNT(*) FROM customers") == 0 and ex("SELECT COUNT(*) FROM users") <= 1


# --- tarmoq: kompyuterni topish va so'rovlar

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # mahalliy tarmoq - proksisiz


_web = urllib.request.build_opener()  # internet (https) - tizim proksisi bilan


def _open(req, timeout):
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    return (_web if url.startswith("https://") else _opener).open(req, timeout=timeout)


def post_json(url, body, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with _open(req, timeout) as res:
            return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("error")
        except ValueError:
            msg = None
        raise SyncError(msg or f"Kompyuter xato qaytardi (HTTP {e.code})", e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SyncError(f"Kompyuterga ulanib bo'lmadi: {getattr(e, 'reason', e)}")


class SyncError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def hello(url, timeout=1.0):
    try:
        with _open(url.rstrip("/") + "/api/sync/hello", timeout) as res:
            data = json.loads(res.read().decode())
            return data if data.get("app") == "EproPos" else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return None if ip.startswith(("127.", "0.")) else ip
    except OSError:
        return None


def discover(port, timeout=0.6):
    """Shu Wi-Fi tarmog'idagi EproPos kompyuterlarini topadi."""
    ip = local_ip()
    if not ip:
        return []
    net = ipaddress.ip_network(f"{ip}/24", strict=False)
    urls = [f"http://{h}:{port}" for h in net.hosts() if str(h) != ip]
    found = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        for url, info in zip(urls, pool.map(lambda u: hello(u, timeout), urls)):
            if info and info.get("role") == "hub":
                found.append(dict(info, url=url))
    return found


# --- internet orqali: kompyuterning tunnel manzilini e'lon qilish va topish (ntfy.sh - bepul, ro'yxatdan o'tishsiz)

RELAY = os.environ.get("EPROPOS_RELAY", "https://ntfy.sh").rstrip("/")
CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # adashtiriladigan belgilarsiz (0/o, 1/l/i)


def new_code():
    """Internet kodi: 10 belgi (~50 bit) - taxmin qilib bo'lmaydi; ko'rinishi: abcde-fghjk"""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(10))


def normalize_code(text):
    code = re.sub(r"[^a-z0-9]", "", str(text or "").lower())
    return code if len(code) == 10 and all(c in CODE_ALPHABET for c in code) else None


def format_code(code):
    return f"{code[:5]}-{code[5:]}" if code else None


def _topic(code):
    return "epropos-" + code


def relay_publish(code, url, timeout=15):
    req = urllib.request.Request(f"{RELAY}/{_topic(code)}", data=url.encode(), method="POST",
                                 headers={"Title": "EproPos", "Tags": "epropos"})
    with _web.open(req, timeout=timeout) as res:
        res.read()


def relay_lookup(code, timeout=15):
    """Kompyuterning eng oxirgi e'lon qilgan manzili (topilmasa None)."""
    try:
        with _web.open(f"{RELAY}/{_topic(code)}/json?poll=1&since=all", timeout=timeout) as res:
            lines = res.read().decode().splitlines()
    except (OSError, ValueError, urllib.error.URLError):
        return None
    url = None
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        text = str(msg.get("message") or "").strip()
        if msg.get("event") == "message" and re.match(r"^https?://[^\s/]+$", text):
            url = text
    return url
