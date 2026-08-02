#!/usr/bin/env bash
# ============================================================
#  3) SQLite -> PostgreSQL ma'lumot ko'chirish.
#
#  Ishlatish (loyiha papkasida):
#      bash server/3-malumot-kochirish.sh
#      bash server/3-malumot-kochirish.sh /yo/l/db.sqlite3
#
#  Xavfsiz: eski SQLite fayliga TEGILMAYDI, faqat o'qiladi.
#  Bemorlar, tashriflar, imzolar, sterilizatsiya tarixi — hammasi ko'chadi.
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

say() { echo -e "\n\033[1;36m==> $*\033[0m"; }
ok()  { echo -e "  \033[1;32m✓\033[0m $*"; }
die() { echo -e "  \033[1;31m✗\033[0m $*" >&2; exit 1; }

SQLITE_PATH="${1:-$PROJECT_DIR/db.sqlite3}"
[ -f "$SQLITE_PATH" ] || die "SQLite fayli topilmadi: $SQLITE_PATH"

# shellcheck disable=SC1091
source .venv/bin/activate

DUMP="$PROJECT_DIR/backups/kochirish_$(date +%Y%m%d_%H%M%S).json"
mkdir -p "$PROJECT_DIR/backups"

say "1/4  Eski bazadan ma'lumot olinmoqda"
echo "     Manba: $SQLITE_PATH"

# Vaqtinchalik sozlama: faqat shu buyruq uchun SQLite'ga ulanamiz
cat > /tmp/_kochirish_settings.py <<PY
import sys
sys.path.insert(0, "$PROJECT_DIR")
from config.settings.production import *  # noqa
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": "$SQLITE_PATH",
}}
DEBUG = False
PY

PYTHONPATH="/tmp:$PROJECT_DIR" python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes --exclude auth.Permission \
    --exclude sessions --exclude admin.logentry \
    --exclude django_celery_beat \
    --indent 1 --settings=_kochirish_settings \
    -o "$DUMP" || die "Ma'lumot olinmadi"

SIZE=$(du -h "$DUMP" | cut -f1)
COUNT=$(python -c "import json;print(len(json.load(open('$DUMP'))))")
ok "$COUNT ta yozuv olindi ($SIZE) -> $DUMP"

say "2/4  Yangi bazaga ulanish tekshirilmoqda"
python manage.py check_db >/dev/null || die "PostgreSQL ga ulanib bo'lmadi"
ok "PostgreSQL tayyor"

say "3/4  Migratsiyalar qo'llanmoqda"
python manage.py migrate --noinput
ok "Jadvallar yaratildi"

# Bo'sh emasligini ogohlantiramiz
EXISTING=$(python - <<'PY'
import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django.setup()
from apps.patients.models import Patient
print(Patient.objects.count())
PY
)
if [ "$EXISTING" != "0" ]; then
    echo
    echo "  DIQQAT: PostgreSQL bazasida allaqachon $EXISTING ta bemor bor."
    read -r -p "  Ustiga ko'chirilsinmi? (ha/yo'q): " JAVOB
    [ "$JAVOB" = "ha" ] || die "Bekor qilindi"
fi

say "4/4  Ma'lumotlar yangi bazaga yozilmoqda"
python manage.py loaddata "$DUMP" || die "Yuklashda xatolik — yuqoridagi xabarni o'qing"
ok "Ma'lumotlar ko'chirildi"

say "Natija"
python manage.py check_db --full

rm -f /tmp/_kochirish_settings.py
echo
echo "  Eski SQLite fayli o'z joyida qoldi: $SQLITE_PATH"
echo "  Bir necha kun ishlatib ko'ring, keyin o'chirsangiz bo'ladi."
