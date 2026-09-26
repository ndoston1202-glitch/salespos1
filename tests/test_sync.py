"""Kompyuter (hub) va telefon (phone) o'rtasida sinxronlash testlari.

Ikkala server alohida jarayonda ishga tushadi (xuddi haqiqiy kompyuter va telefon kabi)."""

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_api import Client  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start(role, tmp, name):
    port = free_port()
    env = dict(os.environ, EPROPOS_ROLE=role, EPROPOS_DB=os.path.join(tmp, name + ".db"),
               EPROPOS_UPLOADS=os.path.join(tmp, name + "_up"), EPROPOS_PORT=str(port))
    with open(os.path.join(tmp, name + ".log"), "w") as log:
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py"), "--no-browser"], env=env,
                                stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            return proc, base
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(open(os.path.join(tmp, name + ".log")).read())


class SyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.hub_proc, cls.hub_url = start("hub", cls.tmp.name, "hub")
        cls.phone_proc, cls.phone_url = start("phone", cls.tmp.name, "phone")
        cls.hub = Client(cls.hub_url).pin("1234")
        phone = Client(cls.phone_url).pin("1234")  # telefondagi boshlang'ich administrator
        # telefonda hali ma'lumot yo'q - kompyuterga ulanganda hammasi kompyuterdan olinadi
        status, res = phone.call("POST", "/api/sync/connect", {"url": cls.hub_url, "pin": "1234"})
        assert status == 200, res
        assert res["cloned"], res
        cls.phone = Client(cls.phone_url).pin("1234")  # kompyuterdagi administrator paroli bilan

    @classmethod
    def tearDownClass(cls):
        for p in (cls.hub_proc, cls.phone_proc):
            p.terminate()
            p.wait(5)
        cls.tmp.cleanup()

    def sync(self):
        status, st = self.phone.call("POST", "/api/sync/now")
        self.assertEqual((status, st.get("state")), (200, "ok"), st)

    def product(self, client, name):
        return next((p for p in client.call("GET", "/api/products")[1] if p["name"] == name), None)

    def test_clone_and_ids(self):
        hub_products = {p["name"] for p in self.hub.call("GET", "/api/products")[1]}
        phone_products = {p["name"] for p in self.phone.call("GET", "/api/products")[1]}
        self.assertTrue(hub_products)
        self.assertEqual(hub_products, phone_products)
        _, st = self.phone.call("GET", "/api/sync/status")
        self.assertTrue(st["paired"])
        self.assertGreater(st["node"], 0)
        # telefonda yaratilgan yozuv ID si telefon oralig'ida - kompyuter ID lari bilan to'qnashmaydi
        _, c = self.phone.call("POST", "/api/categories", {"name": "Telefon kategoriya"})
        self.assertGreaterEqual(c["id"], st["node"] * 10 ** 12)
        self.sync()
        _, cats = self.hub.call("GET", "/api/categories")
        self.assertIn("Telefon kategoriya", [x["name"] for x in cats])
        # kompyuterda keyingi yozuv o'z oralig'ida qoladi
        _, c2 = self.hub.call("POST", "/api/categories", {"name": "Kompyuter kategoriya"})
        self.assertLess(c2["id"], 10 ** 12)
        _, devices = self.hub.call("GET", "/api/sync/status")
        self.assertEqual(len(devices["devices"]), 1)

    def test_offline_sales_merge_stock(self):
        _, p = self.hub.call("POST", "/api/products", {"name": "Sinx tovar", "price": 5000, "stock": 20})
        self.sync()
        phone_p = self.product(self.phone, "Sinx tovar")
        self.assertEqual(phone_p["stock"], 20)
        # ikkala joyda bir vaqtda (oflayn) sotiladi
        s1 = self.hub.call("POST", "/api/sales", {"items": [{"product_id": p["id"], "qty": 3}], "method": "cash"})
        s2 = self.phone.call("POST", "/api/sales", {"items": [{"product_id": phone_p["id"], "qty": 5}], "method": "card"})
        self.assertEqual((s1[0], s2[0]), (200, 200))
        self.assertEqual(self.product(self.phone, "Sinx tovar")["stock"], 15)
        self.sync()
        self.assertEqual(self.product(self.hub, "Sinx tovar")["stock"], 12)   # 20 - 3 - 5
        self.assertEqual(self.product(self.phone, "Sinx tovar")["stock"], 12)
        # telefondagi savdo kompyuter hisobotida
        _, sale = self.hub.call("GET", f"/api/sales/{s2[1]['id']}")
        self.assertEqual((sale["total"], sale["payment_method"]), (25000, "card"))
        # telefonda qaytarilsa - kompyuterda ham qaytariladi, qoldiq tiklanadi
        item = sale["items"][0]
        self.assertEqual(self.phone.call("POST", f"/api/sales/{sale['id']}/return",
                                         {"items": [{"item_id": item["id"], "qty": 2}]})[0], 200)
        self.sync()
        _, sale = self.hub.call("GET", f"/api/sales/{sale['id']}")
        self.assertEqual((sale["returned"], sale["items"][0]["returned_qty"]), (10000, 2))
        self.assertEqual(self.product(self.hub, "Sinx tovar")["stock"], 14)

    def test_edits_both_ways(self):
        _, cust = self.phone.call("POST", "/api/customers", {"name": "Telefon Mijoz", "phone": "+998 93 000 11 22", "gender": "f"})
        _, p = self.hub.call("POST", "/api/products", {"name": "Narx tovar", "price": 1000})
        self.sync()
        _, found = self.hub.call("GET", "/api/customers?q=Telefon%20Mijoz")
        self.assertEqual([c["id"] for c in found], [cust["id"]])
        # kompyuterda narx o'zgardi -> telefonga tushadi
        self.hub.call("PUT", f"/api/products/{p['id']}", {"name": "Narx tovar", "price": 1500})
        self.sync()
        self.assertEqual(self.product(self.phone, "Narx tovar")["price"], 1500)
        # ikkalasida o'zgarsa - oxirgisi qoladi
        self.hub.call("PUT", f"/api/products/{p['id']}", {"name": "Narx tovar", "price": 1600})
        time.sleep(0.02)
        self.phone.call("PUT", f"/api/products/{p['id']}", {"name": "Narx tovar", "price": 1700})
        self.sync()
        self.assertEqual(self.product(self.hub, "Narx tovar")["price"], 1700)
        self.assertEqual(self.product(self.phone, "Narx tovar")["price"], 1700)
        # o'chirish ham o'tadi (mahsulot yashiriladi)
        self.hub.call("DELETE", f"/api/products/{p['id']}")
        self.sync()
        self.assertIsNone(self.product(self.phone, "Narx tovar"))
        # telefonda qo'shilgan xodim kompyuterda o'z paroli bilan kira oladi
        self.phone.call("POST", "/api/users", {"first_name": "Mobil", "phone": "900770077", "role": "staff",
                                                "permissions": ["cashier"], "pin": "7788"})
        self.sync()
        status, me = Client(self.hub_url).call("POST", "/api/login", {"pin": "7788"})
        self.assertEqual((status, me["full_name"]), (200, "Mobil"))

    def test_offline_hub(self):
        _, st = self.phone.call("GET", "/api/sync/status")
        self.assertEqual(st["role"], "phone")
        # noto'g'ri token bilan kompyuter rad etadi
        self.assertEqual(Client(self.hub_url).call("POST", "/api/sync/exchange", {"token": "x", "changes": []})[0], 401)
        self.assertEqual(Client(self.hub_url).call("POST", "/api/sync/pair", {"pin": "0000", "node": 5})[0], 401)
        _, hello = Client(self.hub_url).call("GET", "/api/sync/hello")
        self.assertEqual((hello["app"], hello["role"]), ("EproPos", "hub"))

    def test_standalone_phone_merges(self):
        """Telefon avval kompyutersiz ishlatilgan bo'lsa - ulanganda ikkala baza birlashadi."""
        proc, url = start("phone", self.tmp.name, "phone2")
        try:
            solo = Client(url).pin("1234")
            _, p = solo.call("POST", "/api/products", {"name": "Yakka tovar", "price": 3000, "stock": 10})
            self.assertEqual(solo.call("POST", "/api/sales", {"items": [{"product_id": p["id"], "qty": 4}], "method": "cash"})[0], 200)
            status, res = solo.call("POST", "/api/sync/connect", {"url": self.hub_url, "pin": "1234"})
            self.assertEqual((status, res["cloned"]), (200, False))
            hub_p = self.product(self.hub, "Yakka tovar")
            self.assertEqual(hub_p["stock"], 6)
            self.assertIsNotNone(self.product(solo, "Non"))  # kompyuterdagi tovarlar ham keldi
        finally:
            proc.terminate()
            proc.wait(5)


if __name__ == "__main__":
    unittest.main()
