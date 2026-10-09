"""Stock splits inferred from the filings themselves: when a later filing restates the share
count of the same period by an exact ratio (2, 4, 3/2, 1/10, ...), a split happened between
the two filing dates. Only filings visible on the as-of date are used, so no look-ahead."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from itertools import groupby

from equity_research.data.sec_edgar import EdgarFact

MIN_SPLIT_CHANGE = 0.2  # ratios within 20% of 1 are restatements, not splits


class AmbiguousSplitError(ValueError):
    pass


@dataclass(frozen=True)
class StockSplit:
    factor: Fraction  # new shares per old share: 4 = 4-for-1, 1/10 = 1-for-10 reverse split
    last_filed_before: date  # latest filing known to be on the pre-split basis
    first_filed_after: date  # earliest filing known to be on the post-split basis
    evidence: str


# Split ratios seen in practice besides whole numbers (3-for-2, 5-for-4, 5-for-2, 4-for-3).
FRACTIONAL_SPLITS = (Fraction(3, 2), Fraction(5, 4), Fraction(5, 2), Fraction(4, 3))


def _split_ratio(old: float, new: float, tolerance: float) -> Fraction | None:
    """The common split ratio within ``tolerance`` of new/old, or None (a restatement or noise).
    Comparatives are sometimes restated by a few tenths of a percent besides the split itself."""
    if old <= 0 or new <= 0:
        return None
    ratio = new / old
    if abs(ratio - 1) <= MIN_SPLIT_CHANGE:
        return None
    forward = ratio if ratio > 1 else 1 / ratio
    candidates = (Fraction(round(forward)),) + FRACTIONAL_SPLITS
    for candidate in candidates:
        if candidate > 1 and abs(float(candidate) - forward) / forward <= tolerance:
            return candidate if ratio > 1 else 1 / candidate
    return None


def detect_splits(history: list[EdgarFact], tolerance: float = 0.02) -> list[StockSplit]:
    def period(f: EdgarFact):
        return f.period_start or date.min, f.period_end

    splits: list[StockSplit] = []
    for _, group in groupby(sorted(history, key=lambda f: (period(f), f.filed, f.accession)), key=period):
        reports = list(group)
        for old, new in zip(reports, reports[1:]):
            if old.filed == new.filed or old.value is None or new.value is None:
                continue
            factor = _split_ratio(old.value, new.value, tolerance)
            if factor is None:
                continue
            evidence = f"{old.period_end}: {old.value:,.0f} ({old.accession}) -> {new.value:,.0f} ({new.accession})"
            for i, split in enumerate(splits):
                low, high = max(split.last_filed_before, old.filed), min(split.first_filed_after, new.filed)
                if split.factor == factor and low < high:
                    splits[i] = StockSplit(factor, low, high, split.evidence + "; " + evidence)
                    break
            else:
                splits.append(StockSplit(factor, old.filed, new.filed, evidence))
    return sorted(splits, key=lambda s: s.last_filed_before)


def cumulative_factor(filed: date, splits: list[StockSplit]) -> Fraction:
    """Factor that brings a value filed on ``filed`` onto the latest share basis."""
    factor = Fraction(1)
    for split in splits:
        if filed <= split.last_filed_before:
            factor *= split.factor
        elif filed < split.first_filed_after:
            raise AmbiguousSplitError(
                f"filing of {filed} lies between {split.last_filed_before} and {split.first_filed_after} "
                f"(split {split.factor}); basis unknown")
    return factor


def adjust(fact: EdgarFact, basis: str, splits: list[StockSplit]) -> EdgarFact:
    factor = cumulative_factor(fact.filed, splits)
    if factor == 1 or fact.value is None:
        return fact
    value = fact.value * float(factor) if basis == "shares" else fact.value / float(factor)
    return dataclasses.replace(fact, value=value, reference=f"{fact.reference} split-adjusted x{factor}")
