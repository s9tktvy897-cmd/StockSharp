"""Pre-registered research protocol. Fixed BEFORE any result of the research runner was seen
(see the git history of this file and docs/RESEARCH_PROTOCOL.md); changing a threshold after
seeing results is data snooping and must be reported as a protocol change.

Periods
- Development: data start .. HOLDOUT_START - embargo. Rule strategies are scored on all of it
  (after the feature warm-up); fitted models walk forward by calendar year (train < Y-1, choose and
  calibrate on Y-1, test once on Y).
- Final holdout: HOLDOUT_START .. end of data. Not used for any choice; evaluated once, at the end,
  for every strategy with the same rules.

Status (one per strategy variant)
- REJECTED: fails any development criterion other than the multiple-testing one.
- RESEARCH ONLY: passes the development criteria before correction, but not after the Holm
  correction over all variants, or fails the holdout.
- PAPER TRADING CANDIDATE: passes every development criterion after correction AND the holdout.
- PAPER TRADING VALIDATED: a candidate whose live paper ledger has >= MIN_PAPER_TRADES closed trades
  over >= MIN_PAPER_MONTHS months with a mean net return whose 95% interval lies above zero."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

HOLDOUT_START = date(2025, 10, 1)     # the last ~12 months of the data
EMBARGO_DAYS = 30                     # calendar days dropped before the holdout (longest horizon 20 trading days)
WARMUP_DAYS = 260                     # trading days of history before a stock-day can be scored (12-1 momentum)
CAPITAL = 1_000_000.0
TOP_N = 10
SEED = 20261010

# Development criteria
MIN_TRADES = 200
MIN_EDGE_PER_TRADE = 0.0010           # +0.10% net per trade at base costs
ALPHA = 0.05                          # one-sided, Holm-Bonferroni over all variants
BOOTSTRAP_BLOCK = 20                  # days (stationary bootstrap of daily portfolio returns)
BOOTSTRAP_REPS = 2000
MAX_DRAWDOWN = -0.25
COST_STRESS = (1.0, 2.0, 3.0)         # 2x must still have a positive mean daily return
MIN_POSITIVE_YEAR_SHARE = 0.60        # share of calendar years with a positive mean daily return
# Holdout: mean daily return > 0, mean net per trade > 0, max drawdown >= MAX_DRAWDOWN, 2x costs > 0

# Paper trading
MIN_PAPER_TRADES = 100
MIN_PAPER_MONTHS = 3

STATUSES = ("REJECTED", "RESEARCH ONLY", "PAPER TRADING CANDIDATE", "PAPER TRADING VALIDATED")


@dataclass(frozen=True)
class Variant:
    strategy: str
    horizon: int
    target: float | None = None   # +target limit exit (only the existing +10% strategy)

    @property
    def name(self) -> str:
        return f"{self.strategy} {self.horizon}d"


# Every variant tested counts as a trial in the Holm correction and the deflated Sharpe ratio.
GRID = (
    [Variant("MOMENTUM_12_1", h) for h in (5, 10, 20)]
    + [Variant("REVERSAL_5D", h) for h in (1, 2, 5)]
    + [Variant("BREAKOUT_VOLUME", h) for h in (1, 2, 5)]
    + [Variant("TREND_60D", h) for h in (10, 20)]
    + [Variant("EARNINGS_DRIFT", h) for h in (5, 10, 20)]
    + [Variant("VOL_COMPRESSION_BREAKOUT", h) for h in (2, 5, 10)]
    + [Variant("EXISTING_TARGET10", h, target=0.10) for h in (1, 2)]
    + [Variant("MODEL_A_DIRECTION", h) for h in (1, 2, 5, 10, 20)]
    + [Variant("MODEL_B_EXPECTED_RETURN", h) for h in (1, 2, 5, 10, 20)]
    + [Variant("MODEL_C_RISK_ADJUSTED", h) for h in (1, 2, 5, 10, 20)]
)
BENCHMARKS = ("RANDOM", "EQUAL_WEIGHT_UNIVERSE", "SPY_BUY_AND_HOLD")


def development_status(c: dict) -> tuple[bool, bool, list[str]]:
    """(passes before correction, passes after correction, failed criteria) from a criteria dict."""
    fails = [k for k in ("min_trades", "min_edge", "beats_spy_sharpe", "max_drawdown", "cost_stress_2x",
                         "positive_years", "both_regimes", "not_extreme_driven") if not c.get(k)]
    before = not fails and bool(c.get("significant_unadjusted"))
    after = before and bool(c.get("significant_holm"))
    if not c.get("significant_unadjusted"):
        fails.append("significant_unadjusted")
    elif not c.get("significant_holm"):
        fails.append("significant_holm")
    return before, after, fails


def status(c: dict, holdout_ok: bool | None, paper_ok: bool = False) -> str:
    before, after, _ = development_status(c)
    if not before:
        return "REJECTED"
    if not after or not holdout_ok:
        return "RESEARCH ONLY"
    return "PAPER TRADING VALIDATED" if paper_ok else "PAPER TRADING CANDIDATE"
