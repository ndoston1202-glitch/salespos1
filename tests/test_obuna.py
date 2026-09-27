"""Obuna: sinov muddati, muddat tugaganda bloklash, sotuvchi kodi bilan faollashtirish."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import obuna  # noqa: E402
from test_api import Client  # noqa: E402
from test_sync import start  # noqa: E402


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

    def run_at(self, day):
        """Kompyuterni berilgan sanada (qayta) ishga tushiradi - baza o'sha."""
        self.stop()
        self.proc, url = start("hub", self.tmp.name, "hub", EPROPOS_TODAY=day)
        return Client(url).pin("1234")

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
