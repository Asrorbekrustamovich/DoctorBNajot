#!/usr/bin/env bash
#  TEKSHIRISH — server holati bir qarashda.
#      bash server/4-tekshirish.sh
set -uo pipefail
APP_DIR="${APP_DIR:-/opt/edumed-his}"
cd "$APP_DIR"
source .venv/bin/activate
echo "== Xizmatlar =="
systemctl is-active edumed-his  | sed 's/^/  edumed-his: /'
systemctl is-active nginx       | sed 's/^/  nginx:      /'
echo
python manage.py deploy_check
echo
echo "== Oxirgi xatolar =="
journalctl -u edumed-his -p err -n 15 --no-pager 2>/dev/null || true
