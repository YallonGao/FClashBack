#!/usr/bin/env bash
# Start FClashBack locally. Listens on 127.0.0.1:8780, data under ./data.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8780}"

if [ ! -d .venv ]; then
  echo "creating .venv"
  python3 -m venv .venv
fi

./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -r requirements.txt
if [ -f requirements-dev.txt ]; then
  ./.venv/bin/python -m pip install --quiet -r requirements-dev.txt
fi

mkdir -p data
if [ -z "${FCLASH_JWT_SECRET:-}" ]; then
  # A fresh secret per start would sign every device out on restart.
  if [ ! -f data/dev-secret.txt ]; then
    ./.venv/bin/python - <<'PY' > data/dev-secret.txt
import secrets
print(secrets.token_urlsafe(48), end="")
PY
  fi
  FCLASH_JWT_SECRET="$(cat data/dev-secret.txt)"
  export FCLASH_JWT_SECRET
fi

export FCLASH_DATA_DIR="${FCLASH_DATA_DIR:-$PWD/data}"

FRONTEND="$(cd .. && pwd)/FClashFront/dist"
if [ -z "${FCLASH_FRONTEND_DIR:-}" ] && [ -f "$FRONTEND/index.html" ]; then
  export FCLASH_FRONTEND_DIR="$FRONTEND"
fi

echo
echo "  API      http://127.0.0.1:${PORT}/docs"
if [ -n "${FCLASH_FRONTEND_DIR:-}" ]; then
  echo "  Console  http://127.0.0.1:${PORT}/"
else
  echo "  Console  not built; run FClashFront/start.sh"
fi
echo "  Data     ${FCLASH_DATA_DIR}"
echo

exec ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" "$@"
