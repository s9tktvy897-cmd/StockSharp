"""Normalized annual statements built from SEC company facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from equity_research.data.sec_edgar import CompanyFacts, EdgarFact
from equity_research.fundamentals.concepts import LINE_ITEMS, SPLIT_EVIDENCE_CONCEPTS, LineItem
from equity_research.fundamentals.splits import AmbiguousSplitError, StockSplit, adjust, detect_splits

TAG_DISAGREEMENT = 0.005


@dataclass
class AnnualStatements:
    cik: str
    entity_name: str
    as_of: date | None
    items: dict[str, dict[date, EdgarFact]]
    splits: list[StockSplit]
    issues: list[str] = field(default_factory=list)

    @property
    def fiscal_years(self) -> list[date]:
        """Fiscal year ends: the period ends of reported revenue (or of any duration item)."""
        years = set(self.items.get("revenue", {}))
        if not years:
            years = {d for item in LINE_ITEMS if not item.instant for d in self.items.get(item.name, {})}
        return sorted(years)

    def get(self, item: str, year_end: date) -> EdgarFact | None:
        return self.items.get(item, {}).get(year_end)

    def series(self, item: str) -> list[EdgarFact]:
        values = self.items.get(item, {})
        return [values[d] for d in sorted(values)]


def _merge(item: LineItem, facts: CompanyFacts, as_of, splits, issues) -> dict[date, EdgarFact]:
    merged: dict[date, EdgarFact] = {}
    used: dict[str, list[date]] = {}
    for concept in item.concepts:
        for fact in facts.annual(concept, unit=item.unit, taxonomy=item.taxonomy, as_of=as_of):
            if item.share_basis:
                try:
                    fact = adjust(fact, item.share_basis, splits)
                except AmbiguousSplitError as error:
                    issues.append(f"{item.name} {fact.period_end}: dropped, {error}")
                    continue
            chosen = merged.get(fact.period_end)
            if chosen is None:
                merged[fact.period_end] = fact
                used.setdefault(concept, []).append(fact.period_end)
            elif chosen.value and abs(fact.value - chosen.value) / abs(chosen.value) > TAG_DISAGREEMENT:
                issues.append(f"{item.name} {fact.period_end}: tags differ, kept {chosen.value:,.0f} "
                              f"({chosen.reference}) over {fact.value:,.0f} ({concept})")
    if len(used) > 1:
        spans = ", ".join(f"{c} {min(d)}..{max(d)}" for c, d in used.items())
        issues.append(f"{item.name}: reported under several tags ({spans})")
    return merged


def build_annual(facts: CompanyFacts, as_of: date | None = None, adjust_splits: bool = True,
                 items: tuple[LineItem, ...] = LINE_ITEMS) -> AnnualStatements:
    splits: list[StockSplit] = []
    if adjust_splits:
        history = [f for c in SPLIT_EVIDENCE_CONCEPTS for f in facts.history(c, unit="shares", as_of=as_of)]
        splits = detect_splits(history)
    issues = [f"stock split x{s.factor} between filings of {s.last_filed_before} and {s.first_filed_after}; "
              f"share counts and per-share values filed before are adjusted (evidence: {s.evidence})"
              for s in splits]
    merged = {item.name: _merge(item, facts, as_of, splits, issues) for item in items}
    return AnnualStatements(facts.cik, facts.entity_name, as_of, merged, splits, issues)
