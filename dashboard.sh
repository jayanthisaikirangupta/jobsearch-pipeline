#!/usr/bin/env bash
# Launch the local jobsearch dashboard.
#   bash dashboard.sh             # default port 8000
#   bash dashboard.sh --port 9000 # custom port
#
# Opens http://localhost:8000 in your default browser, then runs the FastAPI
# server in the foreground. Ctrl-C to stop.

set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python}"
HOST="127.0.0.1"
PORT="8000"

# Naive flag parsing — passes everything else through to the CLI command.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    *) break ;;
  esac
done

# Pre-flight checks
if [[ ! -f .env ]]; then
  echo "  .env missing. Copy .env.example and fill it in."
  exit 1
fi
if ! "$PYTHON" -c "import jobsearch.dashboard.app" 2>/dev/null; then
  echo "  Dashboard deps missing. Run:"
  echo "    pip install -e \".[dashboard]\""
  exit 1
fi

URL="http://$HOST:$PORT"
echo "==> Dashboard starting at $URL"

# Best-effort browser open (Windows / mac / Linux). Non-blocking.
(
  sleep 1.2
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) cmd //c start "" "$URL" ;;
    Darwin)               open "$URL" ;;
    *)                    xdg-open "$URL" >/dev/null 2>&1 || true ;;
  esac
) &

exec "$PYTHON" -m jobsearch.cli dashboard --host "$HOST" --port "$PORT" "$@"
