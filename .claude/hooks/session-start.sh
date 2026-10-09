#!/bin/bash
# Prepares the equity-research Python project in Claude Code cloud sessions.
# Anything printed here is added to the session context.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT="$CLAUDE_PROJECT_DIR/equity-research"
[ -d "$PROJECT" ] || exit 0

python3 -m pip install --quiet --disable-pip-version-check --root-user-action=ignore -e "$PROJECT[dev]" >/dev/null

check() {
  local code
  # 000 = no connection (the environment's network policy blocks the host); any HTTP status means reachable.
  code=$(curl -s -o /dev/null -m 5 -w "%{http_code}" "$1" 2>/dev/null || true)
  [ "${code:-000}" = "000" ] && echo "BLOCKED" || echo "ok"
}

echo "equity-research: Python package installed (python -m pytest -q in equity-research/)."
echo "equity-research: network -> data.sec.gov $(check https://data.sec.gov/), www.sec.gov $(check https://www.sec.gov/files/company_tickers.json), fred.stlouisfed.org $(check https://fred.stlouisfed.org/)"
if [ -z "${EQUITY_RESEARCH_USER_AGENT:-}" ]; then
  echo "equity-research: EQUITY_RESEARCH_USER_AGENT is NOT set -- live SEC requests will fail; tell the user to add it to the environment variables."
fi
