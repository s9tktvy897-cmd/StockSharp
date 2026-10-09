"""Pure ratio formulas (no I/O). Each raises UndefinedRatioError instead of returning a
meaningless number (division by zero, negative bases)."""

from __future__ import annotations


class UndefinedRatioError(ValueError):
    pass


def safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        raise UndefinedRatioError("denominator is zero")
    return numerator / denominator


def cagr(start: float, end: float, years: float) -> float:
    """Compound annual growth rate; undefined unless both ends are positive."""
    if start <= 0 or end <= 0:
        raise UndefinedRatioError(f"CAGR needs positive start and end (start={start}, end={end})")
    if years <= 0:
        raise UndefinedRatioError("CAGR needs a positive number of years")
    return (end / start) ** (1 / years) - 1


def effective_tax_rate(income_tax: float, pretax_income: float) -> float:
    if pretax_income <= 0:
        raise UndefinedRatioError("effective tax rate undefined for non-positive pretax income")
    return income_tax / pretax_income


def nopat(ebit: float, tax_rate: float) -> float:
    return ebit * (1 - tax_rate)


def invested_capital(equity: float, debt: float, cash: float, investments: float) -> float:
    """Financing view: equity + debt - cash - marketable securities (non-operating)."""
    return equity + debt - cash - investments


def return_on_average(numerator: float, begin: float, end: float) -> float:
    average = (begin + end) / 2
    if average <= 0:
        raise UndefinedRatioError(f"average base is not positive ({average})")
    return numerator / average


def roic(nopat_value: float, ic_begin: float, ic_end: float) -> float:
    return return_on_average(nopat_value, ic_begin, ic_end)


def accruals_ratio(net_income: float, operating_cash_flow: float, assets_begin: float, assets_end: float) -> float:
    """Sloan (1996) balance-free variant: (net income - CFO) / average total assets."""
    return return_on_average(net_income - operating_cash_flow, assets_begin, assets_end)


def net_debt(debt: float, cash: float, short_term_investments: float) -> float:
    return debt - cash - short_term_investments


def net_debt_to_ebitda(net_debt_value: float, ebitda: float) -> float:
    if ebitda <= 0:
        raise UndefinedRatioError("net debt / EBITDA undefined for non-positive EBITDA")
    return net_debt_value / ebitda


def interest_coverage(ebit: float, interest_expense: float) -> float:
    if interest_expense <= 0:
        raise UndefinedRatioError("interest coverage undefined without positive interest expense")
    return ebit / interest_expense
