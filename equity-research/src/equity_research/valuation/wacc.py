"""Cost of capital: CAPM, Hamada (un)levering and WACC. Pure functions."""

from __future__ import annotations

from equity_research.fundamentals.ratios import UndefinedRatioError


def cost_of_equity(risk_free: float, beta: float, equity_risk_premium: float) -> float:
    """CAPM: r_e = r_f + beta * ERP."""
    return risk_free + beta * equity_risk_premium


def relever_beta(unlevered: float, debt_to_equity: float, tax_rate: float) -> float:
    """Hamada: beta_L = beta_U * (1 + (1 - t) * D/E)."""
    return unlevered * (1 + (1 - tax_rate) * debt_to_equity)


def unlever_beta(levered: float, debt_to_equity: float, tax_rate: float) -> float:
    return levered / (1 + (1 - tax_rate) * debt_to_equity)


def wacc(equity: float, debt: float, cost_of_equity: float, cost_of_debt: float, tax_rate: float) -> float:
    """WACC = E/V * r_e + D/V * r_d * (1 - t), with market (or book proxy) values E and D."""
    if equity < 0 or debt < 0 or equity + debt <= 0:
        raise UndefinedRatioError(f"WACC needs non-negative E and D with E + D > 0 (E={equity}, D={debt})")
    value = equity + debt
    return equity / value * cost_of_equity + debt / value * cost_of_debt * (1 - tax_rate)
