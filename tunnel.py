"""Kompyuterni internet orqali telefonlarga ochish (turli tarmoqlarda sinxronlash uchun).

Cloudflare'ning bepul "quick tunnel" xizmati (cloudflared dasturi) ishlatiladi: ro'yxatdan o'tish, domen yoki
routerda port ochish shart emas. Tunnel faqat sinxronlash so'rovlarini qabul qiladigan alohida ichki portga
ulanadi - dasturning o'zi (kassa, hisobotlar...) internetga ochilmaydi.
Tunnel manzili har ishga tushganda o'zgaradi, shuning uchun u sync.relay_publish orqali e'lon qilinadi."""

import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request

DOWNLOAD = "https://github.com/cloudflare/cloudflared/releases/latest/download/"
URL_RE = re.compile(os.environ.get("EPROPOS_TUNNEL_RE", r"https://(?!api\.)[-a-z0-9]+\.trycloudflare\.com"))


def asset_name():
    system, machine = platform.system().lower(), platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64",
            "i386": "386", "i686": "386", "x86": "386"}.get(machine, "arm" if machine.startswith("arm") else "amd64")
    if system == "windows":
        return f"cloudflared-windows-{arch}.exe"
    if system == "darwin":
        return f"cloudflared-darwin-{arch}.tgz"
    return f"cloudflared-linux-{arch}"


class Tunnel:
    def __init__(self, port, tools_dir, on_url):
        self.port = port
        self.tools_dir = tools_dir
        self.on_url = on_url
        self.enabled = False
        self.state = "off"      # off / downloading / starting / online / error
        self.url = None
        self.error = None
        self.proc = None
        self.thread = None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            self.enabled = True
            if self.thread and self.thread.is_alive():
                return
            self.state, self.error = "starting", None
            self.thread = threading.Thread(target=self.loop, daemon=True, name="epropos-tunnel")
            self.thread.start()

    def stop(self):
        with self.lock:
            self.enabled = False
            self.state, self.url, self.error = "off", None, None
            proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()

    def command(self):
        custom = os.environ.get("EPROPOS_CLOUDFLARED")
        if custom:  # testlar va maxsus o'rnatishlar uchun
            return shlex.split(custom)
        exe = shutil.which("cloudflared") or self.download()
        return [exe]

    def download(self):
        name = asset_name()
        exe = os.path.join(self.tools_dir, "cloudflared.exe" if name.endswith(".exe") else "cloudflared")
        if os.path.isfile(exe):
            return exe
        self.state = "downloading"
        os.makedirs(self.tools_dir, exist_ok=True)
        tmp = exe + ".part"
        with urllib.request.urlopen(DOWNLOAD + name, timeout=60) as res, open(tmp, "wb") as f:
            shutil.copyfileobj(res, f)
        if name.endswith(".tgz"):
            with tarfile.open(tmp) as tar:
                member = next(m for m in tar.getmembers() if m.name.endswith("cloudflared"))
                with tar.extractfile(member) as src, open(exe + ".bin", "wb") as dst:
                    shutil.copyfileobj(src, dst)
            os.remove(tmp)
            tmp = exe + ".bin"
        os.chmod(tmp, 0o755)
        os.replace(tmp, exe)
        return exe

    def loop(self):
        delay = 5
        while self.enabled:
            started = time.time()
            try:
                self.run(self.command())
            except Exception as e:
                self.error = f"Tunnel ishga tushmadi: {e}"
            if not self.enabled:
                break
            self.url, self.state = None, "error"
            if time.time() - started > 300:
                delay = 5
            time.sleep(delay)
            delay = min(delay * 2, 120)
            if self.enabled:
                self.state = "starting"

    def run(self, cmd):
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW: qora oyna chiqmasin
        proc = subprocess.Popen(cmd + ["tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self.port}"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                text=True, errors="replace", creationflags=flags)
        with self.lock:
            if not self.enabled:
                proc.terminate()
                return
            self.proc = proc
        last = []
        for line in proc.stderr:  # oxirigacha o'qiladi (aks holda cloudflared to'xtab qoladi)
            last = (last + [line.strip()])[-3:]
            m = URL_RE.search(line)
            if m and self.url != m.group(0):
                self.url, self.state, self.error = m.group(0), "online", None
                try:
                    self.on_url(self.url)
                except Exception:
                    pass
        proc.wait()
        if self.enabled:
            self.error = "Tunnel to'xtadi" + (f": {last[-1]}" if last else "")
