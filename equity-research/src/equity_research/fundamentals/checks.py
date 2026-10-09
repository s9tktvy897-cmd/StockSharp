"""Consistency checks run after every analysis (CLAUDE.md section 5). A failed check is
reported, never corrected silently."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from equity_research.fundamentals.statements import AnnualStatements


@dataclass(frozen=True)
class CheckResult:
    name: str
    period_end: date | None
    passed: bool | None  # None: could not be checked
    detail: str


def balance_sheet(st: AnnualStatements, tolerance: float = 0.005) -> list[CheckResult]:
    results = []
    for year, assets in sorted(st.items.get("total_assets", {}).items()):
        liabilities = st.get("total_liabilities", year)
        equity = st.get("equity_including_nci", year) or st.get("equity", year)
        if liabilities and equity:
            other, label = liabilities.value + equity.value, "liabilities + equity"
        elif st.get("liabilities_and_equity", year):
            other, label = st.get("liabilities_and_equity", year).value, "LiabilitiesAndStockholdersEquity"
        else:
            results.append(CheckResult("balance_sheet", year, None, "no liabilities/equity totals reported"))
            continue
        gap = (other - assets.value) / assets.value
        results.append(CheckResult("balance_sheet", year, abs(gap) <= tolerance,
                                   f"assets {assets.value:,.0f} vs {label} {other:,.0f} ({gap:+.3%})"))
    return results


def share_jumps(st: AnnualStatements, threshold: float = 0.2) -> list[CheckResult]:
    series = st.series("diluted_shares")
    results = []
    for prev, cur in zip(series, series[1:]):
        change = cur.value / prev.value - 1
        results.append(CheckResult("share_jump", cur.period_end, abs(change) <= threshold,
                                   f"diluted shares {change:+.1%} y/y" +
                                   ("" if abs(change) <= threshold else " -- explain (split, issue, acquisition)")))
    return results


def capex_sign(st: AnnualStatements) -> list[CheckResult]:
    return [CheckResult("capex_sign", f.period_end, f.value >= 0, f"capex payments {f.value:,.0f} (expected >= 0)")
            for f in st.series("capex")]


def currencies(st: AnnualStatements) -> list[CheckResult]:
    found = {f.currency for values in st.items.values() for f in values.values() if f.currency}
    return [CheckResult("currency", None, len(found) <= 1, f"currencies: {', '.join(sorted(found)) or 'none'}")]


def run_all(st: AnnualStatements) -> list[CheckResult]:
    return balance_sheet(st) + share_jumps(st) + capex_sign(st) + currencies(st)
