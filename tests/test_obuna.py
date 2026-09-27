"""Obuna: sinov muddati, muddat tugaganda bloklash, sotuvchi kodi bilan faollashtirish."""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import obuna  # noqa: E402
from test_api import Client  # noqa: E402
from test_sync import FakeRelay, start  # noqa: E402


class ObunaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proc = None

    def tearDown(self):
        self.stop()
        self.tmp.cleanup()

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(5)
            self.proc = None

    def run_at(self, day, **extra):
        """Kompyuterni berilgan sanada (qayta) ishga tushiradi - baza o'sha."""
        self.stop()
        self.proc, url = start("hub", self.tmp.name, "hub", EPROPOS_TODAY=day, **extra)
        return Client(url).pin("1234")

    def test_suspend_resume(self):
        relay = ThreadingHTTPServer(("127.0.0.1", 0), FakeRelay)
        threading.Thread(target=relay.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{relay.server_address[1]}"
        try:
            c = self.run_at("2027-01-01", EPROPOS_RELAY=base, NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
            shop = c.call("GET", "/api/license")[1]["shop_id"]
            vendor = obuna.new_secret()
            topic = obuna.status_topic(obuna.public_key(vendor))
            c.call("POST", "/api/license", {"code": obuna.make_code(vendor, shop, "2027-06-01")})

            def publish(ids, ts, secret=vendor):
                req = urllib.request.Request(f"{base}/{topic}", data=obuna.make_status(secret, ids, ts).encode(), method="POST")
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req).read()

            publish(["AAAA-BBBB-CCCC"], 100)  # boshqa do'kon to'xtatilgan - bizga ta'sir yo'q
            self.assertEqual(c.call("POST", "/api/license/check")[1]["state"], "active")
            publish([shop], 200)
            publish([], 150, obuna.new_secret())  # begona imzo - e'tiborsiz
            self.assertEqual(c.call("POST", "/api/license/check")[1]["state"], "suspended")
            self.assertEqual(c.call("GET", "/api/products")[0], 402)
            FakeRelay.topics[topic] = FakeRelay.topics[topic][:1]  # eski (ts=100) xabar qayta kelsa ham
            self.assertEqual(c.call("POST", "/api/license/check")[1]["state"], "suspended")
            publish([], 300)  # davom ettirildi
            self.assertEqual(c.call("POST", "/api/license/check")[1]["state"], "active")
            self.assertEqual(c.call("GET", "/api/products")[0], 200)
            # internetsiz: davom ettirish kodi
            publish([shop], 400)
            self.assertEqual(c.call("POST", "/api/license/check")[1]["state"], "suspended")
            code = obuna.make_code(vendor, shop, "2027-06-01", resume=True)
            self.assertEqual(c.call("POST", "/api/license", {"code": code})[1]["state"], "active")
        finally:
            relay.shutdown()

    def test_trial_block_activate(self):
        c = self.run_at("2027-01-01")
        _, lic = c.call("GET", "/api/license")
        self.assertEqual((lic["state"], lic["trial"], lic["until"]), ("active", True, "2027-01-15"))
        shop = lic["shop_id"]
        self.assertRegex(shop, r"^[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}$")

        c = self.run_at("2027-01-17")  # sinov tugadi, 2 kun imtiyoz
        self.assertEqual(c.call("GET", "/api/license")[1]["state"], "grace")
        self.assertEqual(c.call("GET", "/api/products")[0], 200)

        c = self.run_at("2027-01-20")  # bloklandi
        self.assertEqual(c.call("GET", "/api/license")[1]["state"], "expired")
        self.assertEqual(c.call("GET", "/api/products")[0], 402)
        self.assertEqual(c.call("POST", "/api/sales", {"items": [], "method": "cash"})[0], 402)
        _, st = c.call("GET", "/api/settings")
        self.assertEqual(st["license"]["state"], "expired")

        vendor = obuna.new_secret()
        # boshqa do'kon kodi va muddati o'tgan kod qabul qilinmaydi
        other = obuna.make_code(vendor, "AAAA-BBBB-CCCC", "2027-12-31")
        self.assertEqual(c.call("POST", "/api/license", {"code": other})[0], 400)
        old = obuna.make_code(vendor, shop, "2027-01-10")
        self.assertEqual(c.call("POST", "/api/license", {"code": old})[0], 400)
        self.assertEqual(c.call("POST", "/api/license", {"code": "EP1-buzilgan.kod"})[0], 400)

        code = obuna.make_code(vendor, shop, "2027-02-20", "Doston", "+998 90 123 45 67", "Do'kon")
        status, lic = c.call("POST", "/api/license", {"code": code})
        self.assertEqual((status, lic["state"], lic["until"], lic["vendor"]), (200, "active", "2027-02-20", "Doston"))
        self.assertEqual(c.call("GET", "/api/products")[0], 200)

        # boshqa sotuvchi kaliti bilan kod endi qabul qilinmaydi
        stranger = obuna.make_code(obuna.new_secret(), shop, "2030-01-01")
        self.assertEqual(c.call("POST", "/api/license", {"code": stranger})[0], 400)

        # soatni orqaga qo'yish yordam bermaydi
        c = self.run_at("2027-01-10")
        self.assertEqual(c.call("GET", "/api/license")[1]["days_left"], 31)  # 01-20 dan hisoblanadi

        c = self.run_at("2027-02-17")
        self.assertEqual(c.call("GET", "/api/license")[1]["state"], "warning")
        c = self.run_at("2027-02-25")
        self.assertEqual(c.call("GET", "/api/license")[1]["state"], "expired")
        # yangi to'lov - yangi kod
        code = obuna.make_code(vendor, shop, "2027-03-25")
        self.assertEqual(c.call("POST", "/api/license", {"code": code})[1]["state"], "active")


if __name__ == "__main__":
    unittest.main()
