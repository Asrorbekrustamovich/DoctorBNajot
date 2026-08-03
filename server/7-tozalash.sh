#!/usr/bin/env bash
# ============================================================
#  7) TO'LIQ TOZALASH — sinov ma'lumotlarini o'chirish.
#
#  Klinikani haqiqiy ishga tushirishdan OLDIN bir marta ishlatiladi.
#
#  Ishlatish:
#      bash server/7-tozalash.sh --korish    # faqat ko'rsatadi (xavfsiz)
#      bash server/7-tozalash.sh             # tasdiq so'rab o'chiradi
#
#  O'CHADI : bemorlar, tashriflar, hisobotlar, operatsiyalar, cheklar,
#            dorilar ro'yxati, umumiy ombor, anesteziolog ombori, audit
#  QOLADI  : xodimlar, rollar, xizmatlar katalogi, palatalar, xonalar,
#            operatsiya turlari, jarrohlik anjomlari
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

say() { echo -e "\n\033[1;36m==> $*\033[0m"; }
ok()  { echo -e "  \033[1;32m✓\033[0m $*"; }
die() { echo -e "  \033[1;31m✗\033[0m $*" >&2; exit 1; }

# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || die ".venv topilmadi"

if [ "${1:-}" = "--korish" ] || [ "${1:-}" = "--dry-run" ]; then
    python manage.py clear_all_data --dry-run
    exit 0
fi

say "Bazaga ulanish tekshirilmoqda"
python manage.py check_db >/dev/null || die "Bazaga ulanib bo'lmadi"
ok "Baza joyida"

say "Tozalash boshlanmoqda"
echo "  (buyruq avval ro'yxatni ko'rsatadi, keyin HA so'raydi, so'ng zaxira oladi)"
python manage.py clear_all_data

say "Xizmatlar qayta ishga tushirilmoqda"
if systemctl list-unit-files 2>/dev/null | grep -q edumed-his; then
    sudo systemctl restart edumed-his && ok "edumed-his qayta ishga tushdi"
fi

say "Yakuniy holat"
python manage.py check_db --full
