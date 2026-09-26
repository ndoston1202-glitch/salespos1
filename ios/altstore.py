"""AltStore manbasi (altstore.json): AltStore shu fayl orqali EproPos'ning yangi versiyasini topadi va yangilaydi."""

import json
import os
import sys

REPO = "ndoston1202-glitch/salespos1"
BASE = f"https://github.com/{REPO}/releases/download/ios-latest"


def main(ipa, out_dir):
    with open("version.json", encoding="utf-8") as f:
        v = json.load(f)
    version = {"version": v["version"], "date": v.get("date", ""), "size": os.path.getsize(ipa),
               "downloadURL": f"{BASE}/EproPos.ipa", "localizedDescription": "\n".join(v.get("notes") or [])}
    source = {
        "name": "EproPos",
        "identifier": "uz.epropos.source",
        "subtitle": "Do'kon uchun savdo va ombor dasturi",
        "iconURL": f"https://raw.githubusercontent.com/{REPO}/main/static/img/icon-512.png",
        "website": f"https://github.com/{REPO}",
        "tintColor": "1F9E45",
        "apps": [{
            "name": "EproPos",
            "bundleIdentifier": "uz.epropos.epropos",
            "developerName": "EproPos",
            "subtitle": "Kassa, ombor va sinxronlash",
            "localizedDescription": "Kassa, ombor, mijozlar va moliya. iPhone'ning o'zida internetsiz ishlaydi, "
                                    "kompyuterdagi EproPos bilan Wi-Fi yoki internet orqali sinxronlanadi.",
            "iconURL": f"https://raw.githubusercontent.com/{REPO}/main/static/img/icon-512.png",
            "tintColor": "1F9E45",
            "versions": [version],
            # eski AltStore versiyalari uchun
            "version": version["version"], "versionDate": version["date"], "downloadURL": version["downloadURL"],
            "size": version["size"],
            "appPermissions": {"entitlements": [], "privacy": {
                "NSCameraUsageDescription": "Tovar shtrix-kodini skanerlash uchun kamera kerak",
                "NSLocalNetworkUsageDescription": "Shu Wi-Fi'dagi kompyuterdagi EproPos bilan ma'lumot almashish uchun"}},
        }],
        "news": [],
    }
    with open(os.path.join(out_dir, "altstore.json"), "w", encoding="utf-8") as f:
        json.dump(source, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "version.json"), "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
