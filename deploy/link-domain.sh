#!/usr/bin/env bash
# One-time: make https://indev.eko.in/apply (and /dashboard) reach the app in this folder.
#
#   sudo bash /home/shiwangi/ESAF-Onboarding/deploy/link-domain.sh
#
# Adds ONE line to the indev.eko.in nginx config:
#   include <this folder>/deploy/indev-locations.conf;
# All routing lives in that file in the project. A backup of the nginx config is kept in
# <project>/backups/. If nginx rejects the change, the original is restored automatically.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo: sudo bash $0" >&2; exit 1; }

PROJECT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
ROUTES="$PROJECT/deploy/indev-locations.conf"
INCLUDE="include $ROUTES;"

echo "1) Is the app running on port 5055?"
curl -s -m 5 -o /dev/null -w "   app answered: %{http_code}\n" http://127.0.0.1:5055/apply \
  || { echo "   No. Start it as shiwangi first: PORT=5055 nohup venv/bin/python webform/app.py > ~/csp-app.log 2>&1 &"; exit 1; }

FILE=$(grep -rlsE "server_name[^;]*indev\.eko\.in" /etc/nginx/sites-enabled /etc/nginx/conf.d /etc/nginx/nginx.conf | head -1 || true)
[ -n "$FILE" ] || { echo "No nginx config for indev.eko.in found." >&2; exit 1; }
FILE=$(readlink -f "$FILE")
echo "2) nginx config: $FILE"

if grep -qF "$INCLUDE" "$FILE"; then
  echo "   already linked"
else
  mkdir -p "$PROJECT/backups"
  BACKUP="$PROJECT/backups/nginx-indev-$(date +%F-%H%M%S).conf"
  cp "$FILE" "$BACKUP"
  chmod 600 "$BACKUP"
  echo "3) Backup: $BACKUP"
  awk -v inc="    $INCLUDE   # ESAF CSP onboarding app" '
    { print }
    /server_name[^;]*indev\.eko\.in[^;]*;/ { print inc }
  ' "$BACKUP" > "$FILE"
fi

echo "4) Testing nginx config"
if nginx -t; then
  systemctl reload nginx
  sleep 1
  curl -s -o /dev/null -w "5) https://indev.eko.in/apply -> %{http_code}\n" https://indev.eko.in/apply
else
  [ -n "${BACKUP:-}" ] && cp "$BACKUP" "$FILE"
  echo "!! nginx rejected the change; original config restored, live site untouched." >&2
  exit 1
fi
