"""Today's paper-trading signals. Only variants whose latest research status is PAPER TRADING
CANDIDATE (or VALIDATED) are traded on paper; with none, the result is an explicit NO TRADE.
Picks go into the immutable ledger as paper trades (simulated fills on later real data); no order is
ever sent to a broker."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from equity_research import ledger as ledger_mod
from equity_research.research import experiment, protocol, strategies

TRADABLE = ("PAPER TRADING CANDIDATE", "PAPER TRADING VALIDATED")


def candidates(research: dict) -> list[protocol.Variant]:
    by_name = {v.name: v for v in protocol.GRID}
    return [by_name[r["variant"]] for r in research.get("variants", [])
            if r["status"] in TRADABLE and r["variant"] in by_name]


def todays_picks(variant: protocol.Variant, p: experiment.Prepared) -> list[tuple[str, float]]:
    latest = max(p.panel.dates)
    rows = np.where((p.panel.dates == latest) & p.usable)[0]
    if variant.strategy in ("EXISTING_TARGET10", "MODEL_A_DIRECTION", "MODEL_B_EXPECTED_RETURN", "MODEL_C_RISK_ADJUSTED"):
        f = strategies.fitted_scores(variant.strategy, p.panel, variant.horizon, p.labels[variant.horizon], p.usable,
                                     p.vol20, latest, latest)  # trained on everything known today
        scores = f.holdout
    else:
        spy_up = np.array([p.spy_up.get(d, False) for d in p.panel.dates])
        scores = strategies.rule_score(variant.strategy, p.panel, spy_up, p.dollar_volume)
    ok = rows[np.isfinite(scores[rows])]
    best = ok[np.argsort(-scores[ok], kind="stable")][:protocol.TOP_N]
    return [(p.panel.tickers[r], float(scores[r])) for r in best]


def log_paper_trades(research: dict, p: experiment.Prepared, book: ledger_mod.Ledger, code: str, now: datetime,
                     security_ids: dict[str, str]) -> dict[str, int]:
    out = {}
    latest = max(p.panel.dates)
    for variant in candidates(research):
        n = 0
        for ticker, score in todays_picks(variant, p):
            try:
                book.add(ledger_mod.Prediction(
                    ticker=ticker, security_id=security_ids.get(ticker, ""), strategy=variant.strategy,
                    horizon=variant.horizon, model_version=code, dataset_version=f"bars up to {latest}",
                    signal_date=latest, direction="long", expected_return=None, probabilities={"score": score},
                    expected_cost_per_side=None, paper_trade=True, strategy_status="PAPER TRADING CANDIDATE"), now)
                n += 1
            except ValueError:
                pass
        out[variant.name] = n
    return out
