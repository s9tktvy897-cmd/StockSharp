"""Historical simulation of the daily top picks with realistic execution.

- Signal after the close of day t; entry at the open of t+1 (overnight gap included).
- Exit at +target (a limit order): intraday at the target price, or at the open when a later day
  gaps above it. Optional stop loss the same way. If target and stop both fall inside one daily
  bar the order is unknown; by default the stop is assumed (conservative).
- Otherwise exit at the close of the horizon day.
- Costs per side from ``Config.costs`` (spread by liquidity tier + slippage + commission)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from equity_research.shortterm.bars import Bars
from equity_research.shortterm.config import Config
from equity_research.shortterm.dataset import Panel
from equity_research.shortterm.evaluation import daily_top, wilson


@dataclass(frozen=True)
class Trade:
    ticker: str
    signal_date: date | None
    entry_date: date | None
    exit_date: date | None
    entry_price: float
    exit_price: float
    gross: float
    net: float
    reason: str
    hit_target: bool
    max_down: float


def simulate(bars: Bars, i: int, horizon: int, config: Config, dollar_volume: float) -> Trade | None:
    n = len(bars)
    if i + horizon >= n:
        return None
    entry = bars.open[i + 1]
    target = entry * (1 + config.target)
    stop = entry * (1 - config.stop_loss) if config.stop_loss else None
    exit_price, reason, exit_day = None, "time", i + horizon
    for j in range(i + 1, i + horizon + 1):
        if j > i + 1 and bars.open[j] >= target:
            exit_price, reason, exit_day = bars.open[j], "gap above target", j
            break
        if j > i + 1 and stop is not None and bars.open[j] <= stop:
            exit_price, reason, exit_day = bars.open[j], "gap below stop", j
            break
        hit_target = bars.high[j] >= target
        hit_stop = stop is not None and bars.low[j] <= stop
        if hit_target and hit_stop:
            first_stop = config.same_bar_stop_first
            exit_price = stop if first_stop else target
            reason, exit_day = ("stop (same bar as target)" if first_stop else "target (same bar as stop)"), j
            break
        if hit_stop:
            exit_price, reason, exit_day = stop, "stop", j
            break
        if hit_target:
            exit_price, reason, exit_day = target, "target", j
            break
    if exit_price is None:
        exit_price = bars.close[i + horizon]
    cost = config.costs.per_side(dollar_volume)
    low = float(np.min(bars.low[i + 1:exit_day + 1]))
    return Trade(bars.ticker, bars.dates[i], bars.dates[i + 1], bars.dates[exit_day], float(entry), float(exit_price),
                 float(exit_price / entry - 1), float(exit_price * (1 - cost) / (entry * (1 + cost)) - 1),
                 reason, reason.startswith(("target", "gap above")), low / entry - 1)


def summarize(trades: list[Trade], drop: float = 0.10) -> dict:
    if not trades:
        return {"trades": 0}
    net = np.array([t.net for t in trades])
    wins, losses = net[net > 0], net[net <= 0]
    hits = sum(t.hit_target for t in trades)
    drops = sum(t.max_down <= -drop for t in trades)
    return {
        "trades": len(trades),
        "hit_rate": hits / len(trades), "hit_ci": wilson(hits, len(trades)),
        "drop_rate": drops / len(trades), "drop_ci": wilson(drops, len(trades)),
        "mean_net": float(net.mean()), "median_net": float(np.median(net)),
        "mean_net_ci": (float(net.mean() - 1.96 * net.std(ddof=1) / np.sqrt(len(net))),
                        float(net.mean() + 1.96 * net.std(ddof=1) / np.sqrt(len(net)))) if len(net) > 1
        else (float("nan"), float("nan")),
        "mean_gross": float(np.mean([t.gross for t in trades])),
        "win_rate": float(len(wins) / len(net)),
        "payoff_ratio": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else float("nan"),
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("nan"),
        "worst": float(net.min()), "best": float(net.max()),
    }


def equity_curve(daily_returns: list[float]) -> list[float]:
    return list(np.cumprod(1 + np.asarray(daily_returns, dtype=float))) if daily_returns else []


def max_drawdown(curve: list[float]) -> float:
    peak, worst = 1.0, 0.0
    for value in curve:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


@dataclass
class BacktestResult:
    horizon: int
    trades: list[Trade]
    summary: dict
    by_year: dict[int, dict]
    by_regime: dict[str, dict]
    benchmark: dict
    max_drawdown: float
    days: int
    days_without_picks: int
    curve: list[float] = field(default_factory=list)


def run(panel: Panel, scores: np.ndarray, universe: dict[str, Bars], config: Config, horizon: int) -> BacktestResult:
    tested = panel.eligible & np.isfinite(scores) & np.isfinite(panel.outcomes[horizon]["hit"])
    picks = daily_top(scores, panel.dates, tested, config.top_n)
    trades, by_day = [], defaultdict(list)
    regime_of = {}
    market20 = panel.column("market_ret_20d")
    for row in picks:
        trade = simulate(universe[panel.tickers[row]], int(panel.rows[row]), horizon, config, panel.dollar_volume[row])
        if trade:
            trades.append(trade)
            by_day[panel.dates[row]].append(trade.net)
            regime_of[(trade.ticker, trade.signal_date)] = "rising market (20d)" if market20[row] > 0 else "falling market (20d)"
    test_days = sorted(set(panel.dates[tested]))
    # Capital: each signal day gets 1/horizon of the account, split equally over its picks.
    daily = [float(np.mean(by_day[d])) / horizon if by_day.get(d) else 0.0 for d in test_days]
    curve = equity_curve(daily)
    years = defaultdict(list)
    regimes = defaultdict(list)
    for t in trades:
        years[t.signal_date.year].append(t)
        regimes[regime_of[(t.ticker, t.signal_date)]].append(t)
    y = panel.outcomes[horizon]
    bench_rows = tested
    cost = np.array([config.costs.per_side(v) for v in panel.dollar_volume[bench_rows]])
    benchmark = {
        "rows": int(np.sum(bench_rows)),
        "hit_rate": float(np.mean(y["hit"][bench_rows])) if np.any(bench_rows) else float("nan"),
        "drop_rate": float(np.mean(y["drop"][bench_rows])) if np.any(bench_rows) else float("nan"),
        "mean_net_hold": float(np.mean((1 + y["ret_close"][bench_rows]) * (1 - cost) / (1 + cost) - 1))
        if np.any(bench_rows) else float("nan"),
    }
    return BacktestResult(horizon, trades, summarize(trades, config.drop), {k: summarize(v, config.drop) for k, v in sorted(years.items())},
                          {k: summarize(v, config.drop) for k, v in sorted(regimes.items())}, benchmark,
                          max_drawdown(curve), len(test_days), sum(1 for d in test_days if not by_day.get(d)), curve)
