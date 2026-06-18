#!/usr/bin/env bash
# Run the full web app locally: FastAPI backend + Next.js frontend.
#
#   ./dev.sh
#
# Backend -> http://localhost:8008   (API)
# Frontend -> http://localhost:3000  (open this in the browser)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

cleanup() {
  trap - INT TERM EXIT
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "Starting FastAPI backend on :8008 ..."
./run.sh serve --port 8008 &
BACKEND_PID=$!

if [[ ! -d frontend/node_modules ]]; then
  echo "Installing frontend deps ..."
  (cd frontend && npm install)
fi

echo "Starting Next.js frontend on :3000 ..."
(cd frontend && npm run dev) &
FRONTEND_PID=$!

echo ""
echo "Open http://localhost:3000"
wait
