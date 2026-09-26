"""Telefonda EproPos serverini ishga tushirish (MainActivity chaqiradi).

Server faqat telefonning o'zida (127.0.0.1) ochiladi: ilova kompyutersiz ham to'liq ishlaydi,
kompyuter bilan bitta Wi-Fi'da bo'lganda esa server.SyncWorker ma'lumotlarni almashtiradi."""

import os
import threading

_server = None


def start(data_dir, static_dir, port=8100, apk_version=0):
    """Serverni fonda ishga tushiradi va ochilgan portni qaytaradi."""
    global _server
    if _server is not None:
        return _server.server_address[1]
    os.makedirs(data_dir, exist_ok=True)
    os.environ["EPROPOS_ROLE"] = "phone"
    os.environ["EPROPOS_DB"] = os.path.join(data_dir, "epropos.db")
    os.environ["EPROPOS_UPLOADS"] = os.path.join(data_dir, "uploads")
    os.environ["EPROPOS_STATIC"] = static_dir
    os.environ["EPROPOS_APK_VERSION"] = str(apk_version)  # yangilanishni tekshirish uchun
    import server  # sozlamalar (yo'llar) import paytida o'qiladi

    last = None
    for p in range(port, port + 20):  # port band bo'lsa - keyingisi
        try:
            _server = server.make_server(port=p, host="127.0.0.1")
            break
        except OSError as e:
            last = e
    else:
        raise last
    threading.Thread(target=_server.serve_forever, daemon=True, name="epropos-http").start()
    return _server.server_address[1]
