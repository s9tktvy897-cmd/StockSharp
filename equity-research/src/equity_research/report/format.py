"""Dutch number formatting for reports: 1.234,5 / 8,7% / 10,8x; missing values as a dash."""

from __future__ import annotations

import math

MISSING = "–"


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def nl(x: float | None, decimals: int = 1) -> str:
    if not _ok(x):
        return MISSING
    text = f"{x:,.{decimals}f}"
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def bn(x: float | None, decimals: int = 1) -> str:
    """USD billions (mld)."""
    return nl(x / 1e9, decimals) if _ok(x) else MISSING


def pct(x: float | None, decimals: int = 1) -> str:
    return nl(x * 100, decimals) + "%" if _ok(x) else MISSING


def multiple(x: float | None, decimals: int = 1) -> str:
    return nl(x, decimals) + "x" if _ok(x) else MISSING


def by_unit(x: float | None, unit: str) -> str:
    if unit == "ratio":
        return pct(x)
    if unit == "multiple":
        return multiple(x)
    if unit == "USD/shares":
        return nl(x, 2)
    if unit == "shares":
        return bn(x, 3)
    return bn(x)
