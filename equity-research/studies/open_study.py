"""Exploratory study: when does a stock keep rising AFTER the open? Development data only (signal
dates up to the development end); the holdout is shown separately as a second look. Entry at the
open of the next day (or just after it, knowing the opening gap); exits: +target limit, optional
stop (stop first when both in one bar, gaps fill at the open), else the close of day h.
Every cell x rule is a trial in a Holm correction. Exploratory: no strategy status changes."""
import sys, json
from datetime import date
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from equity_research.research import experiment, protocol, stats
from equity_research.research.__main__ import load_inputs
from equity_research.research.execution import CostModel

out_path = Path(sys.argv[2])
inputs = load_inputs(Path(sys.argv[1]), 0, True)
# Only real data errors are excluded here: a large genuine jump (e.g. +100%) is exactly what this study is about.
split_like = lambda problems: all("possible unadjusted split" in x for x in problems)
inputs.excluded = {t: pr for t, pr in inputs.excluded.items() if not split_like(pr)}
print("excluded (structural errors only)", len(inputs.excluded), flush=True)
p = experiment.prepare(inputs)
panel = p.panel
n = len(panel.dates)
print("rows", n, flush=True)

RULES = [(h, t, s) for h in (1, 2) for t in (0.05, 0.07, 0.10) for s in (None, 0.05)]


def exits(b, rows, h, target, stop):
    """Gross return per signal row (entry open of row+1) for one ticker."""
    o, hi, lo, c = b.open, b.high, b.low, b.close
    ok = rows + h < len(o)
    r = np.full(len(rows), np.nan)
    i = rows[ok]
    e = o[i + 1]
    tgt, stp = e * (1 + target), (e * (1 - stop) if stop else None)
    px = np.full(len(i), np.nan)
    done = np.zeros(len(i), bool)
    for k in range(1, h + 1):
        j = i + k
        if k > 1:
            if stp is not None:
                g = ~done & (o[j] <= stp)
                px[g], done = o[j][g], done | g
            g = ~done & (o[j] >= tgt)
            px[g], done = o[j][g], done | g
        if stp is not None:
            g = ~done & (lo[j] <= stp)
            px[g], done = stp[g], done | g
        g = ~done & (hi[j] >= tgt)
        px[g], done = tgt[g], done | g
    rest = ~done
    px[rest] = c[i + h][rest]
    r[ok] = px / e - 1
    return r


# per-row gross returns for every rule, plus open->high, open->close, open->low for day 1
gross = {rule: np.full(n, np.nan) for rule in RULES}
up1 = np.full(n, np.nan); oc1 = np.full(n, np.nan); dn1 = np.full(n, np.nan); gap_next = np.full(n, np.nan)
order = np.argsort(panel.tickers, kind="stable")
tick_sorted = panel.tickers[order]
bounds = np.flatnonzero(tick_sorted[1:] != tick_sorted[:-1]) + 1
for grp in np.split(order, bounds):
    t = panel.tickers[grp[0]]
    b = p.market.bars[t]
    rows = panel.rows[grp]
    for rule in RULES:
        gross[rule][grp] = exits(b, rows, *rule)
    ok = rows + 1 < len(b.open)
    j = rows[ok] + 1
    up1[grp[ok]] = b.high[j] / b.open[j] - 1
    oc1[grp[ok]] = b.close[j] / b.open[j] - 1
    dn1[grp[ok]] = b.low[j] / b.open[j] - 1
    gap_next[grp[ok]] = b.open[j] / b.close[j - 1] - 1
cost = np.array([CostModel().per_side(0.0, float(dv), 0.0, float(pr)) for dv, pr in zip(panel.dollar_volume, panel.price)])
net = {rule: (1 + g) * (1 - cost) / (1 + cost) - 1 for rule, g in gross.items()}
print("outcomes done", flush=True)

col = lambda name: panel.column(name).astype(float)
dev = p.usable & (p.ordinals <= p.dev_end.toordinal())
hold = p.usable & (p.ordinals >= p.holdout_start.toordinal())


def buckets(x, edges, labels):
    out = np.full(len(x), "", dtype=object)
    for (a, b_), lab in zip(zip(edges[:-1], edges[1:]), labels):
        out[(x >= a) & (x < b_)] = lab
    return out


conds = {
    "news before the open (8-K overnight)": np.where(col("cat_overnight_earnings") == 1, "earnings 8-K",
                                             np.where(col("cat_overnight_deal") == 1, "deal 8-K",
                                             np.where(col("cat_overnight_any") == 1, "other 8-K", "no 8-K"))),
    "opening gap (known just after the open)": buckets(gap_next, [-1, -0.10, -0.03, 0.03, 0.10, 0.20, 10],
                                                        ["< -10%", "-10..-3%", "-3..+3%", "+3..+10%", "+10..+20%", "> +20%"]),
    "move on the signal day": buckets(col("ret_1d"), [-1, -0.10, -0.03, 0.03, 0.10, 10],
                                      ["< -10%", "-10..-3%", "-3..+3%", "+3..+10%", "> +10%"]),
    "relative volume (signal day)": buckets(col("rvol"), [0, 1, 2, 5, 1e9], ["< 1x", "1-2x", "2-5x", "> 5x"]),
    "price (traded)": buckets(panel.price.astype(float), [0, 5, 20, 100, 1e9], ["$2-5", "$5-20", "$20-100", "> $100"]),
    "daily volatility (20d)": buckets(col("vol_20"), [0, 0.02, 0.04, 0.08, 10], ["< 2%", "2-4%", "4-8%", "> 8%"]),
    "liquidity (20d $ volume)": buckets(p.dollar_volume, [0, 10e6, 50e6, 250e6, 1e15], ["$5-10M", "$10-50M", "$50-250M", "> $250M"]),
    "market (SPY vs 200d average)": np.where(np.array([p.spy_up.get(d, False) for d in panel.dates]), "rising", "falling"),
}
# two-way: earnings news x opening gap
conds["earnings 8-K x opening gap"] = np.where(conds["news before the open (8-K overnight)"] == "earnings 8-K",
                                               conds["opening gap (known just after the open)"], "")

results, pvals = [], {}
for cname, lab in conds.items():
    for value in sorted(set(lab[dev]) - {""}):
        m = dev & (lab == value)
        if m.sum() < 300 or len(set(panel.dates[m])) < 100:
            continue
        row = {"condition": cname, "value": value, "n": int(m.sum()), "days": len(set(panel.dates[m])),
               "p_up5_intraday": float(np.mean(up1[m] >= 0.05)), "p_up10_intraday": float(np.mean(up1[m] >= 0.10)),
               "p_down5_intraday": float(np.mean(dn1[m] <= -0.05)), "p_down10_intraday": float(np.mean(dn1[m] <= -0.10)),
               "median_max_up": float(np.nanmedian(up1[m])),
               "p_close_above_open": float(np.mean(oc1[m] > 0)), "mean_open_to_close": float(np.nanmean(oc1[m])),
               "rules": {}}
        for rule in RULES:
            x = net[rule][m]
            okx = np.isfinite(x)
            lo_, hi_, pv = stats.cluster_bootstrap_mean(x[okx], panel.dates[m][okx], n=400, seed=protocol.SEED)
            key = f"{rule[0]}d +{int(rule[1]*100)}%" + (f" stop {int(rule[2]*100)}%" if rule[2] else "")
            hm = hold & (lab == value)
            hx = net[rule][hm]
            hx = hx[np.isfinite(hx)]
            row["rules"][key] = {"mean_net": float(np.mean(x[okx])), "ci": (lo_, hi_), "p": pv,
                                 "hit_target": float(np.mean(gross[rule][m][okx] >= rule[1] - 1e-9)),
                                 "holdout_n": int(len(hx)), "holdout_mean_net": float(np.mean(hx)) if len(hx) else None}
            pvals[(cname, value, key)] = pv if np.mean(x[okx]) > 0 else 1.0
        results.append(row)
        print(cname, value, row["n"], max((r["mean_net"], k) for k, r in row["rules"].items()), flush=True)
holm = stats.holm({"|".join(k): v for k, v in pvals.items()}, 0.05)
for row in results:
    for key, r in row["rules"].items():
        r["significant_holm"] = holm["|".join((row["condition"], row["value"], key))]
json.dump({"trials": len(pvals), "results": results}, open(out_path, "w"), indent=1, default=float)
print("written", out_path, "trials", len(pvals), "significant", sum(holm.values()), flush=True)
