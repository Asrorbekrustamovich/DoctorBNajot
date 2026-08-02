#!/usr/bin/env bash
# ============================================================
#  2) YANGILASH (deploy) — kod o'zgargandan keyin har safar.
#
#  Ishlatish:
#      bash server/2-yangilash.sh
#      bash server/2-yangilash.sh --no-git     # git pull qilmasdan
#
#  Nima qiladi: zaxira -> kodni yangilash -> paketlar -> migratsiya
#  -> statik fayllar -> xizmatlarni qayta ishga tushirish -> tekshirish
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

say() { echo -e "\n\033[1;36m==> $*\033[0m"; }
ok()  { echo -e "  \033[1;32m✓\033[0m $*"; }
err() { echo -e "  \033[1;31m✗\033[0m $*" >&2; }

DO_GIT=1
[ "${1:-}" = "--no-git" ] && DO_GIT=0

# shellcheck disable=SC1091
source .venv/bin/activate

# ---------- 1. Zaxira (orqaga qaytish kerak bo'lsa) ----------
say "Yangilashdan oldin zaxira"
python manage.py backup_db --keep 30 || err "Zaxira olinmadi — davom etilmoqda"

# ---------- 2. Kod ----------
if [ "$DO_GIT" = "1" ] && [ -d .git ]; then
    say "Kod yangilanmoqda (git pull)"
    git pull --ff-only
    ok "Kod yangilandi: $(git rev-parse --short HEAD)"
fi

# ---------- 3. Paketlar ----------
say "Paketlar tekshirilmoqda"
pip install -r requirements.txt -q
ok "Paketlar dolzarb"

# ---------- 4. Migratsiya ----------
say "Migratsiyalar"
python manage.py migrate --noinput
ok "Baza dolzarb"

# ---------- 5. Statik ----------
say "Statik fayllar"
python manage.py collectstatic --noinput -v 0
ok "staticfiles/ yangilandi"

# ---------- 6. Xizmatlar ----------
say "Xizmatlar qayta ishga tushirilmoqda"
if systemctl list-unit-files 2>/dev/null | grep -q edumed-his; then
    sudo systemctl restart edumed-his
    ok "edumed-his qayta ishga tushdi"
    if systemctl list-unit-files | grep -q edumed-celery; then
        sudo systemctl restart edumed-celery
        ok "edumed-celery qayta ishga tushdi"
    fi
else
    err "systemd xizmati topilmadi — qo'lda ishga tushiring"
fi

# ---------- 7. Tekshirish ----------
say "Tekshirish"
sleep 3
bash server/4-tekshirish.sh || err "Tekshiruvda muammo bor — loglarni ko'ring"

say "YANGILASH TUGADI"
