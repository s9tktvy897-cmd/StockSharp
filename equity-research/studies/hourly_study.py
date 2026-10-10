"""Exploratory: the highest point after the open (hourly bars, regular session), its timing, and what
realistic exit rules earn. Signals are known before the open of day D (data up to the close of D-1,
8-Ks up to 09:00 ET of D) plus the opening gap, which is known just after the open.
Period: common to all tickers (from 2024-10-14). Does not change any strategy status."""
import gzip, io, sys, json
from datetime import date, datetime
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from equity_research.research import experiment, protocol, stats
from equity_research.research.__main__ import load_inputs
from equity_research.research.execution import CostModel

HOURLY = Path(sys.argv[2]); OUT = Path(sys.argv[3])
START = date(2024, 10, 14)
inputs = load_inputs(Path(sys.argv[1]), 0, True)
split_like = lambda problems: all("possible unadjusted split" in x for x in problems)
inputs.excluded = {t: pr for t, pr in inputs.excluded.items() if not split_like(pr)}
p = experiment.prepare(inputs)
panel = p.panel
print("panel ready", len(panel.dates), flush=True)

def num(x: str) -> float:
    """Values were written with repr(); numpy scalars appear as 'np.float64(1.5)'."""
    x = x.strip()
    if x.startswith("np."):
        x = x[x.index("(") + 1:x.rindex(")")]
    return float(x)


# index panel rows by (ticker, signal date)
SLOTS = 7  # 09:30, 10:30, ..., 15:30
rec = {k: [] for k in ("row", "open", "gap")}
H = []; L = []; C = []
order = np.argsort(panel.tickers, kind="stable")
ts = panel.tickers[order]
bounds = np.flatnonzero(ts[1:] != ts[:-1]) + 1
loaded = 0
for grp in np.split(order, bounds):
    t = panel.tickers[grp[0]]
    f = HOURLY / f"{t.replace('.', '-')}.csv.gz"
    if not f.exists():
        continue
    lines = gzip.decompress(f.read_bytes()).decode().split("\n")[1:]
    days = {}
    for line in lines:
        parts = line.split(",")
        stamp = datetime.fromisoformat(parts[0])
        slot = stamp.hour - 9 if stamp.minute == 30 else None
        if slot is None or not 0 <= slot < SLOTS:
            continue
        days.setdefault(stamp.date(), {})[slot] = [num(x) for x in parts[1:5]]
    b = p.market.bars[t]
    dates = b.dates
    for r in grp:
        i = panel.rows[r]
        if i + 1 >= len(dates):
            continue
        d1 = dates[i + 1]
        if d1 < START or d1 not in days:
            continue
        bars = days[d1]
        if 0 not in bars or len(bars) < 6:
            continue  # need the opening hour and (almost) the whole session
        o = bars[0][0]
        hi = np.full(SLOTS, np.nan); lo = np.full(SLOTS, np.nan); cl = np.full(SLOTS, np.nan)
        for s, (bo, bh, bl, bc) in bars.items():
            hi[s], lo[s], cl[s] = bh, bl, bc
        # consistency with the daily bar (unadjusted hourly vs adjusted daily: compare ratios)
        dh = b.high[i + 1] / b.open[i + 1]
        if not np.isfinite(o) or o <= 0 or abs(np.nanmax(hi) / o - dh) > 0.02:
            continue
        rec["row"].append(r); rec["open"].append(o)
        rec["gap"].append(b.open[i + 1] / b.close[i] - 1)
        H.append(hi / o - 1); L.append(lo / o - 1); C.append(cl / o - 1)
    loaded += 1
rows = np.array(rec["row"]); H = np.array(H); L = np.array(L); C = np.array(C); gap = np.array(rec["gap"])
print("tickers with hourly data", loaded, "stock-days", len(rows), flush=True)

# forward-fill missing slots for the path (a missing middle hour: carry the previous close)
for k in range(1, SLOTS):
    miss = ~np.isfinite(C[:, k])
    C[miss, k] = C[miss, k - 1]; H[miss, k] = C[miss, k - 1]; L[miss, k] = C[miss, k - 1]
peak = np.nanmax(H, axis=1)
peak_slot = np.nanargmax(H, axis=1)
close = C[:, -1]
cost = np.array([CostModel().per_side(0.0, float(panel.dollar_volume[r]), 0.0, float(panel.price[r])) for r in rows])


def rule(target, stop, until_slot):
    """Buy at the open; sell at +target (limit) or stop, checked hour by hour (stop first inside an hour),
    else at the close of slot ``until_slot`` (1 = 11:30, 3 = 13:30, 6 = 16:00)."""
    out = np.full(len(rows), np.nan); done = np.zeros(len(rows), bool)
    for s in range(until_slot + 1):
        if stop is not None:
            g = ~done & (L[:, s] <= -stop); out[g] = -stop; done |= g
        if target is not None:
            g = ~done & (H[:, s] >= target); out[g] = target; done |= g
    out[~done] = C[~done, until_slot]
    return (1 + out) * (1 - cost) / (1 + cost) - 1


RULES = {f"+{int(t*100)}% {'stop 5% ' if s else ''}until {lab}": (t, s, u)
         for t in (0.05, 0.07, 0.10) for s in (None, 0.05) for u, lab in ((1, "11:30"), (3, "13:30"), (6, "close"))}
nets = {k: rule(*v) for k, v in RULES.items()}

col = lambda name: panel.column(name).astype(float)[rows]
dates = panel.dates[rows]
signal_ord = np.array([d.toordinal() for d in dates])
half = np.where(signal_ord < date(2025, 10, 1).toordinal(), "2024-10..2025-09", "2025-10..2026-10")


def buckets(x, edges, labels):
    out = np.full(len(x), "", dtype=object)
    for (a, b_), lab in zip(zip(edges[:-1], edges[1:]), labels):
        out[(x >= a) & (x < b_)] = lab
    return out


conds = {
    "all": np.full(len(rows), "all stock-days", dtype=object),
    "news before the open (8-K)": np.where(col("cat_overnight_earnings") == 1, "earnings 8-K",
                                   np.where(col("cat_overnight_deal") == 1, "deal 8-K",
                                   np.where(col("cat_overnight_any") == 1, "other 8-K", "no 8-K"))),
    "opening gap": buckets(gap, [-1, -0.10, -0.03, 0.03, 0.10, 0.20, 10], ["< -10%", "-10..-3%", "-3..+3%", "+3..+10%", "+10..+20%", "> +20%"]),
    "move on the day before": buckets(col("ret_1d"), [-1, -0.10, -0.03, 0.03, 0.10, 10], ["< -10%", "-10..-3%", "-3..+3%", "+3..+10%", "> +10%"]),
    "relative volume (day before)": buckets(col("rvol"), [0, 1, 2, 5, 1e9], ["< 1x", "1-2x", "2-5x", "> 5x"]),
    "price": buckets(panel.price.astype(float)[rows], [0, 5, 20, 100, 1e9], ["$2-5", "$5-20", "$20-100", "> $100"]),
    "daily volatility (20d)": buckets(col("vol_20"), [0, 0.02, 0.04, 0.08, 10], ["< 2%", "2-4%", "4-8%", "> 8%"]),
    "market (SPY vs 200d)": np.where(np.array([p.spy_up.get(d, False) for d in dates]), "rising", "falling"),
}
conds["earnings 8-K x opening gap"] = np.where(conds["news before the open (8-K)"] == "earnings 8-K", conds["opening gap"], "")
conds["gap x relative volume"] = np.where(np.isin(conds["opening gap"], ["+3..+10%", "+10..+20%", "> +20%"]),
                                          conds["opening gap"] + " & rvol " + conds["relative volume (day before)"], "")
SLOT_LABELS = ["09:30-10:30", "10:30-11:30", "11:30-12:30", "12:30-13:30", "13:30-14:30", "14:30-15:30", "15:30-16:00"]

results, pvals = [], {}
for cname, lab in conds.items():
    for value in sorted(set(lab) - {""}):
        m = lab == value
        if m.sum() < 300 or len(set(dates[m])) < 100:
            continue
        big = m & (peak >= 0.05)
        row = {"condition": cname, "value": value, "n": int(m.sum()), "days": len(set(dates[m])),
               "p_peak_5": float(np.mean(peak[m] >= 0.05)), "p_peak_10": float(np.mean(peak[m] >= 0.10)),
               "median_peak": float(np.median(peak[m])), "mean_peak": float(np.mean(peak[m])),
               "p_low_5": float(np.mean(np.nanmin(L[m], axis=1) <= -0.05)),
               "mean_open_to_close": float(np.mean(close[m])),
               "giveback_after_peak": float(np.mean(peak[m] - close[m])),
               "peak_hour_share": {SLOT_LABELS[s]: float(np.mean(peak_slot[m] == s)) for s in range(SLOTS)},
               "peak_hour_share_if_peak_5": {SLOT_LABELS[s]: float(np.mean(peak_slot[big] == s)) for s in range(SLOTS)} if big.any() else {},
               "rules": {}}
        for key, x in nets.items():
            ok = np.isfinite(x) & m
            lo_, hi_, pv = stats.cluster_bootstrap_mean(x[ok], dates[ok], n=300, seed=protocol.SEED)
            halves = {h: float(np.mean(x[ok & (half == h)])) if (ok & (half == h)).any() else None for h in sorted(set(half))}
            row["rules"][key] = {"mean_net": float(np.mean(x[ok])), "ci": (lo_, hi_), "p": pv, "halves": halves,
                                 "hit": float(np.mean(x[ok] >= RULES[key][0] - 2 * cost[ok] - 1e-6))}
            pvals[f"{cname}|{value}|{key}"] = pv if np.mean(x[ok]) > 0 else 1.0
        results.append(row)
        best = max(row["rules"].items(), key=lambda kv: kv[1]["mean_net"])
        print(f"{cname} = {value}: n {row['n']}, P(peak>=5%) {row['p_peak_5']:.1%}, best {best[0]} {best[1]['mean_net']:.3%}", flush=True)
holm = stats.holm(pvals, 0.05)
for row in results:
    for key, r in row["rules"].items():
        r["significant_holm"] = holm[f"{row['condition']}|{row['value']}|{key}"]
json.dump({"period_from": START.isoformat(), "stock_days": int(len(rows)), "trials": len(pvals), "results": results},
          open(OUT, "w"), indent=1, default=float)
print("written", OUT, "trials", len(pvals), "significant", sum(holm.values()), flush=True)
