"""Obuna (litsenziya) kodlari: sotuvchining admin paneli (Obuna Admin) imzolaydi, dastur (EproPos va boshqalar) tekshiradi.

Bu fayl ikki joyda bir xil: Obuna Admin repozitoriyasida va har bir mahsulotning ichida.

Kod ichida: do'kon ID, qaysi sanagacha, sotuvchi nomi va telefoni. Imzo - Ed25519 (RFC 8032, sof Python):
kodni faqat maxfiy kalit egasi (admin panel) yarata oladi, tekshirish uchun ochiq kalit yetadi.
Kod ko'rinishi: EP1-<base64url(ma'lumot)>.<base64url(imzo)>"""

import base64
import hashlib
import json
import re
import secrets
from datetime import date

# --- Ed25519 (RFC 8032, 5.1 va 6-bo'lim asosida)

_p = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, _p - 2, _p) % _p
_I = pow(2, (_p - 1) // 4, _p)


def _h(m):
    return hashlib.sha512(m).digest()


def _recover_x(y, sign):
    if y >= _p:
        return None
    x2 = (y * y - 1) * pow(_d * y * y + 1, _p - 2, _p)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_p + 3) // 8, _p)
    if (x * x - x2) % _p != 0:
        x = x * _I % _p
    if (x * x - x2) % _p != 0:
        return None
    if (x & 1) != sign:
        x = _p - x
    return x


_gy = 4 * pow(5, _p - 2, _p) % _p
_gx = _recover_x(_gy, 0)
_G = (_gx, _gy, 1, _gx * _gy % _p)
_ZERO = (0, 1, 1, 0)


def _add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _p
    C = 2 * P[3] * Q[3] * _d % _p
    D = 2 * P[2] * Q[2] % _p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _p, G * H % _p, F * G % _p, E * H % _p)


def _mul(s, P):
    Q = _ZERO
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _equal(P, Q):
    return (P[0] * Q[2] - Q[0] * P[2]) % _p == 0 and (P[1] * Q[2] - Q[1] * P[2]) % _p == 0


def _compress(P):
    zinv = pow(P[2], _p - 2, _p)
    x, y = P[0] * zinv % _p, P[1] * zinv % _p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _p)


def _secret_expand(secret):
    h = _h(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(secret):
    a, _ = _secret_expand(secret)
    return _compress(_mul(a, _G))


def sign(secret, msg):
    a, prefix = _secret_expand(secret)
    A = _compress(_mul(a, _G))
    r = int.from_bytes(_h(prefix + msg), "little") % _L
    R = _compress(_mul(r, _G))
    k = int.from_bytes(_h(R + A + msg), "little") % _L
    s = (r + k * a) % _L
    return R + int.to_bytes(s, 32, "little")


def verify(public, msg, signature):
    if len(public) != 32 or len(signature) != 64:
        return False
    A = _decompress(public)
    R = _decompress(signature[:32])
    if not A or not R:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    k = int.from_bytes(_h(signature[:32] + public + msg), "little") % _L
    return _equal(_mul(s, _G), _add(R, _mul(k, A)))


# --- obuna kodlari

PREFIX = "EP1-"


def _b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_secret():
    return secrets.token_bytes(32)


def key_text(key):
    """Kalitni matn ko'rinishida (saqlash va ko'rsatish uchun)."""
    return _b64(key)


def key_from_text(text):
    key = _unb64(str(text).strip())
    if len(key) != 32:
        raise ValueError("Kalit noto'g'ri")
    return key


def normalize_shop_id(text):
    """Do'kon ID: 12 ta belgi, ko'rinishi 1A2B-3C4D-5E6F (katta-kichik harf va chiziqchalar farqi yo'q)."""
    raw = re.sub(r"[^0-9A-Za-z]", "", str(text or "")).upper()
    return "-".join(raw[i:i + 4] for i in range(0, 12, 4)) if len(raw) == 12 else None


def make_code(secret, shop_id, until, vendor="", phone="", customer="", resume=False, app=""):
    """Faollashtirish kodi: shop_id do'koni `until` (YYYY-MM-DD) sanasigacha ishlaydi."""
    shop = normalize_shop_id(shop_id)
    if not shop:
        raise ValueError("Do'kon ID noto'g'ri (masalan 1A2B-3C4D-5E6F)")
    date.fromisoformat(until)
    payload = {"s": shop, "u": until, "i": date.today().isoformat(), "n": vendor, "p": phone, "c": customer,
               "k": _b64(public_key(secret))}
    if resume:  # internetsiz do'kon uchun: vaqtincha to'xtatishni bekor qiladi
        payload["r"] = 1
    if app:  # qaysi dastur uchun (masalan "epropos") - boshqa dasturning kodi qabul qilinmaydi
        payload["a"] = app
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return PREFIX + _b64(data) + "." + _b64(sign(secret, data))


def read_code(code, trusted_key=None):
    """Kodni tekshiradi. trusted_key berilsa - faqat shu kalit bilan imzolangan kod qabul qilinadi.
    Qaytaradi: dict (s, u, i, n, p, c, k) yoki ValueError."""
    code = re.sub(r"\s+", "", str(code or ""))
    if not code.startswith(PREFIX) or "." not in code:
        raise ValueError("Kod noto'g'ri")
    body, _, sig = code[len(PREFIX):].partition(".")
    try:
        data, signature = _unb64(body), _unb64(sig)
        payload = json.loads(data.decode())
        key = key_from_text(payload["k"])
    except (ValueError, KeyError, TypeError):
        raise ValueError("Kod noto'g'ri")
    if trusted_key and key != trusted_key:
        raise ValueError("Bu kod boshqa sotuvchiniki")
    if not verify(key, data, signature):
        raise ValueError("Kod noto'g'ri (imzo mos emas)")
    return payload


# --- vaqtincha to'xtatish: admin panel imzolangan holat ro'yxatini e'lon qiladi, EproPos internetda tekshiradi

def status_topic(public):
    """Sotuvchining holat kanali nomi (ochiq kalitdan)."""
    return "epropos-v-" + hashlib.sha256(public).hexdigest()[:20]


def make_status(secret, suspended, ts):
    """suspended - to'xtatilgan do'kon ID lari; ts - vaqt (eskisi yangisini bosib ketmasligi uchun)."""
    data = json.dumps({"t": "status", "ts": int(ts), "x": sorted(set(suspended))}, separators=(",", ":")).encode()
    return "ST1-" + _b64(data) + "." + _b64(sign(secret, data))


def read_status(text, public):
    text = str(text or "").strip()
    if not text.startswith("ST1-") or "." not in text:
        raise ValueError("Holat noto'g'ri")
    body, _, sig = text[4:].partition(".")
    data = _unb64(body)
    if not verify(public, data, _unb64(sig)):
        raise ValueError("Holat imzosi mos emas")
    payload = json.loads(data.decode())
    if payload.get("t") != "status":
        raise ValueError("Holat noto'g'ri")
    return payload
