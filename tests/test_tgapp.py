"""Telegram ilova (Mini App): imzo tekshiruvi, tunnel orqali faqat Telegram bilan kirish, akkaunt bog'lash."""

import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telegram  # noqa: E402
from test_api import Client  # noqa: E402
from test_sync import FAKE_TUNNEL, FakeRelay, start  # noqa: E402

TOKEN = "123456789:" + "A" * 35


def init_data(tg_id, token=TOKEN, age=0, name="Ali"):
    fields = {"auth_date": str(int(time.time()) - age), "query_id": "AAE1",
              "user": json.dumps({"id": tg_id, "first_name": name}, separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


class FakeTelegram(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())
        method = self.path.rsplit("/", 1)[-1]
        self.calls.append((method, {k: v[0] for k, v in body.items()}))
        result = {"id": 1, "username": "dokon_kassa_bot", "first_name": "Kassa"} if method == "getMe" else True
        out = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)


class InitDataTest(unittest.TestCase):
    def test_signature(self):
        self.assertEqual(telegram.check_init_data(TOKEN, init_data(42))["id"], 42)
        self.assertIsNone(telegram.check_init_data(TOKEN, init_data(42, token="1:" + "B" * 35)))  # boshqa bot
        self.assertIsNone(telegram.check_init_data(TOKEN, init_data(42, age=2 * 86400)))  # eskirgan
        self.assertIsNone(telegram.check_init_data(TOKEN, init_data(42).replace("Ali", "Vali")))  # o'zgartirilgan
        self.assertIsNone(telegram.check_init_data(TOKEN, "hash=abc"))


class TgAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.servers = []
        for handler in (FakeRelay, FakeTelegram):
            srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            cls.servers.append(srv)
        fake = os.path.join(cls.tmp.name, "fake_cloudflared.py")
        with open(fake, "w") as f:
            f.write(FAKE_TUNNEL)
        base = lambda s: f"http://127.0.0.1:{s.server_address[1]}"
        cls.proc, cls.url = start("hub", cls.tmp.name, "hub", EPROPOS_RELAY=base(cls.servers[0]),
                                  TELEGRAM_API=base(cls.servers[1]), EPROPOS_CLOUDFLARED=f"{sys.executable} {fake}",
                                  EPROPOS_TUNNEL_RE=r"http://127\.0\.0\.1:\d+", NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
        cls.admin = Client(cls.url).pin("1234")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        for s in cls.servers:
            s.shutdown()
        cls.tmp.cleanup()

    def test_flow(self):
        status, cfg = self.admin.call("PUT", "/api/integrations/tg_app", {"token": TOKEN, "enabled": True})
        self.assertEqual((status, cfg["bot"]["username"]), (200, "dokon_kassa_bot"), cfg)
        for _ in range(100):  # tunnel ochilib, botdagi tugma manzili o'rnatilguncha
            cfg = self.admin.call("GET", "/api/integrations/tg_app")[1]
            if cfg["menu_ok"]:
                break
            time.sleep(0.1)
        self.assertTrue(cfg["menu_ok"], cfg)
        public = cfg["internet"]["url"]
        menu = [c for m, c in FakeTelegram.calls if m == "setChatMenuButton"][-1]
        self.assertEqual(json.loads(menu["menu_button"])["web_app"]["url"], public + "/")

        # internetdan: sahifa ochiladi, lekin PIN bilan kirib bo'lmaydi
        phone = Client(public)
        with phone.opener.open(public + "/") as res:
            self.assertIn(b"<html", res.read().lower())
        self.assertEqual(phone.call("POST", "/api/login", {"pin": "1234"})[0], 403)
        self.assertEqual(phone.call("GET", "/api/products")[0], 401)
        self.assertEqual(phone.call("POST", "/api/tg/auth", {"init_data": init_data(555, token="9:" + "C" * 35)})[0], 401)
        # birinchi marta - PIN bilan bog'lash, keyin avtomatik
        status, res = phone.call("POST", "/api/tg/auth", {"init_data": init_data(555)})
        self.assertEqual((status, res.get("need_pin"), res.get("tg_name")), (200, True, "Ali"))
        self.assertEqual(phone.call("POST", "/api/tg/auth", {"init_data": init_data(555), "pin": "0000"})[0], 401)
        status, me = phone.call("POST", "/api/tg/auth", {"init_data": init_data(555), "pin": "1234"})
        self.assertEqual((status, me["role"]), (200, "admin"))
        self.assertEqual(phone.call("GET", "/api/products")[0], 200)
        other = Client(public)
        status, me = other.call("POST", "/api/tg/auth", {"init_data": init_data(555)})
        self.assertEqual((status, me.get("full_name")), (200, "Administrator"))
        cfg = self.admin.call("GET", "/api/integrations/tg_app")[1]
        self.assertEqual([u["tg_user_id"] for u in cfg["linked"]], ["555"])
        # uzilsa - yana PIN so'raladi
        self.admin.call("DELETE", f"/api/integrations/tg_app/links/{cfg['linked'][0]['id']}")
        self.assertTrue(Client(public).call("POST", "/api/tg/auth", {"init_data": init_data(555)})[1].get("need_pin"))
        # o'chirilsa - internetdan faqat sinxronlash qoladi
        self.admin.call("PUT", "/api/integrations/tg_app", {"enabled": False})
        self.assertEqual(Client(public).call("GET", "/api/products")[0], 404)
        self.assertEqual(Client(public).call("GET", "/api/sync/hello")[0], 200)


if __name__ == "__main__":
    unittest.main()
