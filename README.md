# 🛒 EproPos — do'kon uchun savdo va ombor dasturi

Magazinlar uchun yengil POS va ombor tizimi. **Faqat Python kerak**: `pip install`, Node.js yoki internet shart emas.
Ma'lumotlar shu papkadagi `epropos.db` (SQLite) faylida saqlanadi.

## 🚀 Ishga tushirish

EproPos kompyuterda **alohida oynada** (desktop dastur kabi) ochiladi. Server qora oynasiz orqa fonda ishlaydi.

| Fayl | Vazifasi |
|------|----------|
| **ORNATISH.bat** | Bir marta: ish stoli va Pusk menyusiga "EproPos" yorlig'ini qo'shadi |
| **ISHGA_TUSHIR.bat** | Dasturni ochadi (yorliq bilan bir xil) |
| **TOXTATISH.bat** | Orqa fondagi serverni to'xtatadi |
| **YANGILASH.bat** | GitHub'dan yangi versiyani oladi va dasturni qayta ochadi |
| **TARMOQQA_RUXSAT.bat** | Telefon/planshetdan kirish uchun fayervolda ruxsat (bir marta) |

### Birinchi marta
1. **Python 3.8+** o'rnating: https://www.python.org/downloads/ ("Add Python to PATH" ni belgilang)
2. **ORNATISH.bat** ga ikki marta bosing
3. Ish stolidagi **EproPos** ikonkasini oching

Linux/macOS: `python3 desktop.py` (yoki faqat server: `python3 server.py`)

### Kirish
Kirish ekranida **parol** (4 ta raqam) ekrandagi raqamlar bilan teriladi — klaviatura shart emas.
Administratorning standart paroli: **1234** (Xodimlar bo'limida o'zgartiring).
5 marta noto'g'ri terilsa, 1 daqiqa kutish kerak bo'ladi.

## ✨ Imkoniyatlar

### 💰 Kassa
- **Shtrix-kod skaneri** — skaner tovar kodini o'qishi bilan tovar savatga tushadi (sichqoncha shart emas)
- Tovarni nomi bo'yicha qidirish yoki kategoriya bo'yicha tanlash
- **Tarozi tovarlari** (kg, litr, metr) — miqdor kasr son bilan kiritiladi (masalan 1.255 kg)
- Chegirma, mijozni tanlash, to'lov: naqd (qaytim hisoblanadi), karta, Payme, Click, **nasiya**
- **F2** — to'lov oynasi, **Enter** — tasdiqlash; savat sahifa yangilansa ham saqlanadi
- Omborda yetmaydigan tovar sotilmaydi (Sozlamalarda ruxsat berish mumkin)

### 🏬 Ombor
- **Qoldiqlar** — har bir tovar qoldig'i, qiymati (tannarx va sotish narxida), kam qolgan va tugaganlar
- **Kirim** — ta'minotchidan tovar qabul qilish: miqdor, tannarx, yangi sotish narxi;
  to'lanmagan qismi ta'minotchiga qarz bo'lib yoziladi. Tannarx o'rtacha hisoblanadi
- **Inventarizatsiya** — sanalgan haqiqiy qoldiq kiritiladi, farq avtomatik tuzatiladi
- **Hisobdan chiqarish** — yaroqsiz, singan, muddati o'tgan tovarlar
- **Harakatlar** — har bir kirim-chiqim tarixi (kim, qachon, nima uchun); tovarni bossangiz — o'z tarixi

### 📦 Mahsulotlar
- Nomi, shtrix-kod (yoki "Kod yaratish" — ichki EAN-13 kod), kategoriya, o'lchov birligi,
  tannarx, sotish narxi (ustama % ko'rinadi), minimal qoldiq, rasm
- **Import** — Excel shablon (.xlsx) yoki CSV orqali: nomi, shtrix-kod, kategoriya, birlik, narxlar, qoldiq

### 🧾 Savdolar
- Barcha cheklar: ko'rish, qayta chop etish, **qisman qaytarish** va **to'liq bekor qilish**
  (pul qaytariladi, tovar omborga qaytadi); chek o'chirilmaydi — tarixda qoladi
- **Sozlamalar → Chek**: chekda nimalar chiqishi (logo, do'kon nomi, kassir, mijoz, qaytim...) va qog'oz kengligi

### Boshqalar
- 👥 **CRM** — mijozlar, nasiyalar (muddati o'tgan / keldi / bor), to'lovlar
- 💵 **Moliya** — kassa balansi (naqd, karta, Payme, Click, hisob raqam), kirim-chiqim, ta'minotchilar balansi
- 📊 **Hisobotlar** — tushum, tannarx, **foyda**, ko'p sotilgan tovarlar, kassirlar
- 👤 **Xodimlar** — telefon, ism, 4 raqamli parol va bo'limlarga ruxsatlar
- 📓 **Jurnal** — barcha amallar: kim, qachon, nima qildi
- 🔌 **Integratsiyalar** — Telegram bot (xodimlar uchun jurnal xabarlari) va Mijozlar boti
  (chek, nasiya balansi, xabarlar)
- 🚫 Dublikatlar yo'q — bir xil nomli tovar/kategoriya yoki bir xil shtrix-kod ikki marta yaratilmaydi

## 📶 Telefon va planshetdan kirish
Qurilma kompyuter bilan bitta Wi-Fi'da bo'lsin. Manzil **Sozlamalar → Umumiy** sahifasida ko'rsatiladi
(masalan `http://192.168.1.10:8100`). Ochilmasa — **TARMOQQA_RUXSAT.bat**.

## 📱 Android ilova (APK)
Yuklab olish: **[EproPos.apk](https://github.com/ndoston1202-glitch/salespos1/releases/download/android-latest/EproPos.apk)**

- Ilova **telefonning o'zida to'liq ishlaydi** — internet ham, kompyuter ham shart emas
  (barcha bo'limlar: kassa, ombor, mahsulotlar, mijozlar, moliya, hisobotlar)
- Kompyuterdagi EproPos bilan ulash: telefonda **Sozlamalar → Sinxronlash** → *Kompyuterni qidirish* →
  kompyuterdagi administrator paroli. Shundan keyin telefon kompyuter bilan **bitta Wi-Fi'da bo'lganda**
  har 15 soniyada sotuvlar, tovarlar, qoldiqlar, mijozlar va boshqa ma'lumotlar o'zi almashadi
- Wi-Fi yo'q paytda qilingan savdolar saqlanib turadi va keyin yuboriladi; ikkala joyda sotilgan tovar
  qoldig'i to'g'ri qo'shib hisoblanadi
- Telefonda ma'lumot bo'lmasa — hammasi kompyuterdan olinadi (kompyuterdagi parollar bilan kirasiz);
  bo'lsa — ikkala baza birlashtiriladi
- Kompyuterda: **Sozlamalar → Sinxronlash** — ulangan telefonlar ro'yxati (keraksizini uzish mumkin)
- **🌐 Boshqa tarmoqda (internet orqali):** kompyuterda **Sozlamalar → Sinxronlash → Internet orqali ulanishni yoqish**.
  Kompyuter bepul Cloudflare tunneli orqali internetga chiqadi (ro'yxatdan o'tish, domen yoki routerda port ochish
  shart emas; `cloudflared` dasturi birinchi marta o'zi yuklab olinadi) va **internet kodi** (masalan `c6rbu-q4b3p`) beriladi.
  Telefonda manzil o'rniga shu kodni va administrator parolini kiriting. Wi-Fi'da ulangan telefonlar ham kompyuterdan
  uzoqlashganda internet orqali davom etadi. Internetga faqat sinxronlash ochiladi — kassa va hisobotlar internetdan
  ko'rinmaydi. Kompyuterning o'zgaruvchan tunnel manzili telefonlarga kod bo'yicha [ntfy.sh](https://ntfy.sh) orqali yetkaziladi
- Chek Android chop etish oynasi orqali chiqariladi (Bluetooth/Wi-Fi printer yoki PDF)

APK `android/` papkasidan GitHub Actions'da yig'iladi (Gradle + Chaquopy).

## 🔑 Obuna
EproPos oylik obuna bilan ishlaydi. Obunalar alohida **Obuna Admin** panelida boshqariladi
(alohida repozitoriya: `ndoston1202-glitch/obuna-admin`, dastur kodi: `epropos`).
- Mijozning EproPos'ida: **Sozlamalar → Obuna** — Do'kon ID (sotuvchiga aytiladi) va faollashtirish kodi kiritiladigan joy
- Yangi o'rnatilgan dastur **14 kun** sinov muddatida ishlaydi. Muddat tugashiga 5 kun qolganda ogohlantirish chiqadi,
  tugagach 3 kun imtiyoz, keyin dastur bloklanadi (ma'lumotlar saqlanadi) — kod kiritilsa darhol ochiladi
- Sotuvchi dasturni **vaqtincha to'xtatishi** mumkin: internetga ulanganda (30 daqiqagacha) bloklanadi
- Kompyuter va unga ulangan telefonlar — bitta obuna (bitta Do'kon ID)
- Kodlar raqamli imzo (Ed25519, `obuna.py`) bilan himoyalangan

## ☁️ Internetdagi server (Contabo va boshqa VPS)
Server (Ubuntu/Debian) terminalida bitta buyruq:
```
curl -fsSL https://raw.githubusercontent.com/ndoston1202-glitch/salespos1/main/deploy/install.sh | bash
```
- Natija: `https://<IP>.sslip.io` manzili (bepul HTTPS), administrator paroli ekranga chiqadi — yozib oling
- Do'kondagi kompyuter: **Sozlamalar → Sinxronlash → Serverga ulash** (server manzili + serverdagi parol).
  Kompyuterdagi ma'lumotlar serverga ko'chadi, kompyuter internetsiz ham ishlayveradi va server bilan sinxronlanadi
- Telefon/iPad: brauzerda server manzilini oching yoki ilovada **Sinxronlash** → server manzili
- Yangilash: dastur ichida **Sozlamalar → Yangilash** (yoki buyruqni qayta ishga tushirish)

## 🍎 iPhone ilova
- Telefonda brauzerda kompyuter manzilini oching (masalan `http://192.168.1.10:8100`) → **Sozlamalar → Mobil ilova**:
  qurilmangizga mos ilova (Android APK yoki iPhone) taklif qilinadi. Kompyuterda shu sahifada QR kod ham bor
- iPhone ilovasi **AltStore** orqali o'rnatiladi (bepul): AltStore'ga manba qo'shing —
  `https://github.com/ndoston1202-glitch/salespos1/releases/download/ios-latest/altstore.json` → EproPos → o'rnatish.
  Yangilanishlar AltStore → My Apps da chiqadi. Bepul Apple ID bilan AltStore ilovani har 7 kunda o'zi qayta imzolaydi
- IPA: [EproPos.ipa](https://github.com/ndoston1202-glitch/salespos1/releases/download/ios-latest/EproPos.ipa)
  (Sideloadly bilan ham o'rnatish mumkin). `ios/` papkasidan GitHub Actions'da (macOS) yig'iladi

## 🛠️ Texnologiya
- Backend: Python standart kutubxonasi (`http.server` + `sqlite3`) — `server.py`
- Frontend: oddiy HTML/CSS/JavaScript — `static/`
- Excel: `xlsx.py`, Telegram: `telegram.py`, desktop oyna: `desktop.py`

## 🧪 Testlar
```
python -m unittest discover tests
```

## ⚙️ Sozlamalar (ixtiyoriy)
| O'zgaruvchi | Standart | Tavsif |
|-------------|----------|--------|
| `EPROPOS_PORT` | `8100` | Server porti |
| `EPROPOS_DB` | `epropos.db` | Baza fayli yo'li |
