#!/bin/bash
# Prepares the equity-research Python project in Claude Code cloud sessions.
# Anything printed here is added to the session context. Never fails the session start.
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT="$CLAUDE_PROJECT_DIR/equity-research"
[ -d "$PROJECT" ] || exit 0

if python3 -m pip install --quiet --disable-pip-version-check --root-user-action=ignore -e "$PROJECT[dev]" >/dev/null 2>&1; then
  echo "equity-research: Python package installed (commands: equity-research analyze TICKER, equity-research shortterm scan|catalysts|evaluate; tests: cd equity-research && python -m pytest -q)."
else
  echo "equity-research: pip install FAILED -- run: python3 -m pip install -e 'equity-research[dev]' and report the error to the user."
fi

check() {
  local code
  # 000 = no connection (the environment's network policy blocks the host); any HTTP status means reachable.
  code=$(curl -s -o /dev/null -m 5 -w "%{http_code}" "$1" 2>/dev/null || true)
  [ "${code:-000}" = "000" ] && echo "BLOCKED" || echo "ok"
}

echo "equity-research: network -> data.sec.gov $(check https://data.sec.gov/), www.sec.gov $(check https://www.sec.gov/files/company_tickers.json), fred.stlouisfed.org $(check https://fred.stlouisfed.org/), stooq.com $(check https://stooq.com/), pages.stern.nyu.edu $(check https://pages.stern.nyu.edu/~adamodar/)"
if [ -z "${EQUITY_RESEARCH_USER_AGENT:-}" ]; then
  echo "equity-research: EQUITY_RESEARCH_USER_AGENT is NOT set -- live SEC requests will fail; tell the user to add it to the environment variables."
fi
echo "equity-research: for stock analysis follow equity-research/CLAUDE.md (Dutch chat, fixed method, sources, web context with links, no invented numbers); a BLOCKED source is reported, never filled in."
exit 0
