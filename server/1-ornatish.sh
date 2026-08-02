#!/usr/bin/env bash
# ============================================================
#  1) BIRINCHI O'RNATISH — serverda faqat BIR MARTA ishlatiladi.
#
#  Ishlatish:
#      cd /opt/edumed-his
#      bash server/1-ornatish.sh
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

say()  { echo -e "\n\033[1;36m==> $*\033[0m"; }
ok()   { echo -e "  \033[1;32m✓\033[0m $*"; }
err()  { echo -e "  \033[1;31m✗\033[0m $*" >&2; }
die()  { err "$*"; exit 1; }

say "Loyiha papkasi: $PROJECT_DIR"

# ---------- 1. Tizim paketlari ----------
say "Tizim paketlari o'rnatilmoqda"
if command -v apt-get >/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq \
        python3 python3-venv python3-dev python3-pip \
        build-essential libpq-dev \
        redis-server nginx postgresql-client curl
    ok "apt paketlari o'rnatildi"
else
    err "apt-get topilmadi — paketlarni qo'lda o'rnating"
fi

# ---------- 2. Virtual muhit ----------
say "Python virtual muhiti"
if [ ! -d .venv ]; then
    python3 -m venv .venv
    ok ".venv yaratildi"
else
    ok ".venv allaqachon mavjud"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
ok "Python paketlari o'rnatildi ($(pip list 2>/dev/null | wc -l) ta)"

# ---------- 3. .env ----------
say ".env fayli"
if [ ! -f .env ]; then
    if [ -f .env.server ]; then
        cp .env.server .env
        ok ".env.server dan nusxa olindi"
    else
        cp .env.example .env
        ok ".env.example dan nusxa olindi"
    fi
    NEW_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"
    python - "$NEW_KEY" <<'PY'
import re, sys
key = sys.argv[1]
s = open(".env", encoding="utf-8").read()
s = re.sub(r"^SECRET_KEY=.*$", f"SECRET_KEY={key}", s, flags=re.M)
open(".env", "w", encoding="utf-8").write(s)
PY
    chmod 600 .env
    ok "Yangi SECRET_KEY yaratildi va .env ga yozildi"
else
    ok ".env allaqachon mavjud — tegilmadi"
fi
chmod 600 .env

grep -q "ALMASHTIR\|BU-YERGA" .env && die ".env da to'ldirilmagan qiymatlar bor — tekshiring: nano .env"

# ---------- 4. Baza ----------
say "Bazaga ulanish tekshirilmoqda"
python manage.py check_db || die "Bazaga ulanib bo'lmadi — .env dagi DATABASE_URL ni tekshiring"

say "Migratsiyalar"
python manage.py migrate --noinput
ok "Migratsiyalar qo'llandi"

say "Boshlang'ich ma'lumotlar (rollar)"
python manage.py seed_roles || true
ok "Rollar tayyor"

# ---------- 5. Statik fayllar ----------
say "Statik fayllar yig'ilmoqda"
python manage.py collectstatic --noinput -v 0
ok "staticfiles/ tayyor"

mkdir -p media logs backups
ok "media/ logs/ backups/ papkalari yaratildi"

# ---------- 6. Sozlamalarni tekshirish ----------
say "Django xavfsizlik tekshiruvi"
python manage.py check --deploy || err "Yuqoridagi ogohlantirishlarni ko'rib chiqing"

# ---------- 7. systemd ----------
say "systemd xizmatlari"
echo "  Quyidagi buyruqlarni bajaring (root huquqi kerak):"
echo
echo "    sudo cp server/systemd/*.service /etc/systemd/system/"
echo "    sudo systemctl daemon-reload"
echo "    sudo systemctl enable --now edumed-his edumed-celery"
echo
echo "  Nginx uchun:"
echo "    sudo cp server/nginx-edumed.conf /etc/nginx/sites-available/edumed"
echo "    sudo ln -sf /etc/nginx/sites-available/edumed /etc/nginx/sites-enabled/"
echo "    sudo nginx -t && sudo systemctl reload nginx"
echo
echo "  HTTPS sertifikat (bepul):"
echo "    sudo apt install certbot python3-certbot-nginx"
echo "    sudo certbot --nginx -d doctorbnajot.uz -d www.doctorbnajot.uz"
echo

say "O'RNATISH TUGADI"
echo "  Keyingi qadam: superadmin yaratish"
echo "    source .venv/bin/activate && python manage.py createsuperuser"
echo
echo "  SQLite'dagi eski ma'lumotlarni ko'chirish:"
echo "    bash server/3-malumot-kochirish.sh"
