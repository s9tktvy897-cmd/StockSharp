"""Market statistics from price series (pure): returns, beta, volatility, drawdown."""

from __future__ import annotations

import math
from collections.abc import Sequence

from equity_research.provenance import SourcedValue


def simple_returns(prices: Sequence[float]) -> list[float]:
    return [b / a - 1 for a, b in zip(prices, prices[1:])]


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def beta(stock_returns: Sequence[float], market_returns: Sequence[float]) -> float:
    """OLS slope of stock on market returns: cov(s, m) / var(m)."""
    if len(stock_returns) != len(market_returns) or len(stock_returns) < 2:
        raise ValueError("beta needs two equally long return series with at least 2 observations")
    ms, mm = _mean(stock_returns), _mean(market_returns)
    covariance = sum((s - ms) * (m - mm) for s, m in zip(stock_returns, market_returns))
    variance = sum((m - mm) ** 2 for m in market_returns)
    if variance == 0:
        raise ValueError("market returns have zero variance")
    return covariance / variance


def annualized_volatility(returns: Sequence[float], periods_per_year: int) -> float:
    mean = _mean(returns)
    sample_variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(sample_variance * periods_per_year)


def max_drawdown(prices: Sequence[float]) -> float:
    peak, worst = prices[0], 0.0
    for price in prices:
        peak = max(peak, price)
        worst = min(worst, price / peak - 1)
    return worst


def month_end_closes(prices: Sequence[SourcedValue]) -> dict[tuple[int, int], SourcedValue]:
    closes: dict[tuple[int, int], SourcedValue] = {}
    for p in sorted(prices, key=lambda p: p.period_end):
        if p.value is not None:
            closes[(p.period_end.year, p.period_end.month)] = p
    return closes


def aligned_monthly_returns(stock: Sequence[SourcedValue], market: Sequence[SourcedValue],
                            months: int = 60) -> tuple[list[float], list[float]]:
    """Monthly returns over the last ``months`` months that both series cover, consecutive months only."""
    s, m = month_end_closes(stock), month_end_closes(market)
    common = sorted(set(s) & set(m))[-(months + 1):]
    stock_returns, market_returns = [], []
    for a, b in zip(common, common[1:]):
        if (b[0] * 12 + b[1]) - (a[0] * 12 + a[1]) != 1:
            continue
        stock_returns.append(s[b].value / s[a].value - 1)
        market_returns.append(m[b].value / m[a].value - 1)
    return stock_returns, market_returns
