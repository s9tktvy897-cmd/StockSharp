"""Day-by-day portfolio simulation with realistic execution and the risk layer.

Timeline for a signal on day t (decided after the close of t with data up to t):
- the order is sized by the risk layer on the close of t and sent for the open of t+1;
- it fills at the open of t+1 plus costs, at most ``max_participation`` of that day's dollar
  volume; no bar on t+1 (halt, missing data) = not filled;
- time exit at the close of t+h minus costs; optional +target limit (filled at the target, or at
  the open when a later day gaps above it) and stop (filled at the open when it gaps below, else at
  the stop minus slippage; never a guaranteed price); both in one bar = the stop (conservative);
- when a ticker's history ends before the exit (delisting, data gap) the position is closed at its
  last close and flagged.
The portfolio is marked to market every close; daily returns feed the statistics."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from equity_research.research import stats
from equity_research.research.execution import CostModel, fillable_value
from equity_research.research.risk import Order, PortfolioState, RiskManager
from equity_research.shortterm.bars import Bars


class MarketData:
    """Per-ticker arrays the simulator and the risk layer need, computed once (point-in-time)."""

    def __init__(self, universe: dict[str, Bars], sectors: dict[str, str] | None = None):
        self.bars = universe
        self.sectors = sectors or {}
        self.ordinals = {t: np.array([d.toordinal() for d in b.dates]) for t, b in universe.items()}
        self._cache: dict[str, dict[str, np.ndarray]] = {}

    def arrays(self, ticker: str) -> dict[str, np.ndarray]:
        if ticker not in self._cache:
            b = self.bars[ticker]
            from equity_research.shortterm.features import rolling, shift
            with np.errstate(divide="ignore", invalid="ignore"):
                ret = b.close / shift(b.close, 1) - 1
                self._cache[ticker] = {
                    "ret": ret,
                    "vol20": rolling(np.nan_to_num(ret), 20, np.std),
                    "dv20": rolling(b.close * b.volume, 20, np.mean),
                    "cs20": stats.corwin_schultz(b.high, b.low, 20),
                    "dollar_volume": b.close * b.volume,
                }
        return self._cache[ticker]

    def index(self, ticker: str, day: date) -> int | None:
        o = self.ordinals.get(ticker)
        if o is None:
            return None
        k = int(np.searchsorted(o, day.toordinal()))
        return k if k < len(o) and o[k] == day.toordinal() else None

    def last_index_before(self, ticker: str, day: date) -> int:
        return int(np.searchsorted(self.ordinals[ticker], day.toordinal(), side="right")) - 1

    def correlation(self, a: str, b: str, day: date, window: int = 60) -> float | None:
        ia, ib = self.last_index_before(a, day), self.last_index_before(b, day)
        if ia < window or ib < window:
            return None
        oa, ob = self.ordinals[a][ia - window + 1:ia + 1], self.ordinals[b][ib - window + 1:ib + 1]
        common, xa, xb = np.intersect1d(oa, ob, return_indices=True)
        if len(common) < window // 2:
            return None
        ra = self.arrays(a)["ret"][ia - window + 1:ia + 1][xa]
        rb = self.arrays(b)["ret"][ib - window + 1:ib + 1][xb]
        ok = np.isfinite(ra) & np.isfinite(rb)
        if ok.sum() < window // 2 or np.std(ra[ok]) == 0 or np.std(rb[ok]) == 0:
            return None
        return float(np.corrcoef(ra[ok], rb[ok])[0, 1])


@dataclass(frozen=True)
class ExitRule:
    horizon: int
    target: float | None = None
    stop: float | None = None


@dataclass
class Trade:
    ticker: str
    signal_date: date
    entry_date: date
    exit_date: date
    entry_value: float
    exit_value: float
    net: float
    reason: str
    partial: bool
    cost_entry: float
    cost_exit: float


@dataclass
class Position:
    ticker: str
    signal_date: date
    entry_date: date
    entry_index: int
    exit_index: int
    shares: float
    entry_value: float
    entry_price: float
    partial: bool
    cost_entry: float


@dataclass
class SimulationResult:
    dates: list[date]
    returns: np.ndarray
    exposure: np.ndarray
    trades: list[Trade]
    blocked: Counter
    cancelled: Counter
    no_trade_days: int
    signal_days: int
    traded_value: float
    data_ended: int = 0
    equity: np.ndarray = field(default_factory=lambda: np.array([]))

    def summary(self) -> dict:
        perf = stats.performance(self.returns)
        trades = stats.trade_stats([t.net for t in self.trades])
        years = len(self.returns) / 252 if len(self.returns) else float("nan")
        mean_equity = float(np.mean(self.equity)) if len(self.equity) else float("nan")
        return {**perf, **{f"trade_{k}": v for k, v in trades.items()},
                "exposure": float(np.mean(self.exposure)) if len(self.exposure) else float("nan"),
                "turnover": self.traded_value / mean_equity / years if years and mean_equity else float("nan"),
                "avg_cost": float(np.mean([t.cost_entry + t.cost_exit for t in self.trades])) if self.trades else float("nan"),
                "no_trade_days": self.no_trade_days, "signal_days": self.signal_days,
                "partial_fills": sum(t.partial for t in self.trades), "data_ended": self.data_ended}


def simulate(market: MarketData, picks: dict[date, list[tuple[str, float]]], calendar: list[date], rule: ExitRule,
             costs: CostModel, risk: RiskManager, top_n: int = 10, capital: float = 1e6) -> SimulationResult:
    """``picks``: per signal date the candidates (ticker, score), best first (more than ``top_n``
    may be given; the risk layer takes the best admissible ones)."""
    lim = risk.limits
    cash, positions = capital, []
    state = PortfolioState(capital, 0.0, {}, market.sectors)
    pending: list[Order] = []
    equity_prev, peak = capital, capital
    out_dates, rets, exposure, equity_series = [], [], [], []
    trades: list[Trade] = []
    blocked, cancelled = Counter(), Counter()
    traded_value, no_trade, signal_days, data_ended = 0.0, 0, 0, 0

    def close_position(p: Position, j: int, price: float, reason: str, day: date):
        nonlocal cash, traded_value
        a = market.arrays(p.ticker)
        gross_value = p.shares * price
        c = costs.per_side(gross_value, a["dv20"][j], a["vol20"][j], a["cs20"][j])
        proceeds = gross_value * (1 - c)
        cash += proceeds
        traded_value += gross_value
        trades.append(Trade(p.ticker, p.signal_date, p.entry_date, day, p.entry_value, proceeds,
                            proceeds / p.entry_value - 1, reason, p.partial, p.cost_entry, c))

    for k, day in enumerate(calendar):
        # A. fills at the open
        for o in pending:
            j = market.index(o.ticker, day)
            if j is None:
                cancelled["no bar on the fill day (halt or missing data)"] += 1
                continue
            b, a = market.bars[o.ticker], market.arrays(o.ticker)
            value = min(fillable_value(o.value, a["dollar_volume"][j], lim.max_participation), cash)
            if value < lim.min_order_value:
                cancelled["fill too small (volume or cash)"] += 1
                continue
            c = costs.per_side(value, o.dollar_volume, o.daily_vol, a["cs20"][j - 1] if j else np.nan)
            price = b.open[j] * (1 + c)
            positions.append(Position(o.ticker, o.signal_date, day, j, j + rule.horizon - 1, value / price, value,
                                      b.open[j], value < o.value * 0.999, c))
            cash -= value
            traded_value += value
        pending = []

        # B/C. intraday target/stop, time exits at the close, ended histories
        still = []
        for p in positions:
            b = market.bars[p.ticker]
            j = market.index(p.ticker, day)
            if j is None:
                if market.ordinals[p.ticker][-1] < day.toordinal():
                    last = len(b) - 1
                    close_position(p, last, b.close[last], "history ended (delisting or data gap)", day)
                    data_ended += 1
                    continue
                still.append(p)
                continue
            target = p.entry_price * (1 + rule.target) if rule.target else None
            stop = p.entry_price * (1 - rule.stop) if rule.stop else None
            later = j > p.entry_index
            exit_price, reason = None, ""
            if later and stop is not None and b.open[j] <= stop:
                exit_price, reason = b.open[j], "stop (gap below)"
            elif later and target is not None and b.open[j] >= target:
                exit_price, reason = b.open[j], "target (gap above)"
            else:
                hit_stop = stop is not None and b.low[j] <= stop
                hit_target = target is not None and b.high[j] >= target
                if hit_stop:
                    exit_price, reason = stop * (1 - costs.slippage_bps / 1e4 * costs.stress), "stop"
                elif hit_target:
                    exit_price, reason = target, "target"
            if exit_price is None and j >= p.exit_index:
                exit_price, reason = b.close[j], "time"
            if exit_price is not None:
                close_position(p, j, exit_price, reason, day)
            else:
                still.append(p)
        positions = still

        # D/E. mark to market and update the risk state
        invested = 0.0
        values = {}
        for p in positions:
            i = market.last_index_before(p.ticker, day)
            values[p.ticker] = values.get(p.ticker, 0.0) + p.shares * market.bars[p.ticker].close[i]
        invested = sum(values.values())
        equity = cash + invested
        r = equity / equity_prev - 1
        peak = max(peak, equity)
        out_dates.append(day)
        rets.append(r)
        exposure.append(invested / equity if equity > 0 else 0.0)
        equity_series.append(equity)
        equity_prev = equity
        state.equity, state.invested, state.positions = equity, invested, values
        state.drawdown, state.last_return, state.day = equity / peak - 1, r, k
        risk.update(state)

        # F. new orders for the next open
        candidates = picks.get(day, [])
        if candidates:
            signal_days += 1
            orders = []
            for ticker, score in candidates[:3 * top_n]:
                i = market.index(ticker, day)
                if i is None:
                    continue
                a = market.arrays(ticker)
                b = market.bars[ticker]
                spread = a["cs20"][i] if np.isfinite(a["cs20"][i]) else 2 * costs.half_spread(a["dv20"][i], None)
                orders.append(Order(ticker, day, score, equity / rule.horizon / top_n, float(b.traded_close[i]),
                                    float(a["dv20"][i]), float(a["vol20"][i]), float(spread),
                                    market.sectors.get(ticker, "unknown")))
            decision = risk.check(orders, state, equity / rule.horizon, slots=top_n)
            pending = decision.accepted
            for _, why in decision.blocked:
                blocked[why] += 1
            if not pending:
                no_trade += 1
        else:
            no_trade += 1

    return SimulationResult(out_dates, np.array(rets), np.array(exposure), trades, blocked, cancelled, no_trade,
                            signal_days, traded_value, data_ended, np.array(equity_series))
