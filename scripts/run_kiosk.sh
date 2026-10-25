#!/usr/bin/env bash
# Abre a página da IARA no Chrome/Chromium em modo quiosque (Linux).
# Uso: scripts/run_kiosk.sh [http://localhost:8000]
set -euo pipefail
URL="${1:-http://localhost:8000}"
CHROME="$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)"
[ -n "$CHROME" ] || { echo "Chrome/Chromium não encontrado" >&2; exit 1; }

for _ in $(seq 60); do curl -fs "$URL/healthz" >/dev/null && break; sleep 1; done

exec "$CHROME" \
  --kiosk \
  --user-data-dir="$HOME/.config/iara-chrome-profile" \
  --autoplay-policy=no-user-gesture-required \
  --no-first-run \
  "$URL"
