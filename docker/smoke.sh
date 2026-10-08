# BaseFit deployment smoke check (PLAN.md §2 remote QA).
#
# Exercises the deployed single-origin artifact through the normal public
# API only: health, SPA serving, register/login (real browser-equivalent
# mutations with the Origin header), and an authenticated catalog read.
# No database access, no reset endpoints.
#
# Disposable test instances may use the default throwaway account. Against a
# production origin, set SMOKE_EMAIL/SMOKE_PASSWORD to one clearly named
# reusable synthetic account; its registration conflict is tolerated and its
# resources are cleaned up through normal owner-scoped behavior only.
#
# Usage: docker/smoke.sh <origin>   # e.g. docker/smoke.sh http://127.0.0.1:8080
set -eu

ORIGIN="${1:?usage: docker/smoke.sh <origin>}"
# POSIX-safe throwaway identity (no $RANDOM under /bin/sh); production smoke
# runs must set both variables to the reusable synthetic account.
SMOKE_ID="$$-$(date -u +%Y%m%dT%H%M%SZ)"
SMOKE_EMAIL="${SMOKE_EMAIL:-smoke-$SMOKE_ID@basefit.invalid}"
SMOKE_PASSWORD="${SMOKE_PASSWORD:-smoke-$SMOKE_ID-password}"

echo "smoke: origin=$ORIGIN email=$SMOKE_EMAIL"

echo "smoke: health"
curl -fsS "$ORIGIN/api/v1/health" | grep -q '"status":"ok"'

echo "smoke: SPA index served on the same origin"
curl -fsS "$ORIGIN/" | grep -q 'id="app"'
curl -fsS "$ORIGIN/" | grep -q 'basefit.theme'

echo "smoke: register (tolerating an existing synthetic account)"
register_status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$ORIGIN/api/v1/auth/register" \
  -H "Origin: $ORIGIN" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$SMOKE_EMAIL\",\"password\":\"$SMOKE_PASSWORD\"}")
if [ "$register_status" != "201" ] && [ "$register_status" != "409" ]; then
  echo "smoke: FAIL register returned $register_status" >&2
  exit 1
fi

echo "smoke: login"
cookies=$(mktemp)
trap 'rm -f "$cookies"' EXIT
login_status=$(curl -s -o /dev/null -w '%{http_code}' -c "$cookies" -X POST "$ORIGIN/api/v1/auth/login" \
  -H "Origin: $ORIGIN" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$SMOKE_EMAIL\",\"password\":\"$SMOKE_PASSWORD\"}")
if [ "$login_status" != "200" ]; then
  echo "smoke: FAIL login returned $login_status" >&2
  exit 1
fi

echo "smoke: authenticated read"
curl -fsS -b "$cookies" "$ORIGIN/api/v1/exercises?page=1&pageSize=1" | grep -q '"total":'

echo "smoke: wrong-origin mutation is rejected (CSRF)"
csrf_status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$ORIGIN/api/v1/auth/logout" \
  -H 'Origin: http://evil.example' -H 'Content-Type: application/json' -b "$cookies")
if [ "$csrf_status" != "403" ]; then
  echo "smoke: FAIL expected 403 for a foreign Origin, got $csrf_status" >&2
  exit 1
fi

echo "smoke: OK"
