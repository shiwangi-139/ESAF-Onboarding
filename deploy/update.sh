#!/usr/bin/env bash
# Update the server to the latest code on GitHub and restart the app.
#
#   sudo /srv/csp-onboarding/app/deploy/update.sh
#
# Steps: pull main -> install Python packages -> run database migrations -> restart -> health check.
# If the app doesn't come back up, the script prints the log and the command to roll back.
set -euo pipefail

APP=/srv/csp-onboarding/app
VENV=/srv/csp-onboarding/venv
SERVICE=csp-onboarding
BRANCH=main
GIT=(git -C "$APP" -c safe.directory="$APP")

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

if [ -n "$("${GIT[@]}" status --porcelain --untracked-files=no)" ]; then
  echo "Files under $APP were edited on the server. Make changes on the laptop and push them instead." >&2
  "${GIT[@]}" status --short --untracked-files=no >&2
  exit 1
fi

OLD=$("${GIT[@]}" rev-parse HEAD)
echo "==> Pulling latest code ($BRANCH)"
"${GIT[@]}" fetch --quiet origin "$BRANCH"
"${GIT[@]}" merge --ff-only --quiet "origin/$BRANCH"
NEW=$("${GIT[@]}" rev-parse HEAD)

if [ "$OLD" = "$NEW" ]; then
  echo "Already up to date ($(git -C "$APP" -c safe.directory="$APP" log -1 --format='%h %s'))."
else
  echo "Updated: ${OLD:0:7} -> ${NEW:0:7}"
  "${GIT[@]}" log --oneline "$OLD..$NEW"
fi

echo "==> Installing Python packages"
"$VENV/bin/pip" install --quiet -r "$APP/requirements.txt"

chown -R csp:csp "$APP"
chmod 600 "$APP/.env"

echo "==> Running database migrations"
sudo -u csp "$VENV/bin/python" "$APP/manage.py" migrate

echo "==> Restarting $SERVICE"
systemctl restart "$SERVICE"

for _ in $(seq 1 15); do
  if curl -fsS -o /dev/null http://127.0.0.1:8000/auth/login; then
    echo "==> OK: app is running $(git -C "$APP" -c safe.directory="$APP" log -1 --format='%h %s')"
    exit 0
  fi
  sleep 1
done

echo "!! The app did not respond after the restart. Last log lines:" >&2
journalctl -u "$SERVICE" -n 30 --no-pager >&2
echo >&2
echo "To roll back to the previous version:" >&2
echo "  sudo git -C $APP -c safe.directory=$APP reset --hard $OLD && sudo systemctl restart $SERVICE" >&2
exit 1
