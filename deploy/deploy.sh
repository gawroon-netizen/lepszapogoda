#!/usr/bin/env bash
# Deploy on mydevil (SPEC §7.4). Run on the host:  bash ~/domains/lepszapogoda.pl/app/deploy/deploy.sh
# Touches only ~/domains/lepszapogoda.pl (the account hosts other sites).
set -euo pipefail

DOMAIN=lepszapogoda.pl
BASE="$HOME/domains/$DOMAIN"
APP="$BASE/app"
VENV="$BASE/venv"
PUB="$BASE/public_python"

cd "$APP"
git fetch -q origin main
git reset -q --hard origin/main   # the host copy is never edited by hand
echo "code: $(git log --oneline -1)"

[ -d "$VENV" ] || python3.11 -m venv "$VENV"
nice -n 10 "$VENV/bin/pip" install -q -r requirements-web.txt
nice -n 10 "$VENV/bin/pip" install -q -e . --no-deps

# Passenger entry point and static files served directly by nginx (public/ bypasses Python)
ln -sfn "$APP/web/passenger_wsgi.py" "$PUB/passenger_wsgi.py"
mkdir -p "$PUB/public"
ln -sfn "$APP/web/app/static" "$PUB/public/static"
if [ -f "$PUB/public/index.html" ]; then
  # mydevil's placeholder page would shadow the application's "/"
  mv "$PUB/public/index.html" "$BASE/mydevil-placeholder-index.html"
fi
mkdir -p "$APP/web/data" "$APP/web/var/cache" "$APP/web/var/log"

devil www restart "$DOMAIN" >/dev/null
sleep 3
for scheme in https http; do  # https only once the domain has a certificate
  code=$(curl -s -o /dev/null -w "%{http_code}" "$scheme://$DOMAIN/healthz" || true)
  echo "healthz ($scheme): $code"
  [ "$code" = "200" ] && exit 0
done
exit 1
