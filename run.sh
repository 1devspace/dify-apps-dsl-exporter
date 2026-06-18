#!/usr/bin/env bash
# Convenience runner for the Dify DSL exporter/importer using the local venv.
#
# Usage:
#   ./run.sh export        # export all workflows (default)
#   ./run.sh import        # import all workflows from DSL_FOLDER_PATH
#   ./run.sh import FILE    # import a single workflow file
#   ./run.sh delete [ARGS] # delete workflows
#   ./run.sh sync [ARGS]   # sync the Confluence tracker + notify Slack
#                          #   ARGS: --dry-run, --no-slack
#   ./run.sh prune [ARGS]  # delete workflows marked "Delete" in the tracker + notify Slack
#                          #   ARGS: --yes (required to actually delete), --no-slack
#   ./run.sh tags [ARGS]   # copy env tags (prod/dev/test) from the tracker into Dify
#                          #   ARGS: --dry-run
#   ./run.sh readable [ARGS] # convert DSL workflows into readable Markdown reports
#                          #   ARGS: [files/dirs...] --out DIR
#   ./run.sh serve [ARGS]  # run the FastAPI backend (web app API) with uvicorn
#                          #   ARGS: passed to uvicorn (default: --reload --port 8008)
set -euo pipefail

# Resolve the directory this script lives in, so it works from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="$SCRIPT_DIR/venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "❌ venv not found at $PYTHON. Create it with: python3 -m venv venv && ./venv/bin/pip install httpx python-dotenv" >&2
  exit 1
fi

CMD="${1:-export}"
shift || true

case "$CMD" in
  export|import|delete)
    exec "$PYTHON" "src/${CMD}.py" "$@"
    ;;
  sync)
    exec "$PYTHON" "src/sync_tracker.py" "$@"
    ;;
  prune)
    exec "$PYTHON" "src/prune_deleted.py" "$@"
    ;;
  tags)
    exec "$PYTHON" "src/sync_env_tags.py" "$@"
    ;;
  readable)
    exec "$PYTHON" "src/dsl_readable.py" "$@"
    ;;
  serve)
    if [[ $# -eq 0 ]]; then
      set -- --reload --port 8008
    fi
    exec "$PYTHON" -m uvicorn api.app:app --app-dir src "$@"
    ;;
  *)
    echo "Unknown command: $CMD" >&2
    echo "Usage: ./run.sh [export|import|delete|sync|prune|tags|readable|serve] [args...]" >&2
    exit 1
    ;;
esac
