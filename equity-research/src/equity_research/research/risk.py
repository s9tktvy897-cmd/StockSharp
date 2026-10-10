"""Risk layer, separate from any prediction model. Every limit is configurable and checked
automatically; an order that breaks a limit is blocked (never resized past the limit silently), and
the reason is recorded. No rule here guarantees against large losses: stops can gap, correlations
change, and the limits only bound what the portfolio may *add*.

Sizing: a position gets the smaller of its share of today's sleeve, ``max_position`` of equity,
and ``risk_per_position`` of equity divided by the stock's daily volatility (volatile stocks get
smaller positions). Cash is a valid position: with no admissible order nothing is bought."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class RiskLimits:
    max_position: float = 0.10          # of equity
    max_gross_exposure: float = 1.00    # long only, no leverage
    max_sector: float = 0.30            # of equity per SIC major group (2 digits); unknown SIC = one group
    max_correlation: float = 0.80       # 60-day return correlation with any held position
    min_dollar_volume: float = 5e6      # 20-day average
    min_price: float = 2.0              # price actually traded
    max_spread: float = 0.02            # estimated round-trip spread (Corwin-Schultz or tier)
    max_participation: float = 0.01     # of the fill day's dollar volume
    risk_per_position: float = 0.005    # position value x daily volatility <= this x equity
    min_order_value: float = 500.0
    daily_loss_limit: float = -0.03     # a day worse than this blocks new orders the next day
    drawdown_limit: float = -0.20       # below this drawdown no new orders for ``cooloff_days``
    cooloff_days: int = 20


@dataclass(frozen=True)
class Order:
    ticker: str
    signal_date: date
    score: float
    value: float          # requested value in currency
    price: float          # traded close on the signal day
    dollar_volume: float
    daily_vol: float
    spread: float         # estimated round-trip spread
    sector: str


@dataclass
class PortfolioState:
    equity: float
    invested: float
    positions: dict[str, float]               # ticker -> market value
    sector_of: dict[str, str]
    drawdown: float = 0.0
    last_return: float = 0.0
    blocked_until: int = -1                   # day index until which new orders are blocked
    day: int = 0
    kill_switches: int = 0                    # times the drawdown limit stopped new orders


@dataclass
class Decision:
    accepted: list[Order] = field(default_factory=list)
    blocked: list[tuple[Order | None, str]] = field(default_factory=list)


class RiskManager:
    def __init__(self, limits: RiskLimits | None = None, correlation=None):
        self.limits = limits or RiskLimits()
        self.correlation = correlation  # callable(ticker_a, ticker_b, signal_date) -> float | None

    def update(self, state: PortfolioState) -> str | None:
        """Called after each close: sets the block on new orders after a breach. Returns
        "drawdown" when the drawdown limit fires (the simulator then measures the drawdown again
        from the restart after the cool-off, as a human review would restart the strategy)."""
        lim = self.limits
        fired = None
        if state.drawdown <= lim.drawdown_limit and state.day > state.blocked_until:
            state.blocked_until = state.day + lim.cooloff_days
            state.kill_switches += 1
            fired = "drawdown"
        if state.last_return <= lim.daily_loss_limit:
            state.blocked_until = max(state.blocked_until, state.day + 1)
        return fired

    def size(self, order: Order, equity: float, sleeve_value: float, n_orders: int) -> float:
        lim = self.limits
        share = sleeve_value / max(n_orders, 1)
        # zero volatility (a flat price) puts no risk cap on the size; unknown volatility is blocked in check()
        by_risk = lim.risk_per_position * equity / order.daily_vol if order.daily_vol > 0 else float("inf")
        return max(0.0, min(share, lim.max_position * equity, by_risk))

    def check(self, orders: list[Order], state: PortfolioState, sleeve_value: float,
              slots: int | None = None) -> Decision:
        """Admissible orders, best first, at most ``slots`` (the sleeve is split over ``slots``)."""
        lim = self.limits
        slots = slots or len(orders)
        out = Decision()
        if state.day <= state.blocked_until:
            out.blocked = [(o, "risk block (daily loss or drawdown limit)") for o in orders] or \
                [(None, "risk block (daily loss or drawdown limit)")]
            return out
        invested = state.invested
        sectors: dict[str, float] = {}
        for t, v in state.positions.items():
            sectors[state.sector_of.get(t, "unknown")] = sectors.get(state.sector_of.get(t, "unknown"), 0.0) + v
        held = list(state.positions)
        for o in orders:
            if len(out.accepted) >= slots:
                break
            reason = None
            if o.ticker in state.positions:
                reason = "already held"
            elif not o.price >= lim.min_price:
                reason = "price below minimum"
            elif not o.dollar_volume >= lim.min_dollar_volume:
                reason = "dollar volume below minimum"
            elif not (math.isfinite(o.spread) and o.spread <= lim.max_spread):
                reason = "spread above maximum"
            elif not math.isfinite(o.daily_vol):
                reason = "volatility unknown"
            if reason:
                out.blocked.append((o, reason))
                continue
            value = min(self.size(o, state.equity, sleeve_value, slots), o.value)
            if invested + value > lim.max_gross_exposure * state.equity:
                value = max(0.0, lim.max_gross_exposure * state.equity - invested)
            sector_now = sectors.get(o.sector, 0.0)
            if sector_now + value > lim.max_sector * state.equity:
                value = max(0.0, lim.max_sector * state.equity - sector_now)
            if value < lim.min_order_value:
                out.blocked.append((o, "no room within exposure, sector or size limits"))
                continue
            if self.correlation is not None:
                too_close = next((h for h in held if (c := self.correlation(o.ticker, h, o.signal_date)) is not None
                                  and c > lim.max_correlation), None)
                if too_close:
                    out.blocked.append((o, f"correlation with {too_close} above maximum"))
                    continue
            out.accepted.append(Order(o.ticker, o.signal_date, o.score, value, o.price, o.dollar_volume, o.daily_vol,
                                      o.spread, o.sector))
            invested += value
            sectors[o.sector] = sector_now + value
            held.append(o.ticker)
        return out
