#!/usr/bin/env bash
# EproPos'ni internetdagi serverga (VPS: Contabo va boshqalar, Ubuntu/Debian) o'rnatish yoki yangilash.
#
#   curl -fsSL https://raw.githubusercontent.com/ndoston1202-glitch/salespos1/main/deploy/install.sh | bash
#
# Natija: https://<IP>.sslip.io (bepul HTTPS sertifikati bilan), server qayta yoqilsa ham o'zi ishga tushadi.
# O'z domeningiz bo'lsa:  EPROPOS_DOMAIN=pos.misol.uz bash install.sh
set -euo pipefail

REPO="https://github.com/ndoston1202-glitch/salespos1.git"
APP=/opt/epropos
DATA=/var/lib/epropos
ENV_FILE=/etc/epropos.env

if [ "$(id -u)" != 0 ]; then
    echo "Root sifatida ishga tushiring: sudo bash install.sh"
    exit 1
fi
export DEBIAN_FRONTEND=noninteractive

echo "==> Kerakli dasturlar o'rnatilmoqda..."
apt-get update -q
apt-get install -y -q python3 git curl gnupg ufw ca-certificates debian-keyring debian-archive-keyring apt-transport-https
if ! command -v caddy >/dev/null; then
    # Caddy - HTTPS (Let's Encrypt sertifikatini o'zi oladi va yangilaydi)
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q
    apt-get install -y -q caddy
fi

echo "==> EproPos yuklab olinmoqda..."
id epropos >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin epropos
if [ -d "$APP/.git" ]; then
    sudo -u epropos git -C "$APP" pull --ff-only
else
    git clone --depth 1 "$REPO" "$APP"
fi
mkdir -p "$DATA/uploads"
chown -R epropos:epropos "$APP" "$DATA"  # dastur ichidan yangilash uchun epropos yozishi kerak

IP=$(curl -fsS -4 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
DOMAIN="${EPROPOS_DOMAIN:-$(echo "$IP" | tr . -).sslip.io}"

NEW_PIN=""
if [ ! -f "$ENV_FILE" ]; then
    NEW_PIN=$(shuf -i 1000-9999 -n 1)  # yangi serverda 1234 emas - tasodifiy parol
    cat > "$ENV_FILE" <<CONF
EPROPOS_ROLE=hub
EPROPOS_DB=$DATA/epropos.db
EPROPOS_UPLOADS=$DATA/uploads
EPROPOS_HOST=127.0.0.1
EPROPOS_PORT=8100
EPROPOS_TRUST_PROXY=1
EPROPOS_NO_DEMO=1
EPROPOS_ADMIN_PIN=$NEW_PIN
EPROPOS_PUBLIC_URL=https://$DOMAIN
CONF
    chmod 600 "$ENV_FILE"
else
    sed -i "s|^EPROPOS_PUBLIC_URL=.*|EPROPOS_PUBLIC_URL=https://$DOMAIN|" "$ENV_FILE"
fi

cat > /etc/systemd/system/epropos.service <<UNIT
[Unit]
Description=EproPos
After=network-online.target
Wants=network-online.target

[Service]
User=epropos
WorkingDirectory=$APP
EnvironmentFile=$ENV_FILE
Environment=HOME=$DATA
ExecStart=/usr/bin/python3 $APP/server.py --no-browser
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    encode gzip
    reverse_proxy 127.0.0.1:8100
}
CADDY

echo "==> Fayervol: faqat SSH, HTTP va HTTPS ochiq"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

systemctl daemon-reload
systemctl enable --now epropos >/dev/null
systemctl restart epropos
systemctl enable caddy >/dev/null
systemctl restart caddy

echo "==> Tekshirilmoqda (HTTPS sertifikati 1-2 daqiqa olinishi mumkin)..."
ok=""
for _ in $(seq 1 60); do
    if curl -fsS "https://$DOMAIN/api/sync/hello" >/dev/null 2>&1; then ok=1; break; fi
    sleep 3
done

echo
echo "=================================================="
if [ -n "$ok" ]; then
    echo "  EproPos serverda ishlayapti!"
else
    echo "  EproPos o'rnatildi (HTTPS hali tayyor emas - birozdan keyin oching)"
fi
echo "  Manzil:  https://$DOMAIN"
if [ -n "$NEW_PIN" ]; then
    echo "  Administrator paroli:  $NEW_PIN   (yozib oling!)"
fi
echo "  Do'kondagi kompyuterni ulash: EproPos -> Sozlamalar -> Sinxronlash -> Serverga ulash"
echo "=================================================="
