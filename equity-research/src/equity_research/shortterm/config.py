"""Settings of the short-term engine. Every threshold is an assumption with its reason."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Costs:
    """Per side, in basis points. Half-spread by 20-day average dollar volume (assumption:
    typical quoted half-spreads for US equities by liquidity tier; tune with real quotes)."""

    commission_bps: float = 0.0  # most US retail brokers charge no commission on stocks
    slippage_bps: float = 10.0
    half_spread_tiers: tuple[tuple[float, float], ...] = ((50e6, 5.0), (10e6, 15.0), (0.0, 30.0))

    def per_side(self, dollar_volume: float) -> float:
        for floor, bps in self.half_spread_tiers:
            if dollar_volume >= floor:
                return (self.commission_bps + self.slippage_bps + bps) / 1e4
        return (self.commission_bps + self.slippage_bps + self.half_spread_tiers[-1][1]) / 1e4


@dataclass(frozen=True)
class Config:
    target: float = 0.10            # the user's goal: +10%
    drop: float = 0.10              # "sharp fall" = low at least 10% under entry
    horizons: tuple[int, ...] = (1, 2)
    min_price: float = 2.0          # sub-$2 stocks: very wide spreads, often untradable size
    min_dollar_volume: float = 5e6  # 20-day average; below this our own order moves the price
    min_history: int = 60           # trading days needed for the features
    max_gap_days: int = 5           # calendar days between bars; a longer gap = halt or missing data
    top_n: int = 10
    stop_loss: float | None = None  # None: exit at the horizon close unless the target is hit
    same_bar_stop_first: bool = True  # if target and stop fall in one bar, assume the stop came first
    costs: Costs = field(default_factory=Costs)
