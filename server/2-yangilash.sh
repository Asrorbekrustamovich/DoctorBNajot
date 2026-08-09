#!/usr/bin/env bash
# ============================================================
#  YANGILASH — kodni serverga chiqarish.
#
#    sudo bash server/2-yangilash.sh
#
#  Har bosqichda xato bo'lsa TO'XTAYDI (set -e) — yarim yangilangan
#  holat eng yomon variant.
# ============================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/DoctorBNajot}"
SERVICE="${SERVICE:-edumed-his}"

cd "$APP_DIR"

say() { printf '\n\033[1;36m== %s ==\033[0m\n' "$1"; }

say "1/7  Zaxira"
bash server/5-zaxira.sh || echo "  (zaxira o'tkazib yuborildi)"

say "2/7  Serverni to'xtatish"
systemctl stop "$SERVICE" || true

say "3/7  Kutubxonalar"
source .venv/bin/activate
pip install -q -r requirements.txt

say "4/7  Migratsiyalar"
python manage.py migrate --noinput

say "5/7  Statik fayllar"
python manage.py collectstatic --noinput >/dev/null
echo "  yig'ildi"

say "6/7  Huquqlar"
chown -R www-data:www-data "$APP_DIR/media" "$APP_DIR/logs" 2>/dev/null || true
mkdir -p "$APP_DIR/media/tts"
chown -R www-data:www-data "$APP_DIR/media/tts"

say "7/7  Tekshiruv"
# deploy_check xato topsa 1 qaytaradi va skript shu yerda to'xtaydi —
# serverni buzuq holatda ishga tushirmaymiz.
python manage.py deploy_check

say "Ishga tushirish"
systemctl start "$SERVICE"
sleep 3
systemctl status "$SERVICE" --no-pager | head -8
nginx -t && systemctl reload nginx

printf '\n\033[1;32mTayyor.\033[0m Ovozni tekshirish:\n'
printf '  https://doctorbnajot.uz/registration/board/tts/health/\n'
printf 'Muammo bo%%s sa: server/YUKLASH.md\n'
