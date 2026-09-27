"""Sotuvchi admin paneli: mijoz, to'lov, kod yaratish, zaxira."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "admin"))

TMP = tempfile.TemporaryDirectory()
os.environ["EPROPOS_ADMIN_DATA"] = TMP.name
os.environ["EPROPOS_TODAY"] = "2027-01-10"
import admin  # noqa: E402
import obuna  # noqa: E402

del os.environ["EPROPOS_TODAY"]  # boshqa testlarga ta'sir qilmasin (admin.today() har safar o'qiydi)


class AdminTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = admin.make_server(0)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def call(self, method, path, body=None, host=None):
        req = urllib.request.Request(self.url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **({"Host": host} if host else {})})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req) as res:
                raw = res.read()
                return res.status, (json.loads(raw) if res.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_flow(self):
        os.environ["EPROPOS_TODAY"] = "2027-01-10"
        try:
            self.call("PUT", "/api/settings", {"vendor_name": "Doston", "vendor_phone": "+998 90 111 22 33"})
            self.assertEqual(self.call("POST", "/api/clients", {"business": "Baraka", "shop_id": "xyz"})[0], 400)
            status, c = self.call("POST", "/api/clients", {"business": "Baraka market", "owner": "Ali", "tariff": 150000,
                                                           "shop_id": "1a2b3c4d5e6f"})
            self.assertEqual((status, c["shop_id"], c["status"]), (200, "1A2B-3C4D-5E6F", "new"))
            status, res = self.call("POST", f"/api/clients/{c['id']}/pay", {"months": 1, "amount": 150000})
            self.assertEqual((status, res["until"]), (200, "2027-02-10"))
            info = obuna.read_code(res["code"])
            self.assertEqual((info["s"], info["u"], info["n"], info["p"]), ("1A2B-3C4D-5E6F", "2027-02-10", "Doston", "+998 90 111 22 33"))
            # oldindan to'lov - oxirgi sanadan uzaytiriladi
            _, res = self.call("POST", f"/api/clients/{c['id']}/pay", {"months": 3, "amount": 450000})
            self.assertEqual(res["until"], "2027-05-10")
            _, st = self.call("GET", "/api/state")
            self.assertEqual((st["stats"]["active"], st["stats"]["paid_this_month"] >= 600000), (1, True))
            _, detail = self.call("GET", f"/api/clients/{c['id']}")
            self.assertEqual(len(detail["payments"]), 2)
            # to'lovsiz kod
            _, res = self.call("POST", f"/api/clients/{c['id']}/code", {"until": "2027-06-01", "save": True})
            self.assertEqual(res["client"]["paid_until"], "2027-06-01")
            # vaqtincha to'xtatish: imzolangan ro'yxat e'lon qilinadi, davom ettirishda kod beriladi
            from http.server import ThreadingHTTPServer
            from test_sync import FakeRelay
            relay = ThreadingHTTPServer(("127.0.0.1", 0), FakeRelay)
            threading.Thread(target=relay.serve_forever, daemon=True).start()
            admin.sync.RELAY = f"http://127.0.0.1:{relay.server_address[1]}"
            os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
            try:
                _, res = self.call("POST", f"/api/clients/{c['id']}/suspend", {"suspended": True})
                self.assertEqual(res["client"]["status"], "suspended")
                admin.publisher.publish()
                secret = self.server.secret
                topic = obuna.status_topic(obuna.public_key(secret))
                status = obuna.read_status(FakeRelay.topics[topic][-1], obuna.public_key(secret))
                self.assertEqual(status["x"], ["1A2B-3C4D-5E6F"])
                _, res = self.call("POST", f"/api/clients/{c['id']}/suspend", {"suspended": False})
                self.assertEqual((res["client"]["status"], obuna.read_code(res["code"]).get("r")), ("active", 1))
                admin.publisher.publish()
                self.assertEqual(obuna.read_status(FakeRelay.topics[topic][-1], obuna.public_key(secret))["x"], [])
            finally:
                relay.shutdown()
            # demo: yangi mijozga sotuvchi belgilagan sinov muddati
            self.assertEqual(self.call("POST", "/api/clients", {"business": "Demo", "demo_until": "2027-01-17"})[0], 400)
            _, d = self.call("POST", "/api/clients", {"business": "Demo do'kon", "shop_id": "BBBB-CCCC-DDDD",
                                                      "demo_until": "2027-01-17"})
            self.assertEqual((d["paid_until"], d["demo"], obuna.read_code(d["code"])["u"]), ("2027-01-17", True, "2027-01-17"))
            # boshqa sayt (Host) orqali so'rov rad etiladi
            self.assertEqual(self.call("GET", "/api/state", host="evil.example")[0], 403)
            # zaxira: kalit va ma'lumotlar
            status, raw = self.call("GET", "/api/backup")
            names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
            self.assertIn("vendor.key", names)
            self.assertIn("admin.sql", names)
        finally:
            del os.environ["EPROPOS_TODAY"]


if __name__ == "__main__":
    unittest.main()
