#!/usr/bin/env bash
# ============================================================
#  6) ZAXIRADAN TIKLASH.
#
#  Ishlatish:
#      bash server/6-tiklash.sh                       # oxirgi zaxiradan
#      bash server/6-tiklash.sh backups/edumed_backup_20260801_020000.zip
#      bash server/6-tiklash.sh backups/pg_20260801.dump
#
#  DIQQAT: hozirgi ma'lumotlar ustiga yoziladi. Avval tasdiq so'raladi.
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

say() { echo -e "\n\033[1;36m==> $*\033[0m"; }
ok()  { echo -e "  \033[1;32m✓\033[0m $*"; }
die() { echo -e "  \033[1;31m✗\033[0m $*" >&2; exit 1; }

# shellcheck disable=SC1091
source .venv/bin/activate

FAYL="${1:-}"
if [ -z "$FAYL" ]; then
    FAYL=$(find backups -name "*.zip" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    [ -n "$FAYL" ] || die "backups/ ichida zaxira topilmadi"
    echo "  Oxirgi zaxira tanlandi: $FAYL"
fi
[ -f "$FAYL" ] || die "Fayl topilmadi: $FAYL"

say "Hozirgi holat"
python manage.py check_db --full 2>/dev/null | tail -20

echo
echo -e "\033[1;31m  DIQQAT: hozirgi ma'lumotlar ustiga yoziladi!\033[0m"
echo "  Tiklanadigan fayl: $FAYL"
read -r -p "  Davom etilsinmi? (HA deb yozing): " JAVOB
[ "$JAVOB" = "HA" ] || die "Bekor qilindi"

# Har ehtimolga qarshi — hozirgi holatni saqlab qo'yamiz
say "Tiklashdan oldin joriy holat saqlanmoqda"
python manage.py backup_db --keep 30 || true

case "$FAYL" in
    *.dump)
        say "pg_restore orqali tiklanmoqda"
        command -v pg_restore >/dev/null || die "pg_restore yo'q: sudo apt install postgresql-client"
        DB_URL=$(python - <<'PY'
import environ, pathlib
env = environ.Env(); environ.Env.read_env(pathlib.Path(".env"))
print(env("DATABASE_URL", default=""))
PY
)
        pg_restore --clean --if-exists --no-owner --no-acl -d "$DB_URL" "$FAYL" \
            || die "Tiklashda xatolik"
        ;;
    *.zip)
        say "Universal zaxiradan tiklanmoqda"
        python manage.py restore_db "$FAYL" || die "Tiklashda xatolik"
        ;;
    *.json)
        say "JSON dan tiklanmoqda"
        python manage.py loaddata "$FAYL" || die "Tiklashda xatolik"
        ;;
    *)
        die "Noma'lum format: $FAYL (.zip, .dump yoki .json bo'lishi kerak)"
        ;;
esac

ok "Tiklandi"

say "Natija"
python manage.py check_db --full

say "Xizmatlarni qayta ishga tushirish"
if systemctl list-unit-files 2>/dev/null | grep -q edumed-his; then
    sudo systemctl restart edumed-his && ok "edumed-his qayta ishga tushdi"
fi
