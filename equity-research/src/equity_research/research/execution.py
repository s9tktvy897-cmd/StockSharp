"""Transaction cost and fill model (per side, as a fraction of the price).

cost = commission + slippage + half-spread + market impact, times a stress multiplier.
- half-spread: the larger of a liquidity tier (by 20-day dollar volume) and half the stock's own
  Corwin-Schultz high-low spread estimate (``stats.corwin_schultz``), so volatile small caps pay more;
- impact: square-root law, ``IMPACT_COEF * daily volatility * sqrt(order value / daily dollar volume)``;
- fills: at most ``max_participation`` of the fill day's dollar volume (the rest is not filled); no
  bar on the fill day (halt, missing data) = order not filled.
All parameters are assumptions, varied in the cost-stress scenarios."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

IMPACT_COEF = 0.5  # square-root impact coefficient (typical estimates 0.3-1.0; an assumption)


@dataclass(frozen=True)
class CostModel:
    commission_bps: float = 0.0
    slippage_bps: float = 10.0
    tiers: tuple[tuple[float, float], ...] = ((50e6, 5.0), (10e6, 15.0), (0.0, 30.0))  # (min $ volume, half-spread bp)
    impact_coef: float = IMPACT_COEF
    stress: float = 1.0  # multiplier on everything except commission
    max_participation: float = 0.01

    def half_spread(self, dollar_volume: float, cs_spread: float | None) -> float:
        tier = next((bps for floor, bps in self.tiers if dollar_volume >= floor), self.tiers[-1][1]) / 1e4
        own = cs_spread / 2 if cs_spread is not None and math.isfinite(cs_spread) else 0.0
        return max(tier, own)

    def per_side(self, order_value: float, dollar_volume: float, daily_vol: float, cs_spread: float | None) -> float:
        participation = order_value / dollar_volume if dollar_volume > 0 else 1.0
        vol = daily_vol if math.isfinite(daily_vol) else 0.0
        impact = self.impact_coef * vol * math.sqrt(max(participation, 0.0))
        variable = self.slippage_bps / 1e4 + self.half_spread(dollar_volume, cs_spread) + impact
        return self.commission_bps / 1e4 + self.stress * variable

    def stressed(self, factor: float) -> "CostModel":
        return replace(self, stress=factor)


def fillable_value(order_value: float, fill_day_dollar_volume: float, max_participation: float) -> float:
    """Part of an order that can be filled on a day with this dollar volume."""
    if not fill_day_dollar_volume > 0:
        return 0.0
    return min(order_value, max_participation * fill_day_dollar_volume)
