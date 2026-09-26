"""EproPos iPhone ilovasi.

Dasturning o'zi (server.py, baza) iPhone'da ishlaydi - internet yoki kompyuter shart emas.
Oyna - WKWebView (http://127.0.0.1). Kompyuter bilan sinxronlash server.SyncWorker orqali.
Chop etish: sahifa /api/native/print ni chaqiradi -> iOS AirPrint oynasi."""

import os
import sys

import toga
from toga.style import Pack

CORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core")  # server.py, static/ (CI nusxalaydi)
sys.path.insert(0, CORE)


class EproPos(toga.App):
    def startup(self):
        data = str(self.paths.data)
        os.makedirs(data, exist_ok=True)
        os.environ["EPROPOS_PLATFORM"] = "ios"
        import mobile_main  # noqa: E402 - yo'l yuqorida qo'shildi

        port = mobile_main.start(os.path.join(data, "data"), os.path.join(CORE, "static"), 8100)
        import server

        server.NATIVE["print"] = lambda: self.loop.call_soon_threadsafe(self.print_page)

        self.web = toga.WebView(url=f"http://127.0.0.1:{port}/", style=Pack(flex=1))
        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = self.web
        self.main_window.show()

    def print_page(self):
        """Chek: iOS chop etish oynasi (AirPrint printer yoki PDF sifatida saqlash)."""
        try:
            from rubicon.objc import ObjCClass

            controller = ObjCClass("UIPrintInteractionController").sharedPrintController
            controller.printFormatter = self.web._impl.native.viewPrintFormatter()
            controller.presentAnimated(True, completionHandler=None)
        except Exception as e:  # chop etish bo'lmasa ham ilova yiqilmasin
            print("Chop etib bo'lmadi:", e)


def main():
    return EproPos("EproPos", "uz.epropos.epropos")
