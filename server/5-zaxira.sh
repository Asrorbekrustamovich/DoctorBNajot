#!/usr/bin/env bash
# ============================================================
#  5) ZAXIRA NUSXA (backup).
#
#  Ishlatish:
#      bash server/5-zaxira.sh
#
#  Har kuni avtomatik ishlashi uchun (kechasi 02:00 da):
#      sudo crontab -e
#      0 2 * * * cd /opt/edumed-his && bash server/5-zaxira.sh >> logs/backup.log 2>&1
#
#  Ikki xil zaxira olinadi:
#    1. data.json + media  -> backups/edumed_backup_*.zip  (universal)
#    2. pg_dump            -> backups/pg_*.dump            (tez tiklash uchun)
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

say() { echo -e "\n\033[1;36m==> $*\033[0m"; }
ok()  { echo -e "  \033[1;32m✓\033[0m $*"; }
err() { echo -e "  \033[1;31m✗\033[0m $*" >&2; }

SAQLASH_KUNI="${SAQLASH_KUNI:-30}"
mkdir -p backups logs

# shellcheck disable=SC1091
source .venv/bin/activate

say "1/2  Universal zaxira (baza + rasmlar)"
python manage.py backup_db --keep "$SAQLASH_KUNI" && ok "Tayyor" || err "Xatolik"

say "2/2  PostgreSQL dump"
if command -v pg_dump >/dev/null; then
    # DATABASE_URL ni to'g'ridan-to'g'ri pg_dump ga beramiz
    DB_URL=$(python - <<'PY'
import os, environ, pathlib
env = environ.Env()
environ.Env.read_env(pathlib.Path(".env"))
print(env("DATABASE_URL", default=""))
PY
)
    if [ -n "$DB_URL" ] && [[ "$DB_URL" == postgres* ]]; then
        FAYL="backups/pg_$(date +%Y%m%d_%H%M%S).dump"
        if pg_dump --format=custom --no-owner --no-acl --file="$FAYL" "$DB_URL" 2>/dev/null; then
            ok "$FAYL ($(du -h "$FAYL" | cut -f1))"
            # Eskilarini tozalash
            find backups -name "pg_*.dump" -mtime "+$SAQLASH_KUNI" -delete
        else
            err "pg_dump ishlamadi (versiya mos kelmasligi mumkin) — universal zaxira baribir olindi"
            rm -f "$FAYL"
        fi
    else
        ok "PostgreSQL emas — o'tkazib yuborildi"
    fi
else
    err "pg_dump o'rnatilmagan:  sudo apt install postgresql-client"
fi

say "Zaxiralar ro'yxati"
ls -lht backups/ 2>/dev/null | head -8 | sed 's/^/  /'
echo
echo "  Jami: $(du -sh backups 2>/dev/null | cut -f1)"
echo
echo "  MUHIM: zaxirani boshqa joyga ham nusxalang (tashqi disk / bulut)."
echo "  Server buzilsa, serverdagi zaxira ham yo'qoladi."
