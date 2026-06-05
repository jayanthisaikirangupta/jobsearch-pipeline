#!/usr/bin/env bash
# One-shot daily run. From the project root:
#   bash run.sh              # full pipeline, top 10, opens jobs.xlsx
#   bash run.sh --top 20     # tailor more
#   bash run.sh --skip-tailor --skip-review   # cheap re-score only
#   bash run.sh --skip-sponsors               # use cached register
#
# Forwards every flag through to `python -m jobsearch.cli pipeline run`.

set -euo pipefail

cd "$(dirname "$0")"

PROFILE="${AWS_PROFILE:-fitai}"
PYTHON="${PYTHON:-python}"

echo
echo "==> Pre-flight checks"

# 1. AWS SSO must be live (Bedrock is needed for tailor + review)
if ! aws sts get-caller-identity --profile "$PROFILE" >/dev/null 2>&1; then
  echo "  AWS SSO session for profile '$PROFILE' is not active."
  echo "  Run:  aws sso login --profile $PROFILE"
  echo "  ...then re-run this script."
  exit 1
fi
echo "  AWS SSO ($PROFILE): ok"

# 2. .env must exist (Bedrock region + model)
if [[ ! -f .env ]]; then
  echo "  .env missing. Copy .env.example and fill it in."
  exit 1
fi
echo "  .env: ok"

# 3. Python package is importable
if ! "$PYTHON" -c "import jobsearch" 2>/dev/null; then
  echo "  jobsearch package not importable. Run the install commands from README."
  exit 1
fi
echo "  package: ok"

echo
echo "==> Running pipeline"
"$PYTHON" -m jobsearch.cli pipeline run "$@"

# Open the refreshed Excel if it exists. Best-effort, won't fail the run.
XLSX="output/jobs.xlsx"
if [[ -f "$XLSX" ]]; then
  echo
  echo "==> Opening $XLSX"
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) cmd //c start "" "$XLSX" ;;
    Darwin)               open "$XLSX" ;;
    *)                    xdg-open "$XLSX" >/dev/null 2>&1 || true ;;
  esac
fi
