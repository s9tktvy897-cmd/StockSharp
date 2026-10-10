"""How long must a position be held before the average result after costs reaches +5%, and how likely
is a loss then? Entry at the open after the signal day, exit at the close h trading days later, base costs
per side. Groups: every eligible stock-day (= random selection), the 10 highest 12-1 momentum stocks per day,
the 10 highest earnings-drift signals, and SPY. Development period only (holdout reported separately)."""
import sys, json
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from equity_research.research import experiment, protocol, strategies
from equity_research.research.__main__ import load_inputs
from equity_research.research.execution import CostModel
from equity_research.shortterm.evaluation import daily_top

HORIZONS = (1, 5, 20, 60, 120, 250)
inputs = load_inputs(Path(sys.argv[1]), 0, True)
p = experiment.prepare(inputs)
panel = p.panel
n = len(panel.dates)
cost = np.array([CostModel().per_side(0.0, float(dv), 0.0, float(pr)) for dv, pr in zip(panel.dollar_volume, panel.price)])
net = {h: np.full(n, np.nan) for h in HORIZONS}
order = np.argsort(panel.tickers, kind="stable")
ts = panel.tickers[order]
for grp in np.split(order, np.flatnonzero(ts[1:] != ts[:-1]) + 1):
    b = p.market.bars[panel.tickers[grp[0]]]
    rows = panel.rows[grp]
    for h in HORIZONS:
        ok = rows + h < len(b)
        g = b.close[rows[ok] + h] / b.open[rows[ok] + 1] - 1
        net[h][grp[ok]] = (1 + g) * (1 - cost[grp[ok]]) / (1 + cost[grp[ok]]) - 1
print("outcomes ready", flush=True)
dev = p.usable & (p.ordinals <= p.dev_end.toordinal())
hold = p.usable & (p.ordinals >= p.holdout_start.toordinal())
spy_up = np.array([p.spy_up.get(d, False) for d in panel.dates])
groups = {"all eligible stock-days (random)": None,
          "momentum 12-1 top 10 per day": strategies.rule_score("MOMENTUM_12_1", panel, spy_up, p.dollar_volume),
          "earnings drift top 10 per day": strategies.rule_score("EARNINGS_DRIFT", panel, spy_up, p.dollar_volume)}


def describe(x):
    x = x[np.isfinite(x)]
    if not len(x):
        return {"n": 0}
    return {"n": int(len(x)), "mean": float(x.mean()), "median": float(np.median(x)), "p_ge_5": float(np.mean(x >= 0.05)),
            "p_le_minus5": float(np.mean(x <= -0.05)), "p_loss": float(np.mean(x < 0)),
            "p10": float(np.percentile(x, 10)), "p90": float(np.percentile(x, 90))}


out = {}
for name, score in groups.items():
    for period, mask in (("development", dev), ("holdout", hold)):
        rows = np.where(mask)[0] if score is None else daily_top(score, panel.dates, mask & np.isfinite(score), 10)
        out[f"{name} | {period}"] = {h: describe(net[h][rows]) for h in HORIZONS}
        print(name, period, {h: round(out[f'{name} | {period}'][h].get('mean', float('nan')), 4) for h in HORIZONS}, flush=True)
spy = inputs.spy
for period, (lo, hi) in (("development", (None, p.dev_end)), ("holdout", (p.holdout_start, None))):
    res = {}
    idx = [i for i, d in enumerate(spy.dates) if (lo is None or d >= lo) and (hi is None or d <= hi)]
    for h in HORIZONS:
        r = [spy.close[i + h] / spy.open[i + 1] * (1 - 0.0015) / (1 + 0.0015) - 1 for i in idx if i + h < len(spy)]
        res[h] = describe(np.array(r))
    out[f"SPY | {period}"] = res
json.dump(out, open(sys.argv[2], "w"), indent=1)
print("written", flush=True)
