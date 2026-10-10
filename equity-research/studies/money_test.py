"""Money test: EUR 10,000 following fixed rules, chosen with data before the test period only.
Test period: 2025-10-01 .. end of data (never used to choose anything). Entry at the open; the opening
gap is known just after the open. Each trade gets 20% of equity (1% risk at a 5% stop), at most 3 trades
per day, all costs included; daily bars, a stop and a target in the same bar count as the stop."""
import sys, json
from datetime import date
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from equity_research.research import experiment, stats
from equity_research.research.__main__ import load_inputs
from equity_research.research.execution import CostModel

START = date(2025, 10, 1)
inputs = load_inputs(Path(sys.argv[1]), 0, True)
split_like = lambda problems: all("possible unadjusted split" in x for x in problems)
inputs.excluded = {t: pr for t, pr in inputs.excluded.items() if not split_like(pr)}
p = experiment.prepare(inputs)
panel = p.panel
cost = np.array([CostModel().per_side(0.0, float(dv), 0.0, float(pr)) for dv, pr in zip(panel.dollar_volume, panel.price)])


def exits(b, i, h, target, stop):
    e = b.open[i + 1]
    up, down = e * (1 + target), (e * (1 - stop) if stop else None)
    for k in range(1, h + 1):
        j = i + k
        if k > 1 and down is not None and b.open[j] <= down:
            return b.open[j] / e - 1
        if k > 1 and b.open[j] >= up:
            return b.open[j] / e - 1
        if down is not None and b.low[j] <= down:
            return -stop
        if b.high[j] >= up:
            return target
    return b.close[i + h] / e - 1


STRATEGIES = {
    "A. Ochtendscanner: zeer liquide (> $250 mln/dag), +5% limiet, -5% stop, slot": dict(h=1, target=0.05, stop=0.05,
        pick=lambda gap, dv: dv > 250e6),
    "B. Rebound na gap < -10%, +10% limiet of slot na 2 dagen": dict(h=2, target=0.10, stop=None,
        pick=lambda gap, dv: gap < -0.10),
    "C. Gap-ups najagen (> +10%), +5% limiet, -5% stop, slot": dict(h=1, target=0.05, stop=0.05,
        pick=lambda gap, dv: gap > 0.10),
}
rows = np.where(p.usable & (p.ordinals >= START.toordinal()))[0]
gap = np.full(len(panel.dates), np.nan)
for r in rows:
    b = p.market.bars[panel.tickers[r]]
    i = panel.rows[r]
    if i + 1 < len(b):
        gap[r] = b.open[i + 1] / b.close[i] - 1
days = sorted({panel.dates[r] for r in rows})
by_day = {}
for r in rows:
    by_day.setdefault(panel.dates[r], []).append(r)

out = {}
for name, s in STRATEGIES.items():
    equity, curve, trades, months = 10_000.0, [], [], {}
    for d in days:
        cands = [r for r in by_day.get(d, []) if np.isfinite(gap[r]) and s["pick"](gap[r], panel.dollar_volume[r])]
        cands = sorted(cands, key=lambda r: -panel.dollar_volume[r])[:3]
        pnl = 0.0
        for r in cands:
            b = p.market.bars[panel.tickers[r]]
            i = panel.rows[r]
            if i + s["h"] >= len(b):
                continue
            g = exits(b, i, s["h"], s["target"], s["stop"])
            net = (1 + g) * (1 - cost[r]) / (1 + cost[r]) - 1
            pnl += 0.20 * equity * net
            trades.append(net)
        equity += pnl
        curve.append(equity)
        months[d.strftime("%Y-%m")] = equity
    rets = np.diff(np.concatenate([[10_000.0], curve])) / np.concatenate([[10_000.0], curve[:-1]])
    t = np.array(trades)
    out[name] = {"start": 10_000.0, "end": equity, "total_return": equity / 10_000 - 1, "trades": len(t),
                 "win_rate": float(np.mean(t > 0)) if len(t) else None, "mean_per_trade": float(t.mean()) if len(t) else None,
                 "share_trades_ge_5pct": float(np.mean(t >= 0.045)) if len(t) else None,
                 "max_drawdown": stats.max_drawdown(rets), "months": months}
    print(f"{name}: EUR 10,000 -> {equity:,.0f} ({equity/10_000-1:+.1%}), trades {len(t)}, win {out[name]['win_rate']}, "
          f"mean/trade {out[name]['mean_per_trade']}, maxDD {out[name]['max_drawdown']:.1%}", flush=True)
spy = inputs.spy
idx = [i for i, d in enumerate(spy.dates) if d >= START]
first, last = idx[0], idx[-1]
spy_end = 10_000 * spy.close[last] / spy.open[first] * (1 - 0.0015) / (1 + 0.0015)
spy_rets = spy.close[idx[1:]] / spy.close[idx[:-1]] - 1
out["D. SPY kopen en vasthouden"] = {"start": 10_000.0, "end": float(spy_end), "total_return": float(spy_end / 10_000 - 1),
                                     "trades": 1, "max_drawdown": stats.max_drawdown(spy_rets),
                                     "months": {spy.dates[i].strftime("%Y-%m"): float(10_000 * spy.close[i] / spy.open[first]) for i in idx}}
print(f"D. SPY: EUR 10,000 -> {spy_end:,.0f} ({spy_end/10_000-1:+.1%})", flush=True)
json.dump(out, open(sys.argv[2], "w"), indent=1, default=float)
print("period", days[0], days[-1], flush=True)
