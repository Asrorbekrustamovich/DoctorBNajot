#!/usr/bin/env bash
# ============================================================
#  4) SOG'LIQ TEKSHIRUVI — "hammasi joyidami?"
#
#  Ishlatish:
#      bash server/4-tekshirish.sh
#
#  Har kuni ertalab yoki muammo bo'lganda birinchi shu ishga tushiriladi.
# ============================================================
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

say()  { echo -e "\n\033[1;36m==> $*\033[0m"; }
ok()   { echo -e "  \033[1;32m✓\033[0m $*"; }
bad()  { echo -e "  \033[1;31m✗\033[0m $*"; XATO=$((XATO+1)); }
warn() { echo -e "  \033[1;33m!\033[0m $*"; }
XATO=0

DOMEN="${DOMEN:-doctorbnajot.uz}"

# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || { echo ".venv topilmadi"; exit 1; }

say "1) Xizmatlar"
for SVC in edumed-his edumed-celery redis-server nginx; do
    if systemctl list-unit-files 2>/dev/null | grep -q "^$SVC"; then
        if systemctl is-active --quiet "$SVC"; then
            ok "$SVC ishlayapti"
        else
            bad "$SVC TO'XTAGAN  →  sudo systemctl start $SVC"
        fi
    else
        warn "$SVC o'rnatilmagan"
    fi
done

say "2) Ma'lumotlar bazasi"
python manage.py check_db 2>&1 | sed 's/^/  /' | tail -n +2

say "3) Veb-sayt javob beryaptimi"
for URL in "http://127.0.0.1:8000/accounts/login/" "https://$DOMEN/accounts/login/"; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 10 -k "$URL" 2>/dev/null || echo "000")
    case "$CODE" in
        200|302) ok "$URL -> $CODE" ;;
        000)     warn "$URL -> javob yo'q" ;;
        *)       bad "$URL -> $CODE" ;;
    esac
done

say "4) Disk va xotira"
DISK=$(df -h "$PROJECT_DIR" | awk 'NR==2{print $5}' | tr -d '%')
if [ "$DISK" -ge 90 ]; then bad "Disk to'lgan: ${DISK}%"; else ok "Disk: ${DISK}% band"; fi
free -h 2>/dev/null | awk 'NR==2{printf "  Xotira: %s / %s ishlatilgan\n", $3, $2}'

say "5) Zaxira nusxalar"
if [ -d backups ]; then
    N=$(find backups -name "*.zip" 2>/dev/null | wc -l)
    OXIRGI=$(find backups -name "*.zip" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    if [ -n "$OXIRGI" ]; then
        KUN=$(( ( $(date +%s) - $(stat -c %Y "$OXIRGI") ) / 86400 ))
        if [ "$KUN" -gt 2 ]; then
            bad "Oxirgi zaxira $KUN kun oldin — server/5-zaxira.sh ishlatiling"
        else
            ok "$N ta zaxira, oxirgisi $KUN kun oldin"
        fi
    else
        bad "Zaxira nusxa yo'q!"
    fi
else
    bad "backups/ papkasi yo'q"
fi

say "6) Oxirgi xatoliklar (jurnal)"
if command -v journalctl >/dev/null; then
    N=$(journalctl -u edumed-his --since "24 hours ago" -p err --no-pager 2>/dev/null | grep -c . || echo 0)
    if [ "$N" -gt 1 ]; then
        warn "Oxirgi 24 soatda $N ta xato satri:"
        journalctl -u edumed-his --since "24 hours ago" -p err --no-pager 2>/dev/null | tail -5 | sed 's/^/      /'
    else
        ok "Xatolik yo'q"
    fi
fi

echo
if [ "$XATO" -eq 0 ]; then
    echo -e "\033[1;32m  ══ HAMMASI JOYIDA ══\033[0m"
else
    echo -e "\033[1;31m  ══ $XATO ta MUAMMO topildi (yuqoriga qarang) ══\033[0m"
fi
echo
exit "$XATO"
