"""Dastur ichida yangilash: yangi versiya yuklanadi, fayllar almashadi, server o'zi qayta ishga tushadi."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_api import Client  # noqa: E402
from test_sync import free_port  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_FILES = ["server.py", "sync.py", "telegram.py", "tunnel.py", "xlsx.py", "version.json", "static"]


def make_zip(src, version):
    """GitHub arxivi kabi: salespos1-main/ ichida dastur fayllari (+ tegilmasligi kerak bo'lganlar)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in APP_FILES:
            path = os.path.join(src, name)
            if os.path.isdir(path):
                for dirpath, _, files in os.walk(path):
                    for f in files:
                        full = os.path.join(dirpath, f)
                        z.write(full, "salespos1-main/" + os.path.relpath(full, src))
            elif name == "version.json":
                z.writestr("salespos1-main/version.json", json.dumps({"version": version, "notes": ["Sinov"]}))
            else:
                z.write(path, "salespos1-main/" + name)
        z.writestr("salespos1-main/YANGI_FAYL.txt", "yangi")
        z.writestr("salespos1-main/epropos.db", "buzilgan baza")      # yozilmasligi kerak
        z.writestr("salespos1-main/uploads/rasm.png", "x")            # yozilmasligi kerak
    return buf.getvalue()


class UpdateTest(unittest.TestCase):
    def test_install_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = os.path.join(tmp, "app")
            os.makedirs(app)
            for name in APP_FILES:
                src = os.path.join(ROOT, name)
                (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(app, name))
            with open(os.path.join(app, "version.json"), "w") as f:
                json.dump({"version": "1.0.0"}, f)
            # yangi versiya turgan "GitHub"
            site = os.path.join(tmp, "site")
            os.makedirs(site)
            with open(os.path.join(site, "main.zip"), "wb") as f:
                f.write(make_zip(ROOT, "9.9.9"))
            with open(os.path.join(site, "version.json"), "w") as f:
                json.dump({"version": "9.9.9", "notes": ["Sinov"]}, f)

            class Quiet(SimpleHTTPRequestHandler):
                def __init__(self, *a, **k):
                    super().__init__(*a, directory=site, **k)

                def log_message(self, *a):
                    pass

            web = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
            threading.Thread(target=web.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{web.server_address[1]}"
            port = free_port()
            clean = {k: v for k, v in os.environ.items() if not k.startswith("EPROPOS_")}  # boshqa testlarniki
            env = dict(clean, EPROPOS_PORT=str(port), EPROPOS_UPDATE_ZIP=base + "/main.zip",
                       EPROPOS_UPDATE_VERSION_URL=base + "/version.json", NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
            log = open(os.path.join(tmp, "server.log"), "w")
            subprocess.Popen([sys.executable, os.path.join(app, "server.py"), "--no-browser"], cwd=app, env=env,
                             stdout=log, stderr=subprocess.STDOUT)
            url = f"http://127.0.0.1:{port}"
            try:
                for _ in range(100):
                    try:
                        client = Client(url).pin("1234")
                        break
                    except OSError:
                        time.sleep(0.1)
                pid_path = os.path.join(app, "epropos.pid")
                for _ in range(50):  # pid fayli port ochilgandan keyin yoziladi
                    if os.path.exists(pid_path):
                        break
                    time.sleep(0.1)
                self.assertTrue(os.path.exists(pid_path), open(os.path.join(tmp, "server.log")).read())
                with open(pid_path) as f:
                    pid_before = f.read()
                _, p = client.call("POST", "/api/products", {"name": "Saqlanadigan tovar", "price": 700})
                _, u = client.call("GET", "/api/update?force=1")
                self.assertEqual((u["available"], u["current"], u["latest"]), (True, "1.0.0", "9.9.9"), u)
                status, res = client.call("POST", "/api/update/install")
                self.assertEqual((status, res.get("version")), (200, "9.9.9"), res)
                # server o'zi qayta ishga tushadi
                info = None
                for _ in range(150):
                    time.sleep(0.2)
                    try:
                        info = Client(url).call("GET", "/api/sync/hello")[1]
                        if info.get("version") == "9.9.9":
                            break
                    except OSError:
                        pass
                self.assertEqual(info and info.get("version"), "9.9.9", open(os.path.join(app, "epropos.log")).read())
                with open(os.path.join(app, "epropos.pid")) as f:
                    self.assertNotEqual(f.read(), pid_before)  # yangi jarayon
                self.assertTrue(os.path.exists(os.path.join(app, "YANGI_FAYL.txt")))
                self.assertFalse(os.path.exists(os.path.join(app, "uploads", "rasm.png")))
                client = Client(url).pin("1234")  # baza va parollar saqlangan
                names = [x["name"] for x in client.call("GET", "/api/products")[1]]
                self.assertIn("Saqlanadigan tovar", names)
                self.assertFalse(client.call("GET", "/api/update?force=1")[1]["available"])
            finally:
                pid_path = os.path.join(app, "epropos.pid")
                if os.path.exists(pid_path):
                    try:
                        os.kill(int(open(pid_path).read()), 15)
                    except (OSError, ValueError):
                        pass
                time.sleep(0.3)
                web.shutdown()
                log.close()


if __name__ == "__main__":
    unittest.main()
