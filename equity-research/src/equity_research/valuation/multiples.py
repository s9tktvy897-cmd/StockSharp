"""Market multiples (pure). A multiple with a non-positive denominator is None, not a number."""

from __future__ import annotations


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


def market_multiples(price: float, shares: float, debt: float, cash: float, investments: float,
                     minority_interest: float, revenue: float, ebit: float, net_income: float,
                     fcf: float) -> dict[str, float | None]:
    market_cap = price * shares
    enterprise_value = market_cap + debt + minority_interest - cash - investments
    return {
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
        "ev_sales": _ratio(enterprise_value, revenue),
        "ev_ebit": _ratio(enterprise_value, ebit),
        "pe": _ratio(market_cap, net_income),
        "p_fcf": _ratio(market_cap, fcf),
        "fcf_yield": fcf / market_cap if market_cap > 0 else None,
    }
