"""Hisobotlar markazi: bo'limlar, filtrlar, jami, Excel."""

import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_api import Client  # noqa: E402
from test_sync import start  # noqa: E402


class ReportsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.proc, url = start("hub", cls.tmp.name, "hub")
        cls.c = c = Client(url).pin("1234")
        _, cat = c.call("POST", "/api/categories", {"name": "Hisobot kat"})
        _, cls.p1 = c.call("POST", "/api/products", {"name": "H tovar 1", "price": 10000, "cost": 6000, "stock": 50, "category_id": cat["id"]})
        _, cls.p2 = c.call("POST", "/api/products", {"name": "H tovar 2", "price": 5000, "cost": 2000, "stock": 5, "min_stock": 10})
        cls.cat = cat
        _, cls.cust = c.call("POST", "/api/customers", {"name": "Hisobot mijoz", "phone": "+998 91 555 66 77", "gender": "m"})
        c.call("POST", "/api/sales", {"items": [{"product_id": cls.p1["id"], "qty": 3}], "method": "cash", "customer_id": cls.cust["id"]})
        c.call("POST", "/api/sales", {"items": [{"product_id": cls.p2["id"], "qty": 2}], "method": "card"})
        _, sup = c.call("POST", "/api/suppliers", {"name": "Hisobot ta'minotchi"})
        cls.sup = sup
        c.call("POST", "/api/purchases", {"supplier_id": sup["id"], "items": [{"product_id": cls.p1["id"], "qty": 10, "cost": 6000}],
                                          "paid": 20000, "account": "cash"})
        c.call("POST", "/api/stock/writeoff", {"comment": "Singan", "items": [{"product_id": cls.p2["id"], "qty": 1}]})
        cls.today = date.today().isoformat()

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.tmp.cleanup()

    def run_report(self, key, **params):
        q = "&".join(f"{k}={v}" for k, v in dict({"from": self.today, "to": self.today}, **params).items())
        status, res = self.c.call("GET", f"/api/reports/run/{key}?{q}")
        self.assertEqual(status, 200, (key, res))
        return res

    def test_catalog_sections(self):
        _, lst = self.c.call("GET", "/api/reports/list")
        self.assertEqual(set(lst["sections"]), {"sales", "crm", "stock", "finance"})
        only_all = {r["key"] for r in lst["reports"] if not r["sections"]}
        self.assertEqual(only_all, {"staff_sales", "suppliers"})  # faqat "Barchasi" da
        self.assertTrue(lst["options"]["categories"] and lst["options"]["cashiers"])
        for r in lst["reports"]:  # hamma hisobotlar ishlaydi va Excel beradi
            res = self.run_report(r["key"])
            self.assertTrue(res["columns"])
            with self.c.opener.open(f"{self.c.base}/api/reports/xlsx/{r['key']}?from={self.today}&to={self.today}") as f:
                self.assertEqual(f.read(2), b"PK", r["key"])  # Excel (zip) fayl

    def test_numbers_and_filters(self):
        res = self.run_report("sales_daily")
        self.assertEqual((res["totals"]["orders"], res["totals"]["revenue"], res["totals"]["profit"]), (2, 40000, 18000))
        cards = {c["label"]: c["value"] for c in res["cards"]}
        self.assertEqual(cards["Daromad (sof)"], 40000)
        self.assertEqual(self.run_report("sales_daily", method="card")["totals"]["revenue"], 10000)
        self.assertEqual(self.run_report("sales_daily", customer=self.cust["id"])["totals"]["revenue"], 30000)
        self.assertEqual(self.run_report("sales_daily", category=self.cat["id"])["totals"]["revenue"], 30000)
        self.assertEqual(self.run_report("sales_daily", hour_from=0, hour_to=0)["totals"].get("orders", 0) in (0, 2), True)
        self.assertEqual(self.run_report("sales_daily", group="month")["rows"][0]["day"], self.today[:7])
        prods = self.run_report("sales_products", category=self.cat["id"])["rows"]
        self.assertEqual([p["name"] for p in prods], ["H tovar 1"])
        self.assertEqual(self.run_report("customers_sales")["rows"][0]["name"], "Hisobot mijoz")
        stock = {r["name"]: r for r in self.run_report("stock_balance")["rows"]}
        self.assertEqual((stock["H tovar 1"]["stock"], stock["H tovar 2"]["state"]), (57, "Kam qolgan"))
        flow = {r["name"]: r for r in self.run_report("stock_flow")["rows"]}
        self.assertEqual((flow["H tovar 1"]["qty_in"], flow["H tovar 1"]["qty_out"], flow["H tovar 1"]["closing"]), (60, 3, 57))
        self.assertEqual(self.run_report("writeoffs")["totals"]["value"], 2000)
        self.assertIn("H tovar 2", [r["name"] for r in self.run_report("reorder")["rows"]])
        sup = self.run_report("suppliers", supplier=self.sup["id"])["rows"][0]
        self.assertEqual((sup["received"], sup["paid"], sup["balance"]), (60000, 20000, 40000))
        profit = {r["item"]: r["amount"] for r in self.run_report("profit")["rows"]}
        self.assertEqual(profit["Yalpi foyda"], 18000)
        staff = self.run_report("staff_sales")["rows"]
        self.assertEqual(staff[0]["orders"], 2)
        self.assertEqual(self.c.call("GET", "/api/reports/run/sales_daily?from=bad")[0], 400)


if __name__ == "__main__":
    unittest.main()
