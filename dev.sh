#!/usr/bin/env bash
# Run the full web app locally: FastAPI backend + Next.js frontend.
#
#   ./dev.sh
#
# Ports default to 8008 (backend) and 3000 (frontend). If either is already in
# use, the next free port is picked automatically and the frontend proxy is
# pointed at whatever backend port we landed on.
#
# Override the starting ports with env vars:
#   BACKEND_PORT=9000 FRONTEND_PORT=4000 ./dev.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Return the first free TCP port at or above the given starting port.
find_free_port() {
  local port="$1"
  while lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; do
    port=$((port + 1))
    if [[ "$port" -gt 65535 ]]; then
      echo "No free port found" >&2
      exit 1
    fi
  done
  printf '%s' "$port"
}

BACKEND_PORT="$(find_free_port "${BACKEND_PORT:-8008}")"
FRONTEND_PORT="$(find_free_port "${FRONTEND_PORT:-3000}")"

# The Next.js dev proxy reads this to forward /api to the backend.
export BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"

cleanup() {
  trap - INT TERM EXIT
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "Starting FastAPI backend on :${BACKEND_PORT} ..."
./run.sh serve --reload --port "$BACKEND_PORT" &
BACKEND_PID=$!

if [[ ! -d frontend/node_modules ]]; then
  echo "Installing frontend deps ..."
  (cd frontend && npm install)
fi

# A leftover production build (`next build`) in .next corrupts `next dev`
# ("Cannot find module './NNN.js'"). Drop it before starting the dev server.
if [[ -f frontend/.next/BUILD_ID ]]; then
  echo "Removing stale production build in frontend/.next ..."
  rm -rf frontend/.next
fi

echo "Starting Next.js frontend on :${FRONTEND_PORT} ..."
(cd frontend && npm run dev -- -p "$FRONTEND_PORT") &
FRONTEND_PID=$!

echo ""
echo "Backend  -> ${BACKEND_URL}"
echo "Frontend -> http://localhost:${FRONTEND_PORT}   <- open this"
wait
