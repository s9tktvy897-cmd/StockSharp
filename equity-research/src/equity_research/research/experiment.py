"""Research runner: builds the panel once, scores every pre-registered variant, simulates the
portfolio with the risk layer at 1x/2x/3x costs, applies the criteria and the Holm correction,
evaluates the holdout once and assigns a status. Nothing is tuned here: every threshold comes from
``protocol``."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from equity_research.research import protocol, stats, strategies
from equity_research.research.execution import CostModel
from equity_research.research.portfolio import ExitRule, MarketData, SimulationResult, simulate
from equity_research.research.risk import RiskLimits, RiskManager
from equity_research.shortterm.bars import Bars, validate
from equity_research.shortterm.config import Config
from equity_research.shortterm.dataset import Panel, build_panel
from equity_research.shortterm.evaluation import daily_top

HORIZONS = (1, 2, 5, 10, 20)
BENCHMARK_TICKERS = ("SPY", "QQQ", "IWM", "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE",
                     "XLC", "^VIX", "^GSPC")


@dataclass
class Inputs:
    universe: dict[str, Bars]
    spy: Bars
    filings: dict | None
    sectors: dict[str, str]
    excluded: dict[str, list[str]]
    notes: list[str] = field(default_factory=list)


@dataclass
class Prepared:
    panel: Panel
    market: MarketData
    usable: np.ndarray
    labels: dict[int, dict[str, np.ndarray]]
    vol20: np.ndarray
    dollar_volume: np.ndarray
    spy_up: dict[date, bool]
    spy_returns: dict[date, float]
    dev_end: date
    holdout_start: date
    calendar: list[date]
    ordinals: np.ndarray = None  # panel dates as ordinals (fast window masks)

    def window(self, start: date, end: date) -> np.ndarray:
        return (self.ordinals >= start.toordinal()) & (self.ordinals <= end.toordinal())


def prepare(inputs: Inputs, config: Config | None = None) -> Prepared:
    config = config or Config(horizons=HORIZONS)
    panel = build_panel(inputs.universe, inputs.filings, config)
    market = MarketData(inputs.universe, inputs.sectors)
    bad = set(inputs.excluded)
    usable = panel.eligible & np.array([t not in bad for t in panel.tickers]) & (panel.rows >= protocol.WARMUP_DAYS - 8)
    vol20 = panel.column("vol_20").astype(float)
    # per-row cost estimate for the model labels (no impact: the order size is not known yet)
    cost = np.empty(len(panel.dates))
    model = CostModel()
    for k in range(len(cost)):
        cost[k] = model.per_side(0.0, float(panel.dollar_volume[k]), 0.0, float(panel.price[k]))
    labels = {}
    for h in HORIZONS:
        o = panel.outcomes[h]
        net = (1 + o["ret_close"]) * (1 - cost) / (1 + cost) - 1
        up = np.where(np.isfinite(net), (net > 0).astype(float), np.nan)
        labels[h] = {"net": net, "up": up, "hit": o["hit"]}
    spy = inputs.spy
    ma200 = np.convolve(spy.close, np.ones(200) / 200, mode="full")[:len(spy.close)]
    ma200[:199] = np.nan
    spy_up = {d: bool(c > m) for d, c, m in zip(spy.dates, spy.close, ma200) if np.isfinite(m)}
    spy_ret = {d: float(spy.close[i] / spy.close[i - 1] - 1) for i, d in enumerate(spy.dates) if i}
    dev_end = protocol.HOLDOUT_START - timedelta(days=protocol.EMBARGO_DAYS)
    return Prepared(panel, market, usable, labels, vol20, panel.dollar_volume.astype(float), spy_up, spy_ret,
                    dev_end, protocol.HOLDOUT_START, list(spy.dates), np.array([d.toordinal() for d in panel.dates]))


def picks_from(scores: np.ndarray, p: Prepared, window: tuple[date, date], n: int) -> dict[date, list]:
    mask = p.usable & np.isfinite(scores) & p.window(window[0], window[1])
    top = daily_top(scores, p.panel.dates, mask, n)
    out: dict[date, list] = {}
    for row in top:
        out.setdefault(p.panel.dates[row], []).append((p.panel.tickers[row], float(scores[row])))
    return out


def _regime_means(res: SimulationResult, spy_up: dict) -> dict[str, float]:
    # regime of a day = SPY above/below its 200-day average at the previous close
    prev = {}
    last = None
    for d in res.dates:
        prev[d] = spy_up.get(last) if last else None
        last = d
    up = [r for d, r in zip(res.dates, res.returns) if prev.get(d) is True]
    down = [r for d, r in zip(res.dates, res.returns) if prev.get(d) is False]
    return {"rising": float(np.mean(up)) if up else float("nan"), "falling": float(np.mean(down)) if down else float("nan")}


def _year_means(res: SimulationResult) -> dict[int, float]:
    years: dict[int, list] = {}
    for d, r in zip(res.dates, res.returns):
        years.setdefault(d.year, []).append(r)
    return {y: float(np.mean(v)) for y, v in sorted(years.items())}


def _active_window(res: SimulationResult) -> slice:
    """From the first fill (or first signal) to the end: idle warm-up days are not part of the test."""
    if not res.trades:
        return slice(0, len(res.dates))
    first = min(t.entry_date for t in res.trades)
    k = next(i for i, d in enumerate(res.dates) if d >= first)
    return slice(max(k - 1, 0), len(res.dates))


@dataclass
class VariantResult:
    variant: protocol.Variant
    dev: dict
    dev_2x: dict
    dev_3x: dict
    holdout: dict
    holdout_2x: dict
    criteria: dict
    p_value: float
    daily_ci: tuple
    trade_ci: tuple
    deflated_sharpe: float
    years: dict
    regimes: dict
    spy_sharpe: float
    holdout_ok: bool | None = None
    status: str = ""
    blocked: dict = field(default_factory=dict)
    cancelled: dict = field(default_factory=dict)
    chosen: dict = field(default_factory=dict)
    curve: list = field(default_factory=list)
    holdout_curve: list = field(default_factory=list)
    period: tuple = ()


def evaluate_variant(variant: protocol.Variant, dev_scores: np.ndarray, hold_scores: np.ndarray, p: Prepared,
                     risk_limits: RiskLimits, chosen: dict | None = None) -> VariantResult:
    rule = ExitRule(variant.horizon, target=variant.target)
    base = CostModel()
    finite = np.isfinite(dev_scores)
    first = date.fromordinal(int(p.ordinals[finite].min())) if finite.any() else p.dev_end
    dev_window = (first, p.dev_end)
    dev_cal = [d for d in p.calendar if first <= d <= p.dev_end + timedelta(days=protocol.EMBARGO_DAYS - 1)]
    hold_cal = [d for d in p.calendar if d >= p.holdout_start]
    dev_picks = picks_from(dev_scores, p, dev_window, 3 * protocol.TOP_N)
    hold_picks = picks_from(hold_scores, p, (p.holdout_start, p.calendar[-1]), 3 * protocol.TOP_N)

    def run(picks, cal, factor):
        risk = RiskManager(risk_limits, correlation=p.market.correlation)
        return simulate(p.market, picks, cal, rule, base.stressed(factor), risk, protocol.TOP_N, protocol.CAPITAL)

    sims = {f: run(dev_picks, dev_cal, f) for f in protocol.COST_STRESS}
    res = sims[1.0]
    w = _active_window(res)
    r = res.returns[w]
    dates = res.dates[w]
    dev = res.summary() | stats.performance(r)
    lo, hi, pval = stats.bootstrap_mean(r, protocol.BOOTSTRAP_BLOCK, protocol.BOOTSTRAP_REPS, protocol.SEED)
    tlo, thi, _ = stats.cluster_bootstrap_mean([t.net for t in res.trades], [t.signal_date for t in res.trades],
                                               n=protocol.BOOTSTRAP_REPS, seed=protocol.SEED) if len(res.trades) > 1 \
        else (float("nan"), float("nan"), float("nan"))
    spy = np.array([p.spy_returns.get(d, 0.0) for d in dates])
    spy_sharpe = stats.performance(spy).get("sharpe", float("nan"))
    years = _year_means(SimulationResult(dates, r, res.exposure[w], [], Counter(), Counter(), 0, 0, 0.0))
    regimes = _regime_means(SimulationResult(dates, r, res.exposure[w], [], Counter(), Counter(), 0, 0, 0.0), p.spy_up)
    s2 = sims[2.0].returns[_active_window(sims[2.0])]
    criteria = {
        "min_trades": dev.get("trade_trades", 0) >= protocol.MIN_TRADES,
        "min_edge": dev.get("trade_expected_value", -1) >= protocol.MIN_EDGE_PER_TRADE,
        "beats_spy_sharpe": np.nan_to_num(dev.get("sharpe", np.nan), nan=-9) > np.nan_to_num(spy_sharpe, nan=9),
        "max_drawdown": dev.get("max_drawdown", -1) >= protocol.MAX_DRAWDOWN,
        "cost_stress_2x": len(s2) > 0 and float(np.mean(s2)) > 0,
        "positive_years": bool(years) and np.mean([v > 0 for v in years.values()]) >= protocol.MIN_POSITIVE_YEAR_SHARE,
        "both_regimes": regimes["rising"] > 0 and regimes["falling"] > 0,
        "not_extreme_driven": np.nan_to_num(dev.get("trade_mean_without_top_1pct", np.nan), nan=-1) > 0,
        "significant_unadjusted": bool(np.isfinite(pval) and pval < protocol.ALPHA and r.mean() > 0),
    }
    hold = {f: run(hold_picks, hold_cal, f) for f in (1.0, 2.0)}
    hs = hold[1.0].summary()
    h2 = hold[2.0].summary()
    holdout_ok = bool(hs.get("mean_daily", -1) > 0 and hs.get("trade_expected_value", -1) > 0
                      and hs.get("max_drawdown", -1) >= protocol.MAX_DRAWDOWN and h2.get("mean_daily", -1) > 0)
    eq = np.cumprod(1 + r)
    return VariantResult(variant, dev, sims[2.0].summary(), sims[3.0].summary(), hs, h2, criteria, pval, (lo, hi),
                         (tlo, thi), stats.deflated_sharpe(r, len(protocol.GRID)), years, regimes, spy_sharpe,
                         holdout_ok, "", dict(res.blocked), dict(res.cancelled), chosen or {},
                         [(d.isoformat(), float(e)) for d, e in zip(dates, eq)],
                         [(d.isoformat(), float(e)) for d, e in zip(hold[1.0].dates, np.cumprod(1 + hold[1.0].returns))],
                         (dates[0].isoformat() if len(dates) else "", dates[-1].isoformat() if len(dates) else ""))


def finalize(results: list[VariantResult]) -> None:
    """Holm over all variants, then the status of each."""
    pvals = {v.variant.name: (v.p_value if v.criteria["significant_unadjusted"] else 1.0) for v in results}
    holm = stats.holm(pvals, protocol.ALPHA)
    for v in results:
        v.criteria["significant_holm"] = holm[v.variant.name]
        v.status = protocol.status(v.criteria, v.holdout_ok)


def benchmarks(p: Prepared, risk_limits: RiskLimits, start: date) -> dict:
    out = {}
    dev_days = [d for d in p.calendar if start <= d <= p.dev_end]
    hold_days = [d for d in p.calendar if d >= p.holdout_start]
    for name, days in (("development", dev_days), ("holdout", hold_days)):
        spy = np.array([p.spy_returns.get(d, 0.0) for d in days])
        out[f"SPY_BUY_AND_HOLD {name}"] = stats.performance(spy)
    # equal-weighted eligible universe, close to close, gross (no costs: an upper bound for passive)
    ret1 = p.panel.column("ret_1d").astype(float)
    by_day: dict[date, list] = {}
    for d, r, ok in zip(p.panel.dates, ret1, p.usable):
        if ok and np.isfinite(r):
            by_day.setdefault(d, []).append(r)
    for name, days in (("development", dev_days), ("holdout", hold_days)):
        ew = np.array([float(np.mean(by_day[d])) if d in by_day else 0.0 for d in days])
        out[f"EQUAL_WEIGHT_UNIVERSE {name}"] = stats.performance(ew)
    rng = np.random.default_rng(protocol.SEED)
    random_scores = rng.random(len(p.panel.dates))
    for h in HORIZONS:
        v = protocol.Variant("RANDOM", h)
        dev_scores = np.where(p.window(start, p.dev_end), random_scores, np.nan)
        hold_scores = np.where(p.ordinals >= p.holdout_start.toordinal(), random_scores, np.nan)
        r = evaluate_variant(v, dev_scores, hold_scores, p, risk_limits)
        out[f"RANDOM {h}d development"] = r.dev
        out[f"RANDOM {h}d holdout"] = r.holdout
    return out


def run_all(inputs: Inputs, variants=None, risk_limits: RiskLimits | None = None, progress=print) -> dict:
    variants = list(variants or protocol.GRID)
    risk_limits = risk_limits or RiskLimits()
    p = prepare(inputs)
    progress(f"panel: {len(p.panel.dates)} rows, {int(np.sum(p.usable))} usable, {len(np.unique(p.panel.tickers))} tickers")
    results = []
    fitted_cache: dict = {}
    spy_up_rows = None
    for v in variants:
        if v.strategy in ("EXISTING_TARGET10", "MODEL_A_DIRECTION", "MODEL_B_EXPECTED_RETURN", "MODEL_C_RISK_ADJUSTED"):
            key = (v.strategy, v.horizon)
            if key not in fitted_cache:
                group = tuple(x.strategy for x in variants if x.horizon == v.horizon
                              and strategies._fit_group(x.strategy) == strategies._fit_group(v.strategy))
                many = strategies.fitted_scores_many(group, p.panel, v.horizon, p.labels[v.horizon], p.usable,
                                                     p.vol20, p.dev_end, p.holdout_start)
                for k, f in many.items():
                    fitted_cache[(k, v.horizon)] = f
            f = fitted_cache[key]
            dev_scores, hold_scores, chosen = f.dev, f.holdout, f.chosen
        else:
            if spy_up_rows is None:
                spy_up_rows = np.array([p.spy_up.get(d, False) for d in p.panel.dates])
            s = strategies.rule_score(v.strategy, p.panel, spy_up_rows, p.dollar_volume)
            in_dev = p.ordinals <= p.dev_end.toordinal()
            dev_scores, hold_scores, chosen = np.where(in_dev, s, np.nan), np.where(
                p.ordinals >= p.holdout_start.toordinal(), s, np.nan), {}
        results.append(evaluate_variant(v, dev_scores, hold_scores, p, risk_limits, chosen))
        r = results[-1]
        progress(f"{v.name}: trades {r.dev.get('trade_trades', 0)}, mean/trade {r.dev.get('trade_expected_value', float('nan')):.4%}, "
                 f"Sharpe {r.dev.get('sharpe', float('nan')):.2f}, maxDD {r.dev.get('max_drawdown', float('nan')):.1%}")
    finalize(results)
    starts = [date.fromisoformat(r.period[0]) for r in results if r.period and r.period[0]]
    bench = benchmarks(p, risk_limits, min(starts) if starts else p.calendar[0])
    return {"results": results, "benchmarks": bench, "prepared": p}


def to_json(run: dict, inputs: Inputs) -> dict:
    def clean(x):
        if isinstance(x, float):
            return None if not np.isfinite(x) else x
        if isinstance(x, (np.floating, np.integer)):
            return clean(x.item())
        if isinstance(x, (np.bool_,)):
            return bool(x)
        if isinstance(x, dict):
            return {str(k): clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        return x
    rows = []
    for r in run["results"]:
        rows.append(clean({
            "variant": r.variant.name, "strategy": r.variant.strategy, "horizon": r.variant.horizon,
            "status": r.status, "period": r.period, "dev": r.dev, "dev_2x": r.dev_2x, "dev_3x": r.dev_3x,
            "holdout": r.holdout, "holdout_2x": r.holdout_2x, "holdout_ok": r.holdout_ok, "criteria": r.criteria,
            "p_value": r.p_value, "daily_ci": r.daily_ci, "trade_ci": r.trade_ci,
            "deflated_sharpe": r.deflated_sharpe, "years": r.years, "regimes": r.regimes, "spy_sharpe": r.spy_sharpe,
            "blocked": r.blocked, "cancelled": r.cancelled, "chosen": r.chosen, "curve": r.curve[::5],
            "holdout_curve": r.holdout_curve,
        }))
    p = run["prepared"]
    equity, spy_curve = 1.0, []
    for k, d in enumerate(p.calendar):
        equity *= 1 + p.spy_returns.get(d, 0.0)
        if k % 5 == 0 or k == len(p.calendar) - 1:
            spy_curve.append((d.isoformat(), equity))
    return {"variants": rows, "benchmarks": clean(run["benchmarks"]), "excluded": len(inputs.excluded),
            "notes": inputs.notes, "spy_curve": clean(spy_curve)}
