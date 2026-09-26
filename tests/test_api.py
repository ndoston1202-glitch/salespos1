"""API testlari:  python -m unittest discover tests"""

import base64
import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, Request, build_opener

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(self.base + path, data=data, method=method)
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req) as res:
                return res.status, json.loads(res.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def pin(self, pin):
        status, _ = self.call("POST", "/api/login", {"pin": pin})
        assert status == 200, status
        return self

    def login(self, username, password):
        status, _ = self.call("POST", "/api/login", {"username": username, "password": password})
        assert status == 200, status
        return self


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["EPROPOS_DB"] = os.path.join(cls.tmp.name, "test.db")
        import server

        server.DB_PATH = os.environ["EPROPOS_DB"]
        server.UPLOAD_DIR = os.path.join(cls.tmp.name, "uploads")
        cls.server = server.make_server(port=0, host="127.0.0.1")
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.admin = Client(cls.base).pin("1234")
        cls.admin.call("POST", "/api/users", {"first_name": "Kassir", "phone": "+998 90 000 00 01",
                                              "role": "cashier", "pin": "1111"})
        cls.admin.call("POST", "/api/users", {"first_name": "Ofitsiant", "phone": "+998 90 000 00 02",
                                              "role": "staff", "permissions": [], "pin": "2222"})
        cls.cashier = Client(cls.base).pin("1111")
        cls.waiter = Client(cls.base).pin("2222")  # hech qanday ruxsati yo'q xodim

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.conn.close()
        cls.tmp.cleanup()

    def setUp(self):
        import server
        server.LOGIN_GUARD.ok("127.0.0.1")  # noto'g'ri urinishlar testlar orasida yig'ilmasin

    def product(self, name, price=10000, stock=100, **extra):
        status, p = self.admin.call("POST", "/api/products", dict({"name": name, "price": price, "stock": stock}, **extra))
        assert status == 200, p
        return next(x for x in self.admin.call("GET", "/api/products")[1] if x["id"] == p["id"])

    def sell(self, client, items, method="cash", **extra):
        """items: [(product, qty), ...]"""
        body = dict({"items": [{"product_id": p["id"], "qty": q} for p, q in items], "method": method}, **extra)
        return client.call("POST", "/api/sales", body)

    def stock_of(self, product):
        return next(x for x in self.admin.call("GET", "/api/products")[1] if x["id"] == product["id"])["stock"]

    def test_login_required(self):
        status, _ = Client(self.base).call("GET", "/api/products")
        self.assertEqual(status, 401)

    def test_wrong_password(self):
        status, body = Client(self.base).call("POST", "/api/login", {"pin": "0000"})
        self.assertEqual(status, 401)
        self.assertIn("error", body)

    def test_static_index(self):
        from urllib.request import urlopen

        with urlopen(self.base + "/") as res:
            self.assertIn(b"EproPos", res.read())

    def test_menu_admin_only(self):
        status, _ = self.waiter.call("POST", "/api/products", {"name": "X", "price": 1})
        self.assertEqual(status, 403)
        status, _ = self.cashier.call("POST", "/api/products", {"name": "X", "price": 1})
        self.assertEqual(status, 403)
        status, _ = self.cashier.call("GET", "/api/users")
        self.assertEqual(status, 403)
        status, _ = self.waiter.call("GET", "/api/reports")
        self.assertEqual(status, 403)
        self.assertEqual(self.waiter.call("POST", "/api/sales", {"items": [], "method": "cash"})[0], 403)
        self.assertEqual(self.cashier.call("POST", "/api/purchases", {"items": []})[0], 403)

    def test_menu_crud(self):
        _, cat = self.admin.call("POST", "/api/categories", {"name": "Test kategoriya"})
        _, prod = self.admin.call("POST", "/api/products", {"name": "Test tovar", "price": "12000", "category_id": cat["id"],
                                                           "barcode": "1234567890123", "unit": "dona", "stock": 7})
        self.admin.call("PUT", f"/api/products/{prod['id']}", {"name": "Test tovar 2", "price": 15000, "category_id": cat["id"],
                                                              "barcode": "1234567890123", "unit": "dona", "stock": 999})
        _, products = self.admin.call("GET", "/api/products")
        found = next(p for p in products if p["id"] == prod["id"])
        self.assertEqual((found["name"], found["price"], found["stock"]), ("Test tovar 2", 15000, 7))  # qoldiq tahrirda o'zgarmaydi
        status, byb = self.cashier.call("GET", "/api/products/barcode/1234567890123")
        self.assertEqual((status, byb["id"]), (200, prod["id"]))
        self.assertEqual(self.cashier.call("GET", "/api/products/barcode/999")[0], 404)
        # bir xil shtrix-kod ikki tovarda bo'lmaydi
        status, err = self.admin.call("POST", "/api/products", {"name": "Boshqa", "price": 1, "barcode": "1234567890123"})
        self.assertEqual(status, 409)
        self.assertIn("Test tovar 2", err["error"])
        _, code = self.admin.call("GET", "/api/products/new-barcode")
        self.assertTrue(code["barcode"].startswith("200") and len(code["barcode"]) == 13)

        status, _ = self.admin.call("DELETE", f"/api/categories/{cat['id']}")
        self.assertEqual(status, 409)  # ichida tovar bor
        self.admin.call("DELETE", f"/api/products/{prod['id']}")
        status, _ = self.admin.call("DELETE", f"/api/categories/{cat['id']}")
        self.assertEqual(status, 200)

    def test_bad_price(self):
        status, _ = self.admin.call("POST", "/api/products", {"name": "X", "price": "abc"})
        self.assertEqual(status, 400)

    def test_deactivated_user_logged_out(self):
        _, u = self.admin.call("POST", "/api/users", {"first_name": "Vaqtincha", "phone": "900000009",
                                                      "role": "staff", "permissions": ["cashier"], "pin": "9191"})
        client = Client(self.base).pin("9191")
        self.admin.call("PUT", f"/api/users/{u['id']}", {"first_name": "Vaqtincha", "role": "staff",
                                                        "permissions": ["cashier"], "active": False})
        status, _ = client.call("GET", "/api/products")
        self.assertEqual(status, 401)
        self.assertEqual(Client(self.base).call("POST", "/api/login", {"pin": "9191"})[0], 401)

    def test_custom_permissions(self):
        status, u = self.admin.call("POST", "/api/users", {
            "first_name": "Aziz", "phone": "+998901234567", "pin": "3434",
            "role": "staff", "permissions": ["cashier", "products", "nonsense"],
        })
        self.assertEqual(status, 200)
        aziz = Client(self.base).pin("3434")
        _, me = aziz.call("GET", "/api/me")
        self.assertEqual(me["permissions"], ["cashier", "products"])
        self.assertEqual(aziz.call("GET", "/api/reports")[0], 403)
        self.assertEqual(aziz.call("POST", "/api/categories", {"name": "Aziz kat"})[0], 200)
        self.assertEqual(aziz.call("POST", "/api/purchases", {"items": []})[0], 403)  # ombor ruxsati yo'q

        # Ruxsat o'zgarsa darhol kuchga kiradi (qayta kirish shart emas)
        self.admin.call("PUT", f"/api/users/{u['id']}", {"first_name": "Aziz", "role": "staff", "permissions": ["reports"]})
        self.assertEqual(aziz.call("GET", "/api/reports")[0], 200)
        self.assertEqual(aziz.call("POST", "/api/categories", {"name": "X"})[0], 403)

        # Xodimlar ruxsati bor, lekin admin emas - admin yarata olmaydi
        self.admin.call("PUT", f"/api/users/{u['id']}", {"first_name": "Aziz", "role": "staff", "permissions": ["users"]})
        status, _ = aziz.call("POST", "/api/users", {"first_name": "Boss", "pin": "5656", "role": "admin"})
        self.assertEqual(status, 403)
        _, users = aziz.call("GET", "/api/users")
        admin_row = next(x for x in users if x["role"] == "admin")
        self.assertEqual(aziz.call("DELETE", f"/api/users/{admin_row['id']}")[0], 403)

        # O'chirish = bloklash
        self.assertEqual(self.admin.call("DELETE", f"/api/users/{u['id']}")[0], 200)
        self.assertEqual(aziz.call("GET", "/api/me")[0], 401)
        self.assertEqual(Client(self.base).call("POST", "/api/login", {"pin": "3434"})[0], 401)

    def test_network_info(self):
        status, info = self.waiter.call("GET", "/api/network")
        self.assertEqual(status, 200)
        self.assertIn("main", info)
        self.assertIsInstance(info["others"], list)
        if info["main"]:
            self.assertTrue(info["main"].startswith("http://"))
            self.assertNotIn(info["main"], info["others"])

    def test_dashboard(self):
        _, before = self.admin.call("GET", "/api/dashboard?period=today")
        prod = self.product("Dashboard tovar", 40000, cost=25000)
        self.assertEqual(self.sell(self.cashier, [(prod, 2)], "click")[0], 200)
        for period, size in (("today", 24), ("week", 7), ("year", 12)):
            status, d = self.admin.call("GET", f"/api/dashboard?period={period}")
            self.assertEqual(status, 200)
            self.assertEqual(len(d["series"]), size)
            self.assertEqual(sum(x["value"] for x in d["series"]), d["summary"]["revenue"])
        _, after = self.admin.call("GET", "/api/dashboard?period=today")
        self.assertEqual(after["today"]["revenue"] - before["today"]["revenue"], 80000)
        self.assertEqual(after["today"]["orders"] - before["today"]["orders"], 1)
        self.assertEqual(after["summary"]["items"] - before["summary"]["items"], 2)
        self.assertEqual(after["summary"]["profit"] - before["summary"]["profit"], 30000)
        self.assertIn("value", after["stock"])
        click = next(m for m in after["by_method"] if m["method"] == "click")
        self.assertGreaterEqual(click["revenue"], 80000)
        self.assertEqual(self.waiter.call("GET", "/api/dashboard")[0], 403)
        self.assertEqual(self.admin.call("GET", "/api/dashboard?period=x")[0], 400)

    def test_finance(self):
        _, types = self.admin.call("GET", "/api/finance/types")
        names = {t["name"]: t for t in types}
        topup = names["Mijoz balansini to'ldirish"]
        supplier = names["Ta'minotchiga pul berish"]
        self.assertEqual((topup["direction"], topup["is_system"]), ("in", 1))
        self.assertEqual((supplier["direction"], supplier["is_system"]), ("out", 1))

        # Dublikat bo'lmaydi (katta-kichik harf va bo'sh joylar farqi hisobga olinmaydi)
        status, _ = self.admin.call("POST", "/api/finance/types", {"name": "  mijoz  balansini TO'LDIRISH ", "direction": "in"})
        self.assertEqual(status, 409)
        status, rent = self.admin.call("POST", "/api/finance/types", {"name": "Ijara to'lovi", "direction": "out"})
        self.assertEqual(status, 200)
        self.assertEqual(self.admin.call("POST", "/api/finance/types", {"name": "X", "direction": "in"})[0], 400)
        self.assertEqual(self.admin.call("POST", "/api/finance/types", {"name": "Boshqa", "direction": "?"})[0], 400)
        # O'zgartirib/o'chirib bo'lmaydi
        self.assertEqual(self.admin.call("PUT", f"/api/finance/types/{rent['id']}", {"name": "Y"})[0], 404)
        self.assertEqual(self.admin.call("DELETE", f"/api/finance/types/{rent['id']}")[0], 404)

        _, before = self.admin.call("GET", "/api/finance/balance")
        cash0 = next(a for a in before["accounts"] if a["account"] == "cash")["balance"]
        _, e1 = self.admin.call("POST", "/api/finance/entries",
                                {"type_id": topup["id"], "account": "cash", "amount": 100000, "comment": "Ali aka"})
        _, e2 = self.admin.call("POST", "/api/finance/entries", {"type_id": rent["id"], "account": "cash", "amount": 30000})
        self.assertEqual(self.admin.call("POST", "/api/finance/entries", {"type_id": rent["id"], "account": "safe", "amount": 1})[0], 400)
        self.assertEqual(self.admin.call("POST", "/api/finance/entries", {"type_id": rent["id"], "account": "cash", "amount": 0})[0], 400)
        _, bal = self.admin.call("GET", "/api/finance/balance")
        self.assertEqual(next(a for a in bal["accounts"] if a["account"] == "cash")["balance"] - cash0, 70000)

        # Savdo tushumi ham kassaga tushadi
        _, paid = self.sell(self.cashier, [(self.product("Moliya tovar", 15000), 1)])
        order = paid
        _, bal2 = self.admin.call("GET", "/api/finance/balance")
        self.assertEqual(next(a for a in bal2["accounts"] if a["account"] == "cash")["balance"] - cash0, 70000 + paid["total"])

        # Bekor qilish: balansdan chiqadi, lekin ro'yxatda qoladi; ikki marta bekor qilib bo'lmaydi
        self.assertEqual(self.admin.call("POST", f"/api/finance/entries/{e2['id']}/cancel", {"reason": "xato"})[0], 200)
        self.assertEqual(self.admin.call("POST", f"/api/finance/entries/{e2['id']}/cancel")[0], 409)
        self.assertIn(self.admin.call("DELETE", f"/api/finance/entries/{e2['id']}")[0], (404, 405))  # o'chirib bo'lmaydi
        _, bal3 = self.admin.call("GET", "/api/finance/balance")
        self.assertEqual(next(a for a in bal3["accounts"] if a["account"] == "cash")["balance"] - cash0, 100000 + paid["total"])
        _, lst = self.admin.call("GET", "/api/finance/entries")
        mine = {e["id"]: e for e in lst["entries"] if e["source"] == "manual"}
        self.assertEqual(mine[e2["id"]]["status"], "cancelled")
        self.assertEqual(mine[e1["id"]]["comment"], "Ali aka")
        self.assertTrue(any(e["source"] == "sale" and e["id"] == order["id"] for e in lst["entries"]))
        _, only_out = self.admin.call("GET", "/api/finance/entries?direction=out")
        self.assertTrue(all(e["direction"] == "out" for e in only_out["entries"]))

        # Ruxsatsiz xodim kira olmaydi
        self.assertEqual(self.cashier.call("GET", "/api/finance/balance")[0], 403)

    def test_cancel_sale_refunds(self):
        prod = self.product("Qaytariladigan", 25000, stock=10)
        _, paid = self.sell(self.cashier, [(prod, 2)], "card")
        order = paid
        self.assertEqual(self.stock_of(prod), 8)
        card = lambda b: next(a for a in b["accounts"] if a["account"] == "card")["balance"]
        _, bal_before = self.admin.call("GET", "/api/finance/balance")
        _, rep_before = self.admin.call("GET", "/api/reports")

        self.assertEqual(self.waiter.call("POST", f"/api/finance/sales/{order['id']}/cancel")[0], 403)
        self.assertEqual(self.admin.call("POST", f"/api/finance/sales/{order['id']}/cancel", {"reason": "xato chek"})[0], 200)
        self.assertEqual(self.admin.call("POST", f"/api/finance/sales/{order['id']}/cancel")[0], 409)
        self.assertEqual(self.stock_of(prod), 10)  # tovar omborga qaytdi

        _, bal_after = self.admin.call("GET", "/api/finance/balance")
        self.assertEqual(card(bal_before) - card(bal_after), paid["total"])  # kirgan pul chiqdi
        _, rep_after = self.admin.call("GET", "/api/reports")
        self.assertEqual(rep_before["summary"]["revenue"] - rep_after["summary"]["revenue"], paid["total"])
        _, lst = self.admin.call("GET", "/api/finance/entries?source=sales")
        row = next(e for e in lst["entries"] if e["id"] == order["id"] and e["source"] == "sale")
        self.assertEqual((row["status"], row["cancel_reason"]), ("cancelled", "xato chek"))
        _, detail = self.admin.call("GET", f"/api/orders/{order['id']}")
        self.assertEqual(detail["status"], "refunded")  # o'chirilmadi, tarixda qoldi

    def test_crm_customers_and_debts(self):
        from datetime import date, timedelta
        today = date.today()
        # Mijoz: telefon normallashtiriladi va takrorlanmaydi
        status, ali = self.admin.call("POST", "/api/customers", {"name": "Ali Valiyev", "phone": "90 123-45-67", "gender": "m"})
        self.assertEqual((status, ali["phone"]), (200, "+998901234567"))
        self.assertEqual(self.admin.call("POST", "/api/customers", {"name": "Boshqa", "phone": "+998901234567", "gender": "f"})[0], 409)
        self.assertEqual(self.admin.call("POST", "/api/customers", {"name": "Ali", "phone": "12", "gender": "m"})[0], 400)
        self.assertEqual(self.admin.call("POST", "/api/customers", {"name": "Ali", "phone": "901112233", "gender": "x"})[0], 400)
        _, found = self.admin.call("GET", "/api/customers?q=4567")
        self.assertIn(ali["id"], [c["id"] for c in found])
        _, edited = self.admin.call("PUT", f"/api/customers/{ali['id']}", {"name": "Ali Valiyev", "phone": "901234567", "gender": "m"})
        self.assertEqual(edited["name"], "Ali Valiyev")

        # Nasiyaga sotish: mijoz va muddat shart
        prod = self.product("Qarz tovar", 60000)
        self.assertEqual(self.sell(self.cashier, [(prod, 1)], "debt")[0], 400)
        _, bal0 = self.admin.call("GET", "/api/finance/balance")
        status, paid = self.sell(self.cashier, [(prod, 1)], "debt", customer_id=ali["id"],
                                 due_date=str(today - timedelta(days=2)))
        order = paid
        self.assertEqual(status, 200)
        _, bal1 = self.admin.call("GET", "/api/finance/balance")
        self.assertEqual(bal1["total"], bal0["total"])  # qarzga sotuv kassaga pul keltirmaydi

        # Qo'lda qarz: 2 kundan keyin (vaqti keldi) va 10 kundan keyin (muddati bor)
        self.admin.call("POST", f"/api/customers/{ali['id']}/debts", {"amount": 20000, "due_date": str(today + timedelta(days=2))})
        self.admin.call("POST", f"/api/customers/{ali['id']}/debts", {"amount": 30000, "due_date": str(today + timedelta(days=10))})
        _, debts = self.admin.call("GET", "/api/debts")
        mine = {d["amount"]: d for d in debts["debts"] if d["customer_id"] == ali["id"]}
        self.assertEqual(mine[paid["total"]]["bucket"], "overdue")
        self.assertEqual(mine[20000]["bucket"], "due")
        self.assertEqual(mine[30000]["bucket"], "later")

        # To'lov usullari -> hisoblar: naqd->naqd, click->karta, terminal/ko'chirish->hisob raqam
        acc = lambda b, k: next(a for a in b["accounts"] if a["account"] == k)["balance"]
        overdue = mine[paid["total"]]
        self.assertEqual(self.admin.call("POST", f"/api/debts/{overdue['id']}/pay", {"amount": 10, "method": "bitcoin"})[0], 400)
        self.assertEqual(self.admin.call("POST", f"/api/debts/{overdue['id']}/pay", {"amount": 10**9, "method": "cash"})[0], 400)
        for method, account, amount in (("cash", "cash", 10000), ("click", "card", 20000),
                                        ("terminal", "bank", 5000), ("transfer", "bank", 5000)):
            _, before = self.admin.call("GET", "/api/finance/balance")
            _, res = self.admin.call("POST", f"/api/debts/{overdue['id']}/pay", {"amount": amount, "method": method})
            self.assertEqual(res["account"], account)
            _, after = self.admin.call("GET", "/api/finance/balance")
            self.assertEqual(acc(after, account) - acc(before, account), amount)

        # Qolganini to'lasa - qarz yopiladi va ro'yxatdan chiqadi
        left = paid["total"] - 40000
        _, res = self.admin.call("POST", f"/api/debts/{overdue['id']}/pay", {"method": "cash"})
        self.assertEqual(res["remaining"], 0)
        self.assertEqual(self.admin.call("POST", f"/api/debts/{overdue['id']}/pay", {"method": "cash"})[0], 409)
        _, debts = self.admin.call("GET", "/api/debts")
        self.assertNotIn(overdue["id"], [d["id"] for d in debts["debts"]])

        # Mijoz kartasi: qarz, to'langan, qoldiq; to'lovni bekor qilish qarzni qayta ochadi
        _, card = self.admin.call("GET", f"/api/customers/{ali['id']}")
        self.assertEqual(card["remaining"], 50000)
        last = card["payments"][0]
        self.assertEqual(last["amount"], left)
        self.assertEqual(self.admin.call("POST", f"/api/debt-payments/{last['id']}/cancel", {"reason": "xato"})[0], 200)
        self.assertEqual(self.admin.call("POST", f"/api/debt-payments/{last['id']}/cancel")[0], 409)
        _, card = self.admin.call("GET", f"/api/customers/{ali['id']}")
        self.assertEqual(card["remaining"], 50000 + left)

        # Qarzga sotilgan savdoni bekor qilish - to'lovlar bor ekan, avval ular bekor qilinadi
        self.assertEqual(self.admin.call("POST", f"/api/finance/sales/{order['id']}/cancel")[0], 409)
        # Ofitsiantda CRM ruxsati yo'q
        self.assertEqual(self.waiter.call("GET", "/api/debts")[0], 403)

    def upload(self, client, kind, content, name="fayl.xlsx"):
        return client.call("POST", f"/api/import/{kind}", {"file_name": name, "data": base64.b64encode(content).decode()})

    def test_import_template_and_products(self):
        import xlsx
        from urllib.request import Request
        # Shablon - haqiqiy xlsx, o'zimiz o'qiy olamiz
        req = Request(self.base + "/api/import/products/template")
        with self.admin.opener.open(req) as res:
            self.assertIn("spreadsheetml", res.headers["Content-Type"])
            template = res.read()
        headers, rows = xlsx.read_table(template)
        self.assertEqual(headers[:3], ["nomi", "shtrix-kod", "kategoriya"])
        self.assertEqual(len(rows), 2)  # izoh qatorlari (#) o'tkazib yuboriladi

        content = xlsx.write_xlsx(
            ["Nomi*", "Shtrix-kod", "Kategoriya", "Birlik", "Sotish narxi*", "Tannarxi", "Qoldiq"],
            [["Import Pechenye", "4780000099991", "Import Kategoriya", "dona", "8 000", "3000", 12],
             ["Import Kartoshka", "", "Import Kategoriya", "kg", 6000, 4000, "15.5"],
             ["", "", "X", "", 1000, "", ""],                    # nomi yo'q
             ["Import Xato", "", "", "", "abc", "", ""],          # narx son emas
             ["Import Birlik", "", "", "tonna", 5000, "", ""],    # birlik noto'g'ri
             ["Import Kasr", "", "", "dona", 5000, "", "1.5"]])   # dona kasr bo'lmaydi
        status, res = self.upload(self.admin, "products", content)
        self.assertEqual(status, 200)
        self.assertEqual((res["created"], res["updated"]), (2, 0))
        self.assertEqual([e["row"] for e in res["errors"]], [4, 5, 6, 7])
        _, products = self.admin.call("GET", "/api/products")
        pech = next(p for p in products if p["name"] == "Import Pechenye")
        self.assertEqual((pech["price"], pech["cost"], pech["category_name"], pech["stock"], pech["barcode"]),
                         (8000, 3000, "Import Kategoriya", 12, "4780000099991"))
        kart = next(p for p in products if p["name"] == "Import Kartoshka")
        self.assertEqual((kart["unit"], kart["stock"]), ("kg", 15.5))

        # Qayta yuklansa - shtrix-kod bo'yicha topiladi va yangilanadi, qoldiq tenglanadi, dublikat bo'lmaydi
        again = xlsx.write_xlsx(["Nomi", "Shtrix-kod", "Sotish narxi", "Qoldiq"], [["Import Pechenye yangi", "4780000099991", 9000, 20]])
        _, res = self.upload(self.admin, "products", again)
        self.assertEqual((res["created"], res["updated"]), (0, 1))
        _, products = self.admin.call("GET", "/api/products")
        pech = next(p for p in products if p["id"] == pech["id"])
        self.assertEqual((pech["name"], pech["price"], pech["stock"]), ("Import Pechenye yangi", 9000, 20))

        # CSV ham qabul qilinadi; ustun yetishmasa - tushunarli xato
        _, res = self.upload(self.admin, "products", "Nomi;Sotish narxi\nImport CSV;7000\n".encode(), "a.csv")
        self.assertEqual(res["created"], 1)
        status, err = self.upload(self.admin, "products", xlsx.write_xlsx(["Nomi"], [["X"]]))
        self.assertEqual(status, 400)
        self.assertIn("Sotish narxi", err["error"])
        self.assertEqual(self.upload(self.admin, "products", b"not a real file at all")[0], 400)
        self.assertEqual(self.upload(self.waiter, "products", again)[0], 403)

    def test_import_customers(self):
        import xlsx
        content = xlsx.write_xlsx(["Ismi*", "Telefon*", "Jinsi*"], [
            ["Import Ali", "90 700 00 01", "Erkak"],
            ["Import Laylo", "+998 90 700 00 02", "ayol"],
            ["Import Xato", "12", "Erkak"],
            ["Import Jins", "90 700 00 03", "?"],
        ])
        _, res = self.upload(self.admin, "customers", content)
        self.assertEqual((res["created"], len(res["errors"])), (2, 2))
        _, found = self.admin.call("GET", "/api/customers?q=Import")
        self.assertEqual({c["name"]: c["gender"] for c in found}, {"Import Ali": "m", "Import Laylo": "f"})
        _, res = self.upload(self.admin, "customers", xlsx.write_xlsx(["Ismi", "Telefon", "Jinsi"], [["Ali Yangi", "907000001", "E"]]))
        self.assertEqual(res["updated"], 1)

    def test_set_balances(self):
        _, b = self.admin.call("GET", "/api/balances")
        cash = next(a for a in b["accounts"]["accounts"] if a["account"] == "cash")["balance"]
        # Kassa: yangi balans o'rnatiladi, farq tuzatish yozuvi bo'ladi
        _, r = self.admin.call("POST", "/api/balances/account", {"account": "cash", "balance": cash + 500000, "comment": "Boshlang'ich qoldiq"})
        self.assertEqual((r["old"], r["new"]), (cash, cash + 500000))
        self.admin.call("POST", "/api/balances/account", {"account": "cash", "balance": cash + 400000})
        _, b = self.admin.call("GET", "/api/balances")
        self.assertEqual(next(a for a in b["accounts"]["accounts"] if a["account"] == "cash")["balance"], cash + 400000)
        self.assertEqual(self.admin.call("POST", "/api/balances/account", {"account": "cash", "balance": cash + 400000})[0], 400)
        # Tuzatish turlari kirim/chiqim oynasida tanlanmaydi (is_adjust)
        _, types = self.admin.call("GET", "/api/finance/types")
        self.assertEqual(sum(t["is_adjust"] for t in types), 2)

        # Mijoz: qarz 0 -> 80000 -> 30000
        _, c = self.admin.call("POST", "/api/customers", {"name": "Balans Mijoz", "phone": "907771122", "gender": "m"})
        self.admin.call("POST", "/api/balances/customer", {"customer_id": c["id"], "balance": 80000})
        _, r = self.admin.call("POST", "/api/balances/customer", {"customer_id": c["id"], "balance": 30000})
        self.assertEqual((r["old"], r["new"]), (80000, 30000))
        _, card = self.admin.call("GET", f"/api/customers/{c['id']}")
        self.assertEqual(card["remaining"], 30000)
        self.assertEqual(self.admin.call("POST", "/api/balances/customer", {"customer_id": c["id"], "balance": -5})[0], 400)
        _, b2 = self.admin.call("GET", "/api/balances")
        self.assertEqual(b2["accounts"]["total"], b["accounts"]["total"])  # mijoz tuzatishi kassaga ta'sir qilmaydi

        # Ta'minotchi: yaratish (dublikatsiz), balans, chiqim bilan kamayadi
        _, sup = self.admin.call("POST", "/api/suppliers", {"name": "Go'sht do'koni", "phone": "901112233"})
        self.assertEqual(self.admin.call("POST", "/api/suppliers", {"name": "go'sht  DO'KONI"})[0], 409)
        self.admin.call("POST", "/api/balances/supplier", {"supplier_id": sup["id"], "balance": 1000000})
        _, types = self.admin.call("GET", "/api/finance/types")
        pay_type = next(t for t in types if t["name"] == "Ta'minotchiga pul berish")
        self.admin.call("POST", "/api/finance/entries", {"type_id": pay_type["id"], "account": "cash", "amount": 250000, "supplier_id": sup["id"]})
        _, sups = self.admin.call("GET", "/api/suppliers")
        self.assertEqual(next(x for x in sups if x["id"] == sup["id"])["balance"], 750000)
        _, b3 = self.admin.call("GET", "/api/balances")
        self.assertEqual([h["target"] for h in b3["history"][:4]], ["supplier", "customer", "customer", "account"])
        self.assertEqual(self.cashier.call("GET", "/api/balances")[0], 403)

    def test_admin_cannot_demote_self(self):
        _, me = self.admin.call("GET", "/api/me")
        status, _ = self.admin.call("PUT", f"/api/users/{me['id']}", {"first_name": "A", "role": "cashier"})
        self.assertEqual(status, 400)

    def test_journal_records_actions(self):
        prod = self.product("Jurnal tovar", 5000)
        status, order = self.sell(self.cashier, [(prod, 2)])
        self.assertEqual(status, 200)

        status, j = self.admin.call("GET", "/api/journal?category=sales")
        self.assertEqual(status, 200)
        sale = next(i for i in j["items"] if f"#{order['id']} " in i["summary"])
        self.assertEqual(sale["title"], "Sotuv")
        self.assertEqual(sale["user_name"], "Kassir")
        _, detail = self.admin.call("GET", f"/api/journal/{sale['id']}")
        fields = dict(map(tuple, detail["details"]["fields"]))
        self.assertEqual(fields["To'lov usuli"], "Naqd")
        self.assertEqual(detail["details"]["items"][0]["qty"], 2)

        _, j = self.admin.call("GET", "/api/journal?category=sales&q=" + quote("Sotuv"))
        self.assertTrue(j["items"])
        # login ham yoziladi, parol esa hech qayerda saqlanmaydi
        _, j = self.admin.call("GET", "/api/journal?category=auth")
        self.assertTrue(j["items"])
        self.admin.call("POST", "/api/users", {"first_name": "Jurnal Test", "phone": "900001122", "role": "staff",
                                               "permissions": ["cashier"], "pin": "7373", "password": "sirli-parol"})
        _, j = self.admin.call("GET", "/api/journal?category=users")
        _, detail = self.admin.call("GET", f"/api/journal/{j['items'][0]['id']}")
        self.assertNotIn("sirli-parol", json.dumps(detail))
        self.assertEqual(detail["details"]["request"]["password"], "•••")
        self.assertEqual(detail["details"]["request"]["pin"], "•••")
        # ruxsatsiz - yo'q
        status, _ = self.waiter.call("GET", "/api/journal")
        self.assertEqual(status, 403)

    def test_journal_product_changes(self):
        _, p = self.admin.call("POST", "/api/products", {"name": "Jurnal somsa", "price": 8000})
        self.admin.call("PUT", f"/api/products/{p['id']}", {"name": "Jurnal somsa", "price": 9000})
        self.admin.call("DELETE", f"/api/products/{p['id']}")
        _, j = self.admin.call("GET", "/api/journal?q=Jurnal%20somsa")
        titles = [i["title"] for i in j["items"]]
        self.assertEqual(titles[:3], ["Mahsulot o'chirildi", "Mahsulot o'zgartirildi", "Mahsulot qo'shildi"])
        self.assertIn("8 000 so'm → 9 000 so'm", j["items"][1]["summary"])
        # xato bilan tugagan amal jurnalga yozilmaydi
        status, _ = self.admin.call("POST", "/api/products", {"name": "", "price": 1})
        self.assertEqual(status, 400)
        _, after = self.admin.call("GET", "/api/journal?category=products")
        self.assertEqual(after["items"][0]["title"], "Mahsulot o'chirildi")

    def test_telegram_integration(self):
        import server
        import telegram
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import parse_qs

        sent = []

        class FakeTelegram(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = parse_qs(self.rfile.read(int(self.headers["Content-Length"] or 0)).decode())
                method = self.path.rsplit("/", 1)[-1]
                if "/botBAD" in self.path or "000:" in self.path:
                    result = {"ok": False, "description": "Unauthorized"}
                elif method == "getMe":
                    result = {"ok": True, "result": {"id": 1, "username": "cafe_test_bot", "first_name": "Cafe"}}
                elif method == "getUpdates":
                    result = {"ok": True, "result": [{"message": {"chat": {"id": 555111, "type": "private", "first_name": "Ali"}}}]}
                else:
                    sent.append(body)
                    result = {"ok": True, "result": {}}
                raw = json.dumps(result).encode()
                self.send_response(200 if result["ok"] else 401)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeTelegram)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        old_api, telegram.API = telegram.API, f"http://127.0.0.1:{fake.server_address[1]}"
        token = "123456789:AAH" + "x" * 32
        try:
            status, _ = self.cashier.call("GET", "/api/integrations/telegram")
            self.assertEqual(status, 403)
            status, bot = self.admin.call("POST", "/api/integrations/telegram/check", {"token": token})
            self.assertEqual((status, bot["username"]), (200, "cafe_test_bot"))
            status, err = self.admin.call("POST", "/api/integrations/telegram/check", {"token": "000:" + "y" * 30})
            self.assertEqual(status, 502)
            self.assertIn("noto'g'ri", err["error"])
            _, chats = self.admin.call("POST", "/api/integrations/telegram/chats", {"token": token})
            self.assertEqual(chats[0]["id"], 555111)
            # chatsiz yoqib bo'lmaydi
            status, _ = self.admin.call("PUT", "/api/integrations/telegram", {"enabled": True, "token": token, "chats": []})
            self.assertEqual(status, 400)
            status, cfg = self.admin.call("PUT", "/api/integrations/telegram", {
                "enabled": True, "token": token, "chats": [{"id": 555111, "title": "Ali"}],
                "categories": ["sales", "finance"]})
            self.assertEqual(status, 200)
            self.assertNotIn(token, json.dumps(cfg))  # token to'liq qaytarilmaydi
            self.assertTrue(cfg["token_set"])
            _, settings = self.admin.call("GET", "/api/settings")
            self.assertNotIn(token, json.dumps(settings))
            # token kiritilmasa - eskisi qoladi
            status, cfg = self.admin.call("PUT", "/api/integrations/telegram", {
                "enabled": True, "chats": cfg["chats"], "categories": ["sales", "finance"]})
            self.assertEqual((status, cfg["token_set"]), (200, True))

            status, res = self.admin.call("POST", "/api/integrations/telegram/test", {})
            self.assertEqual(status, 200)
            self.assertTrue(res[0]["ok"])
            sent.clear()
            _, types = self.admin.call("GET", "/api/finance/types")
            ftype = next(t for t in types if t["direction"] == "in")
            self.admin.call("POST", "/api/finance/entries", {"type_id": ftype["id"], "account": "cash",
                                                             "amount": 77000, "comment": "Telegram sinov"})
            self.admin.call("POST", "/api/categories", {"name": "Telegramga bormaydi"})  # menu tanlanmagan
            for _ in range(50):
                if sent:
                    break
                time.sleep(0.05)
            telegram.notifier.queue.join()
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0]["chat_id"], ["555111"])
            self.assertIn("77 000 so'm", sent[0]["text"][0])
            self.assertIn("Telegram sinov", sent[0]["text"][0])

            # soddalashtirilgan ulash: uzish -> token bilan ulash -> /start yozganlar o'zi qo'shiladi
            _, cfg = self.admin.call("DELETE", "/api/integrations/telegram")
            self.assertFalse(cfg["token_set"])
            status, _ = self.admin.call("POST", "/api/integrations/telegram/connect", {"token": "yomon"})
            self.assertEqual(status, 400)
            status, cfg = self.admin.call("POST", "/api/integrations/telegram/connect", {"token": token})
            self.assertEqual(status, 200)
            self.assertEqual((cfg["token_set"], cfg["chats"], cfg["enabled"]), (True, [], False))
            self.assertEqual(cfg["bot"]["username"], "cafe_test_bot")
            sent.clear()
            status, cfg = self.admin.call("POST", "/api/integrations/telegram/link", {})
            self.assertEqual((status, cfg["added"], cfg["enabled"]), (200, ["Ali"], True))
            self.assertEqual(len(sent), 1)  # salom xabari
            _, cfg = self.admin.call("POST", "/api/integrations/telegram/link", {})
            self.assertEqual(cfg["added"], [])  # ikkinchi marta qo'shilmaydi
            self.assertEqual(len(cfg["chats"]), 1)
        finally:
            self.admin.call("PUT", "/api/integrations/telegram", {"enabled": False})
            telegram.API = old_api
            fake.shutdown()
            fake.server_close()

    def test_customer_bot(self):
        import server
        import telegram
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import parse_qs

        sent = []

        class FakeTelegram(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = parse_qs(self.rfile.read(int(self.headers["Content-Length"] or 0)).decode())
                method = self.path.rsplit("/", 1)[-1]
                if method == "getMe":
                    result = {"ok": True, "result": {"id": 77, "username": "kafe_mijoz_bot", "first_name": "Kafe"}}
                else:
                    sent.append({k: v[0] for k, v in body.items()})
                    result = {"ok": True, "result": {}}
                raw = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        def wait_sent(n):
            for _ in range(60):
                if len(sent) >= n:
                    break
                time.sleep(0.05)
            telegram.customer_notifier.queue.join()

        fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeTelegram)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        old_api, telegram.API = telegram.API, f"http://127.0.0.1:{fake.server_address[1]}"
        token = "987654321:BBH" + "z" * 32
        try:
            status, _ = self.admin.call("POST", "/api/customers/message", {"all": True, "text": "salom"})
            self.assertEqual(status, 400)  # bot ulanmagan
            status, cfg = self.admin.call("POST", "/api/integrations/customer-bot/connect", {"token": token})
            self.assertEqual(status, 200)
            self.assertEqual((cfg["enabled"], cfg["bot"]["username"]), (True, "kafe_mijoz_bot"))

            _, c = self.admin.call("POST", "/api/customers", {"name": "Bot Mijoz", "phone": "+998 97 111 22 33", "gender": "f"})

            def reply(update):
                with server.db_lock:
                    return server.customer_bot_reply(self.server.conn, update)
            chat = {"id": 4242, "type": "private"}
            r = reply({"message": {"chat": chat, "from": {"id": 4242}, "text": "/start"}})
            self.assertTrue(r[0][2]["keyboard"][0][0]["request_contact"])
            r = reply({"message": {"chat": chat, "from": {"id": 4242},
                                   "contact": {"phone_number": "998971112233", "user_id": 999}}})
            self.assertIn("o'zingizning", r[0][1])  # boshqa odamning raqami
            r = reply({"message": {"chat": chat, "from": {"id": 4242},
                                   "contact": {"phone_number": "998900000000", "user_id": 4242}}})
            self.assertIn("topilmadi", r[0][1])
            r = reply({"message": {"chat": chat, "from": {"id": 4242},
                                   "contact": {"phone_number": "998971112233", "user_id": 4242}}})
            self.assertIn("Bot Mijoz", r[0][1])
            self.assertIn("Qarzingiz yo'q", r[1][1])
            _, linked = self.admin.call("GET", "/api/customers?telegram=1")
            self.assertEqual([x["id"] for x in linked], [c["id"]])

            # savdoda mijoz tanlansa - chek botga boradi
            prod = self.product("Bot tovar", 7000)
            products = [prod]
            status, paid = self.sell(self.cashier, [(prod, 2)], customer_id=c["id"])
            order = paid
            self.assertEqual(status, 200)
            self.assertTrue(paid["customer_notified"])
            wait_sent(1)
            self.assertEqual(sent[-1]["chat_id"], "4242")
            self.assertIn(f"Chek #{order['id']}", sent[-1]["text"])
            self.assertIn(products[0]["name"], sent[-1]["text"])

            # qarz va balans
            self.admin.call("POST", f"/api/customers/{c['id']}/debts", {"amount": 45000, "due_date": "2030-01-01"})
            r = reply({"message": {"chat": chat, "from": {"id": 4242}, "text": server.BTN_BALANCE}})
            self.assertIn("45 000 so'm", r[0][1])
            r = reply({"message": {"chat": chat, "from": {"id": 4242}, "text": server.BTN_ORDERS}})
            self.assertIn(f"#{order['id']}", r[0][1])
            _, detail = self.admin.call("GET", f"/api/customers/{c['id']}")
            debt_id = next(d["id"] for d in detail["debts"] if d["remaining"] > 0)
            self.admin.call("POST", f"/api/debts/{debt_id}/pay", {"method": "cash", "amount": 5000})
            wait_sent(2)
            self.assertIn("40 000 so'm", sent[-1]["text"])

            # ommaviy xabar
            sent.clear()
            status, res = self.admin.call("POST", "/api/customers/message", {"all": True, "text": "Ertaga 20% chegirma!"})
            self.assertEqual((status, res["sent"]), (200, 1))
            wait_sent(1)
            self.assertIn("Ertaga 20% chegirma!", sent[-1]["text"])
            status, _ = self.waiter.call("POST", "/api/customers/message", {"all": True, "text": "x x"})
            self.assertEqual(status, 403)  # ofitsiantda CRM ruxsati yo'q
        finally:
            self.admin.call("DELETE", "/api/integrations/customer-bot")
            telegram.API = old_api
            fake.shutdown()
            fake.server_close()

    def test_sales_receipts_return(self):
        p1 = self.product("Qaytarish A", 10000, stock=10, cost=6000)
        p2 = self.product("Qaytarish B", 5000, stock=10)
        _, paid = self.sell(self.cashier, [(p1, 3), (p2, 1)], discount=3500)
        order = paid
        _, before = self.admin.call("GET", "/api/reports")
        _, bal0 = self.admin.call("GET", "/api/finance/balance")

        status, sales = self.admin.call("GET", "/api/sales")
        self.assertEqual(status, 200)
        self.assertIn(order["id"], [x["id"] for x in sales["sales"]])
        status, sale = self.admin.call("GET", f"/api/sales/{order['id']}")
        self.assertEqual((status, sale["can_manage"]), (200, True))
        item1 = next(i for i in sale["items"] if i["name"] == p1["name"])

        # ko'p qaytarib bo'lmaydi
        status, _ = self.cashier.call("POST", f"/api/sales/{order['id']}/return", {"items": [{"item_id": item1["id"], "qty": 4}]})
        self.assertEqual(status, 400)
        status, _ = self.waiter.call("POST", f"/api/sales/{order['id']}/return", {"items": [{"item_id": item1["id"], "qty": 1}]})
        self.assertEqual(status, 403)
        status, ret = self.cashier.call("POST", f"/api/sales/{order['id']}/return",
                                        {"items": [{"item_id": item1["id"], "qty": 1}], "reason": "yaroqsiz"})
        self.assertEqual(status, 200)
        self.assertEqual(ret["amount"], round(10000 * paid["total"] / paid["subtotal"]))
        self.assertEqual(self.stock_of(p1), 8)  # 10 - 3 + 1

        _, after = self.admin.call("GET", "/api/reports")
        self.assertEqual(after["summary"]["revenue"], before["summary"]["revenue"] - ret["amount"])
        self.assertEqual(after["summary"]["cost"], before["summary"]["cost"] - 6000)
        _, bal1 = self.admin.call("GET", "/api/finance/balance")
        cash = lambda b: next(a for a in b["accounts"] if a["account"] == "cash")["balance"]
        self.assertEqual(cash(bal1), cash(bal0) - ret["amount"])
        _, sale = self.admin.call("GET", f"/api/sales/{order['id']}")
        self.assertEqual(sale["returned"], ret["amount"])
        self.assertEqual(sale["returns"][0]["reason"], "yaroqsiz")
        _, only = self.admin.call("GET", "/api/sales?status=returned")
        self.assertIn(order["id"], [x["id"] for x in only["sales"]])

        # qolganini bekor qilish: savdo butunlay hisobdan chiqadi, qolgan tovar ham qaytadi
        status, _ = self.cashier.call("POST", f"/api/finance/sales/{order['id']}/cancel", {"reason": "xato"})
        self.assertEqual(status, 200)
        self.assertEqual((self.stock_of(p1), self.stock_of(p2)), (10, 10))
        _, bal2 = self.admin.call("GET", "/api/finance/balance")
        self.assertEqual(cash(bal2), cash(bal0) - paid["total"])
        status, _ = self.cashier.call("POST", f"/api/sales/{order['id']}/return", {"items": [{"item_id": item1["id"], "qty": 1}]})
        self.assertEqual(status, 409)

    def test_pin_login(self):
        import server
        # administrator standart PIN bilan kiradi
        status, me = Client(self.base).call("POST", "/api/login", {"pin": "1234"})
        self.assertEqual((status, me["username"]), (200, "admin"))
        # xodim faqat PIN bilan yaratiladi
        status, u = self.admin.call("POST", "/api/users", {"first_name": "Pinli", "phone": "900004321",
                                                          "role": "staff", "permissions": ["cashier"], "pin": "4321"})
        self.assertEqual(status, 200)
        status, me = Client(self.base).call("POST", "/api/login", {"pin": "4321"})
        self.assertEqual((status, me["full_name"]), (200, "Pinli"))
        # bir xil PIN ikki xodimda bo'lmaydi, format tekshiriladi
        status, _ = self.admin.call("PUT", f"/api/users/{u['id']}", {"first_name": "Pinli", "role": "staff", "permissions": ["cashier"], "pin": "1234"})
        self.assertEqual(status, 409)
        status, _ = self.admin.call("PUT", f"/api/users/{u['id']}", {"first_name": "Pinli", "role": "staff", "permissions": ["cashier"], "pin": "12a4"})
        self.assertEqual(status, 400)
        self.admin.call("PUT", f"/api/users/{u['id']}", {"first_name": "Pinli", "role": "staff", "permissions": ["cashier"], "pin": "5555"})
        self.assertEqual(Client(self.base).call("POST", "/api/login", {"pin": "4321"})[0], 401)
        _, users = self.admin.call("GET", "/api/users")
        self.assertTrue(next(x for x in users if x["id"] == u["id"])["has_pin"])
        self.assertNotIn("pin_lookup", json.dumps(users))
        _, settings = self.admin.call("GET", "/api/settings")
        self.assertNotIn("_pin_secret", settings)
        # 5 ta xatodan keyin kutish kerak
        server.LOGIN_GUARD.ok("127.0.0.1")
        for _ in range(4):
            Client(self.base).call("POST", "/api/login", {"pin": "0000"})
        status, err = Client(self.base).call("POST", "/api/login", {"pin": "0000"})
        self.assertEqual(status, 401)
        status, err = Client(self.base).call("POST", "/api/login", {"pin": "5555"})
        self.assertEqual(status, 429)
        server.LOGIN_GUARD.ok("127.0.0.1")
        self.assertEqual(Client(self.base).call("POST", "/api/login", {"pin": "5555"})[0], 200)
        server.LOGIN_GUARD.ok("127.0.0.1")

    def test_no_duplicates(self):
        a = self.admin
        _, cat = a.call("POST", "/api/categories", {"name": "Dublikat kategoriya"})
        self.assertEqual(a.call("POST", "/api/categories", {"name": "  dublikat   KATEGORIYA "})[0], 409)
        _, cat2 = a.call("POST", "/api/categories", {"name": "Boshqa kategoriya"})
        self.assertEqual(a.call("PUT", f"/api/categories/{cat2['id']}", {"name": "Dublikat kategoriya"})[0], 409)
        self.assertEqual(a.call("PUT", f"/api/categories/{cat['id']}", {"name": "Dublikat kategoriya"})[0], 200)

        _, p = a.call("POST", "/api/products", {"name": "Dublikat tovar", "price": 1000})
        status, err = a.call("POST", "/api/products", {"name": "dublikat tovar", "price": 2000})
        self.assertEqual(status, 409)
        self.assertIn("allaqachon bor", err["error"])
        _, p2 = a.call("POST", "/api/products", {"name": "Boshqa tovar", "price": 1000})
        self.assertEqual(a.call("PUT", f"/api/products/{p2['id']}", {"name": "Dublikat tovar", "price": 1})[0], 409)
        # o'chirilgan mahsulot nomi qayta ishlatilishi mumkin
        a.call("DELETE", f"/api/products/{p['id']}")
        self.assertEqual(a.call("POST", "/api/products", {"name": "Dublikat tovar", "price": 1000})[0], 200)


        self.assertEqual(a.call("POST", "/api/suppliers", {"name": "Dublikat ta'minotchi", "phone": "90 700 11 22"})[0], 200)
        self.assertEqual(a.call("POST", "/api/suppliers", {"name": "dublikat ta'minotchi"})[0], 409)
        self.assertEqual(a.call("POST", "/api/suppliers", {"name": "Boshqa nom", "phone": "+998 90 700 11 22"})[0], 409)

        self.assertEqual(a.call("POST", "/api/customers", {"name": "Dub Mijoz", "phone": "+998 93 700 11 22", "gender": "m"})[0], 200)
        self.assertEqual(a.call("POST", "/api/customers", {"name": "Boshqa", "phone": "937001122", "gender": "m"})[0], 409)

        self.assertEqual(a.call("POST", "/api/users", {"first_name": "Dub", "phone": "+998 94 700 11 22",
                                                       "role": "staff", "permissions": ["cashier"], "pin": "6061"})[0], 200)
        self.assertEqual(a.call("POST", "/api/users", {"first_name": "Dub2", "phone": "94 700 11 22",
                                                       "role": "staff", "permissions": ["cashier"], "pin": "6062"})[0], 409)

    def test_receipt_settings(self):
        _, s = self.admin.call("GET", "/api/settings")
        self.assertTrue(s["receipt"]["show_shop_name"])
        self.assertEqual(s["receipt"]["footer_text"], "Xaridingiz uchun rahmat!")
        status, s = self.admin.call("PUT", "/api/settings", {"receipt": {
            "show_cashier": False, "show_logo": True, "header_text": " Tel: 90 123 ", "paper_width": "58", "junk": 1}})
        self.assertEqual(status, 200)
        r = s["receipt"]
        self.assertEqual((r["show_cashier"], r["show_logo"], r["header_text"], r["paper_width"]), (False, True, "Tel: 90 123", 58))
        self.assertNotIn("junk", r)
        self.assertEqual(self.admin.call("PUT", "/api/settings", {"receipt": {"footer_text": "x" * 400}})[0], 400)
        self.assertEqual(self.waiter.call("PUT", "/api/settings", {"receipt": {}})[0], 403)
        _, j = self.admin.call("GET", "/api/journal?category=settings")
        self.assertIn("Chek", json.dumps(j["items"][0], ensure_ascii=False))
        self.admin.call("PUT", "/api/settings", {"receipt": {}})  # standartga qaytarish

    def test_cancel_finance_entry_without_order(self):
        _, types = self.admin.call("GET", "/api/finance/types")
        ftype = next(t for t in types if t["direction"] == "in")
        _, e = self.admin.call("POST", "/api/finance/entries", {"type_id": ftype["id"], "account": "cash", "amount": 1000})
        for _ in range(3):  # id ni buyurtmalar sonidan kattaroq qilamiz
            _, e = self.admin.call("POST", "/api/finance/entries", {"type_id": ftype["id"], "account": "cash", "amount": 1000})
        status, _ = self.admin.call("POST", f"/api/finance/entries/{e['id'] + 100000 - 100000}/cancel", {"reason": "x"})
        self.assertEqual(status, 200)

    def test_sale_updates_stock(self):
        p = self.product("Sotuv tovar", 12000, stock=5, cost=8000)
        status, sale = self.sell(self.cashier, [(p, 2), (p, 1)], discount=1000)
        self.assertEqual(status, 200)
        self.assertEqual((sale["subtotal"], sale["discount"], sale["total"]), (36000, 1000, 35000))
        self.assertEqual(self.stock_of(p), 2)
        # omborda yetarli emas - sotilmaydi
        status, err = self.sell(self.cashier, [(p, 3)])
        self.assertEqual(status, 409)
        self.assertIn("qoldiq 2", err["error"])
        self.assertEqual(self.stock_of(p), 2)
        # bo'sh savat, noto'g'ri miqdor, noto'g'ri to'lov turi
        self.assertEqual(self.cashier.call("POST", "/api/sales", {"items": [], "method": "cash"})[0], 400)
        self.assertEqual(self.sell(self.cashier, [(p, 0)])[0], 400)
        self.assertEqual(self.sell(self.cashier, [(p, 1.5)])[0], 400)  # dona kasr bo'lmaydi
        self.assertEqual(self.sell(self.cashier, [(p, 1)], "bitcoin")[0], 400)
        self.assertEqual(self.sell(self.cashier, [(p, 1)], discount=10**9)[0], 400)
        # sozlamada ruxsat berilsa - minusga sotish mumkin
        self.admin.call("PUT", "/api/settings", {"allow_negative": True})
        self.assertEqual(self.sell(self.cashier, [(p, 3)])[0], 200)
        self.assertEqual(self.stock_of(p), -1)
        self.admin.call("PUT", "/api/settings", {"allow_negative": False})
        _, moves = self.admin.call("GET", f"/api/stock/moves?product_id={p['id']}")
        self.assertEqual([m["kind"] for m in moves["items"]], ["sale", "sale", "initial"])
        self.assertEqual(moves["items"][0]["balance"], -1)

    def test_weight_goods(self):
        p = self.product("Olma", 18000, stock=10, unit="kg", cost=12000)
        status, sale = self.sell(self.cashier, [(p, 1.255)])
        self.assertEqual(status, 200)
        self.assertEqual(sale["total"], 22590)  # 18000 * 1.255
        self.assertAlmostEqual(self.stock_of(p), 8.745)
        _, rep = self.admin.call("GET", "/api/reports")
        olma = next(t for t in rep["top_products"] if t["name"] == "Olma")
        self.assertEqual((olma["qty"], olma["unit"], olma["profit"]), (1.255, "kg", 7530))

    def test_purchase_flow(self):
        _, sup = self.admin.call("POST", "/api/suppliers", {"name": "Kirim ta'minotchi"})
        p = self.product("Kirim tovar", 15000, stock=10, cost=10000)
        _, bal0 = self.admin.call("GET", "/api/finance/balance")
        cash = lambda b: next(a for a in b["accounts"] if a["account"] == "cash")["balance"]
        # 10 ta 10 000 dan bor + 30 ta 12 000 dan kirdi -> o'rtacha tannarx 11 500; sotish narxi yangilanadi
        status, pu = self.admin.call("POST", "/api/purchases", {
            "supplier_id": sup["id"], "items": [{"product_id": p["id"], "qty": 30, "cost": 12000, "price": 16000}],
            "paid": 100000, "account": "cash", "comment": "Faktura 15"})
        self.assertEqual(status, 200)
        self.assertEqual((pu["total"], pu["paid"], pu["supplier_name"]), (360000, 100000, "Kirim ta'minotchi"))
        prod = next(x for x in self.admin.call("GET", "/api/products")[1] if x["id"] == p["id"])
        self.assertEqual((prod["stock"], prod["cost"], prod["price"]), (40, 11500, 16000))
        # ta'minotchiga qarz 260 000, kassadan 100 000 chiqdi
        _, sups = self.admin.call("GET", "/api/suppliers")
        self.assertEqual(next(x for x in sups if x["id"] == sup["id"])["balance"], 260000)
        _, bal1 = self.admin.call("GET", "/api/finance/balance")
        self.assertEqual(cash(bal0) - cash(bal1), 100000)
        self.assertEqual(self.admin.call("POST", "/api/purchases", {"supplier_id": sup["id"], "paid": 10**9,
                                                                     "items": [{"product_id": p["id"], "qty": 1, "cost": 1}]})[0], 400)
        self.assertEqual(self.admin.call("POST", "/api/purchases", {"items": []})[0], 400)
        # ta'minotchisiz (bozordan) kirim - darhol to'lanadi
        _, pu2 = self.admin.call("POST", "/api/purchases", {"items": [{"product_id": p["id"], "qty": 2, "cost": 11500}]})
        self.assertEqual(pu2["paid"], 23000)
        _, lst = self.admin.call("GET", "/api/purchases")
        self.assertIn(pu["id"], [x["id"] for x in lst["items"]])
        # bekor qilish: qoldiq kamayadi, to'lov qaytadi, ta'minotchi qarzi yo'qoladi
        self.assertEqual(self.admin.call("POST", f"/api/purchases/{pu['id']}/cancel", {"reason": "xato"})[0], 200)
        self.assertEqual(self.admin.call("POST", f"/api/purchases/{pu['id']}/cancel")[0], 409)
        self.assertEqual(self.stock_of(p), 12)
        _, sups = self.admin.call("GET", "/api/suppliers")
        self.assertEqual(next(x for x in sups if x["id"] == sup["id"])["balance"], 0)
        _, bal2 = self.admin.call("GET", "/api/finance/balance")
        self.assertEqual(cash(bal0) - cash(bal2), 23000)
        _, j = self.admin.call("GET", "/api/journal?category=warehouse")
        self.assertEqual([i["title"] for i in j["items"][:3]], ["Kirim bekor qilindi", "Tovar kirimi", "Tovar kirimi"])
        self.assertEqual(self.cashier.call("GET", "/api/purchases")[0], 403)

    def test_count_and_writeoff(self):
        a = self.product("Inv A", 1000, stock=10, cost=500)
        b = self.product("Inv B", 1000, stock=4, unit="kg", cost=2000, min_stock=5)
        status, doc = self.admin.call("POST", "/api/stock/count", {"comment": "Oy oxiri", "items": [
            {"product_id": a["id"], "actual": 8}, {"product_id": b["id"], "actual": 4.5}]})
        self.assertEqual(status, 200)
        self.assertEqual([l["qty"] for l in doc["lines"]], [-2, 0.5])
        self.assertEqual(doc["total_cost"], -1000 + 1000)
        self.assertEqual((self.stock_of(a), self.stock_of(b)), (8, 4.5))
        self.assertEqual(self.admin.call("POST", "/api/stock/count", {"items": [{"product_id": a["id"], "actual": 8}]})[0], 400)
        self.assertEqual(self.admin.call("POST", "/api/stock/writeoff", {"items": [{"product_id": a["id"], "qty": 1}]})[0], 400)
        status, _ = self.admin.call("POST", "/api/stock/writeoff", {"comment": "Muddati o'tgan",
                                                                    "items": [{"product_id": a["id"], "qty": 3}]})
        self.assertEqual(status, 200)
        self.assertEqual(self.stock_of(a), 5)
        _, docs = self.admin.call("GET", "/api/stock/docs")
        self.assertEqual([d["kind"] for d in docs[:2]], ["writeoff", "count"])
        self.assertEqual(docs[0]["items"][0]["qty"], -3)
        _, st = self.admin.call("GET", "/api/stock?q=Inv")
        self.assertEqual({x["name"] for x in st["items"]}, {"Inv A", "Inv B"})
        _, low = self.admin.call("GET", "/api/stock?filter=low")
        self.assertIn(b["id"], [x["id"] for x in low["items"]])  # 4.5 <= 5 (minimum)
        self.assertNotIn(a["id"], [x["id"] for x in low["items"]])  # minimum belgilanmagan
        self.assertEqual(self.waiter.call("POST", "/api/stock/count", {"items": []})[0], 403)


if __name__ == "__main__":
    unittest.main()
