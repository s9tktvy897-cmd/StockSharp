"""Two-stage FCFF DCF (pure, no I/O).

Stage 1: ``high_growth_years`` at ``revenue_growth``, then ``fade_years`` fading linearly to
``terminal_growth``. FCFF = EBIT * (1 - t) + D&A - capex - change in NWC, with D&A, capex and NWC
as shares of revenue. Terminal value (Gordon) uses FCFF_{n+1} = NOPAT_{n+1} * (1 - g / RONIC):
the reinvestment needed to grow at g when new capital earns RONIC. Cash flows fall one year
apart starting one year after ``base_period_end`` and are discounted to ``valuation_date``."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date

from equity_research.fundamentals.ratios import UndefinedRatioError


@dataclass(frozen=True)
class DcfInputs:
    base_revenue: float
    base_period_end: date
    valuation_date: date
    revenue_growth: float
    high_growth_years: int
    fade_years: int
    ebit_margin: float
    tax_rate: float
    da_pct_revenue: float
    capex_pct_revenue: float
    nwc_pct_revenue: float
    terminal_growth: float
    ronic: float
    wacc: float


@dataclass(frozen=True)
class EquityBridge:
    cash: float
    investments: float  # marketable securities and other non-operating assets
    debt: float
    minority_interest: float
    diluted_shares: float


@dataclass(frozen=True)
class Projection:
    year: int
    growth: float
    revenue: float
    ebit: float
    nopat: float
    da: float
    capex: float
    delta_nwc: float
    fcff: float
    discount_factor: float

    @property
    def present_value(self) -> float:
        return self.fcff * self.discount_factor


@dataclass(frozen=True)
class DcfResult:
    projections: list[Projection]
    terminal_fcff: float
    terminal_value: float
    pv_terminal: float
    enterprise_value: float
    equity_value: float
    value_per_share: float
    terminal_share_of_ev: float
    implied_exit_ev_ebit: float


def growth_path(revenue_growth: float, terminal_growth: float, high_growth_years: int, fade_years: int) -> list[float]:
    fade = [revenue_growth + (terminal_growth - revenue_growth) * k / fade_years for k in range(1, fade_years + 1)]
    return [revenue_growth] * high_growth_years + fade


def gordon_terminal_value(next_cash_flow: float, wacc: float, growth: float) -> float:
    if wacc <= growth:
        raise UndefinedRatioError(f"WACC ({wacc:.2%}) must exceed terminal growth ({growth:.2%})")
    return next_cash_flow / (wacc - growth)


def value(inputs: DcfInputs, bridge: EquityBridge) -> DcfResult:
    i = inputs
    if i.high_growth_years + i.fade_years < 1:
        raise UndefinedRatioError("forecast needs at least one year")
    if i.ronic <= 0 or i.terminal_growth >= i.ronic:
        raise UndefinedRatioError(f"terminal growth ({i.terminal_growth:.2%}) must stay below RONIC ({i.ronic:.2%})")
    if bridge.diluted_shares <= 0:
        raise UndefinedRatioError("diluted share count must be positive")
    elapsed = (i.valuation_date - i.base_period_end).days / 365.25
    if not 0 <= elapsed < 1:
        raise UndefinedRatioError(f"valuation date must fall within a year after the base period ({elapsed:.2f} years)")

    projections, revenue = [], i.base_revenue
    for year, growth in enumerate(growth_path(i.revenue_growth, i.terminal_growth, i.high_growth_years, i.fade_years), 1):
        previous, revenue = revenue, revenue * (1 + growth)
        ebit = revenue * i.ebit_margin
        nopat = ebit * (1 - i.tax_rate)
        da, capex = revenue * i.da_pct_revenue, revenue * i.capex_pct_revenue
        delta_nwc = (revenue - previous) * i.nwc_pct_revenue
        projections.append(Projection(year, growth, revenue, ebit, nopat, da, capex, delta_nwc,
                                      nopat + da - capex - delta_nwc, (1 + i.wacc) ** -(year - elapsed)))

    last = projections[-1]
    terminal_fcff = last.nopat * (1 + i.terminal_growth) * (1 - i.terminal_growth / i.ronic)
    terminal_value = gordon_terminal_value(terminal_fcff, i.wacc, i.terminal_growth)
    pv_terminal = terminal_value * last.discount_factor
    enterprise_value = sum(p.present_value for p in projections) + pv_terminal
    equity_value = enterprise_value + bridge.cash + bridge.investments - bridge.debt - bridge.minority_interest
    return DcfResult(
        projections, terminal_fcff, terminal_value, pv_terminal, enterprise_value, equity_value,
        equity_value / bridge.diluted_shares, pv_terminal / enterprise_value,
        terminal_value / last.ebit if last.ebit > 0 else float("nan"),
    )


def sensitivity(inputs: DcfInputs, bridge: EquityBridge, waccs: list[float], growths: list[float]) -> dict:
    """Value per share for each (WACC, terminal growth); None where the model refuses to compute."""
    grid = {}
    for w in waccs:
        for g in growths:
            try:
                grid[(w, g)] = value(dataclasses.replace(inputs, wacc=w, terminal_growth=g), bridge).value_per_share
            except UndefinedRatioError:
                grid[(w, g)] = None
    return grid


def implied_growth(inputs: DcfInputs, bridge: EquityBridge, price: float, low: float = -0.5, high: float = 1.0,
                   tolerance: float = 1e-9) -> float:
    """Reverse DCF: the stage-1 revenue growth at which value per share equals ``price``."""
    def gap(growth: float) -> float:
        return value(dataclasses.replace(inputs, revenue_growth=growth), bridge).value_per_share - price

    gap_low, gap_high = gap(low), gap(high)
    if gap_low * gap_high > 0:
        raise UndefinedRatioError(f"no stage-1 growth in [{low:.0%}, {high:.0%}] reproduces the price {price:,.2f}")
    for _ in range(200):
        middle = (low + high) / 2
        gap_middle = gap(middle)
        if abs(high - low) < tolerance:
            break
        if gap_low * gap_middle <= 0:
            high = middle
        else:
            low, gap_low = middle, gap_middle
    return (low + high) / 2
