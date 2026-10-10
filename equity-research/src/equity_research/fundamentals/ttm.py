"""Most recent figures from 10-Q filings: trailing twelve months (TTM) for flow items and the
latest balance sheet for stock items.

TTM = latest fiscal year + current year-to-date - prior-year year-to-date (EDGAR has no
discrete Q4, and YTD rows are the only way to bridge from the 10-K)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from equity_research.data.sec_edgar import QUARTERLY_FORMS, CompanyFacts, EdgarFact
from equity_research.fundamentals.concepts import ITEMS_BY_NAME, LINE_ITEMS, OPTIONAL_ITEMS
from equity_research.fundamentals.splits import StockSplit, adjust
from equity_research.fundamentals.statements import AnnualStatements
from equity_research.provenance import DerivedValue

DATE_SLACK = 7  # days; 52/53-week fiscal calendars shift period boundaries by a few days


def _close(a: date, b: date) -> bool:
    return abs((a - b).days) <= DATE_SLACK


def ttm(facts: CompanyFacts, item: str, as_of: date | None = None) -> DerivedValue:
    line = ITEMS_BY_NAME[item]
    if line.instant or line.share_basis:
        raise ValueError(f"TTM applies to summable flow items, not {item}")
    name, formula = f"ttm_{item}", "fiscal year + current YTD - prior-year YTD"
    latest_10k = max((f.period_end for f in facts.annual("Assets", as_of=as_of)), default=None)
    for concept in line.concepts:
        annual = facts.annual(concept, unit=line.unit, taxonomy=line.taxonomy, as_of=as_of)
        if not annual:
            continue
        fy = annual[-1]
        if latest_10k is not None and fy.period_end < latest_10k - timedelta(days=DATE_SLACK):
            return DerivedValue(name, None, line.unit, formula, (fy,), fy.period_end,
                                f"{item} last reported for fiscal year {fy.period_end}, not in the latest 10-K "
                                f"({latest_10k})")
        quarterly = [f for f in facts.history(concept, unit=line.unit, taxonomy=line.taxonomy, as_of=as_of)
                     if f.form in QUARTERLY_FORMS and f.period_start is not None]
        ytd = [f for f in quarterly if 0 < (f.period_start - fy.period_end).days <= DATE_SLACK]
        if not ytd:
            return DerivedValue(name, fy.value, line.unit, "latest fiscal year", (fy,), fy.period_end, None,
                                "no 10-Q after the latest 10-K; TTM = fiscal year")
        current = max(ytd, key=lambda f: (f.period_end, f.filed))
        length = (current.period_end - current.period_start).days
        prior = [f for f in quarterly if _close(f.period_start, fy.period_start) and f.period_end < fy.period_end
                 and abs((f.period_end - f.period_start).days - length) <= DATE_SLACK]
        if not prior:
            return DerivedValue(name, None, line.unit, formula, (fy, current), current.period_end,
                                f"prior-year YTD comparative for {current.period_end} not found ({concept})")
        previous = max(prior, key=lambda f: f.filed)
        return DerivedValue(name, fy.value + current.value - previous.value, line.unit, formula,
                            (fy, current, previous), current.period_end)
    return DerivedValue(name, None, line.unit, formula, (), None, f"{item} not reported")


@dataclass
class LatestBalance:
    period_end: date
    items: dict[str, EdgarFact | DerivedValue]

    def get(self, item: str) -> EdgarFact | DerivedValue:
        return self.items[item]


def _instants(facts: CompanyFacts, concept: str, unit: str, taxonomy: str, as_of: date | None) -> list[EdgarFact]:
    return (facts.annual(concept, unit=unit, taxonomy=taxonomy, as_of=as_of)
            + facts.quarterly(concept, unit=unit, taxonomy=taxonomy, as_of=as_of))


DROPPED_AFTER_DAYS = 730


def latest_balance(facts: CompanyFacts, st: AnnualStatements, as_of: date | None = None) -> LatestBalance:
    """Balance-sheet items at the newest date with reported total assets (10-K or 10-Q). An item
    absent on that date is missing, except an optional component (debt part, securities, minority
    interest) that no 10-K ever reports, which counts as 0 with a note, or one last reported more
    than ``DROPPED_AFTER_DAYS`` before that date (dropped from the statements, typically because it
    became nil): 0 as a labelled assumption naming the last reported date."""
    assets = _instants(facts, "Assets", "USD", "us-gaap", as_of)
    if not assets:
        raise ValueError("no total assets reported")
    when = max(f.period_end for f in assets)
    items: dict[str, EdgarFact | DerivedValue] = {}
    for line in (item for item in LINE_ITEMS if item.instant):
        found = None
        for concept in line.concepts:
            values = _instants(facts, concept, line.unit, line.taxonomy, as_of)
            on_date = [f for f in values if f.period_end == when]
            if on_date:
                found = max(on_date, key=lambda f: f.filed)
                break
        last = max((f.period_end for concept in line.concepts
                    for f in _instants(facts, concept, line.unit, line.taxonomy, as_of)), default=None)
        latest_value = None
        if last is not None:
            latest_value = max((f for concept in line.concepts for f in _instants(facts, concept, line.unit,
                                                                                 line.taxonomy, as_of)
                                if f.period_end == last), key=lambda f: f.filed).value
        if found is not None:
            items[line.name] = found
        elif line.name in OPTIONAL_ITEMS and latest_value == 0:
            items[line.name] = DerivedValue(line.name, 0.0, line.unit, f"{line.name} last reported as 0 on {last}", (),
                                            when, None, f"{line.name} last reported as 0 on {last}, not reported since")
        elif line.name in OPTIONAL_ITEMS and last is not None and (when - last).days > DROPPED_AFTER_DAYS:
            items[line.name] = DerivedValue(
                line.name, 0.0, line.unit, f"{line.name} last reported {last}", (), when, None,
                f"{line.name} last reported {last}, not in any filing since: taken as 0 (assumption: line "
                "dropped because it became nil; check the latest 10-K)")
        elif line.name not in OPTIONAL_ITEMS or st.items.get(line.name):
            items[line.name] = DerivedValue(line.name, None, line.unit, line.name, (), when,
                                            f"{line.name} not reported on {when}")
        else:
            items[line.name] = DerivedValue(line.name, 0.0, line.unit, f"{line.name} never reported", (), when, None,
                                            f"{line.name} never reported, taken as 0")
    return LatestBalance(when, items)


def latest_share_count(facts: CompanyFacts, splits: list[StockSplit], as_of: date | None = None,
                       concept: str = "WeightedAverageNumberOfDilutedSharesOutstanding",
                       taxonomy: str = "us-gaap") -> EdgarFact | None:
    """Most recent reported share count (default: diluted weighted average of the latest quarter
    or year), adjusted onto the latest split basis."""
    candidates = [f for f in facts.history(concept, unit="shares", taxonomy=taxonomy, as_of=as_of)
                  if f.period_start is None or (f.period_end - f.period_start).days < 100]
    candidates += facts.annual(concept, unit="shares", taxonomy=taxonomy, as_of=as_of)
    if not candidates:
        return None
    latest = max(candidates, key=lambda f: (f.period_end, f.filed))
    return adjust(latest, "shares", splits)
