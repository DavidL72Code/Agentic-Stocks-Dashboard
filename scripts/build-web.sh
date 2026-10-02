#!/bin/sh
# Vercel build step for the static frontend.
#
# One job: substitute the __BUILD__ placeholder in index.html, which FastAPI
# does at serve time and a static host cannot. Without this the page ships
# "app.js?v=__BUILD__" literally - harmless, but it pins every visitor to one
# cache entry forever, so a deploy would not reach anyone who had loaded the
# app before.
#
# Vercel sets VERCEL_GIT_COMMIT_SHA; falls back to a timestamp elsewhere.
set -eu

STAMP="${VERCEL_GIT_COMMIT_SHA:-$(date +%s)}"
STAMP=$(printf '%s' "$STAMP" | cut -c1-12)

cd "$(dirname "$0")/.."

if ! grep -q '__BUILD__' web/index.html; then
  echo "build-web: no __BUILD__ placeholder in web/index.html - nothing to do"
  exit 0
fi

# portable in-place edit: BSD and GNU sed disagree about -i
tmp=$(mktemp)
sed "s/__BUILD__/${STAMP}/g" web/index.html > "$tmp"
mv "$tmp" web/index.html

echo "build-web: stamped assets with ${STAMP}"
grep -o 'app\.js?v=[^"]*' web/index.html || true
