"""SEC EDGAR: ticker -> CIK, company profile (SIC) and XBRL company facts, point-in-time."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from equity_research.data.cache import DiskCache
from equity_research.data.http import HttpClient
from equity_research.provenance import SourcedValue

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
MAX_AGE = timedelta(days=1)

ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})
QUARTERLY_FORMS = frozenset({"10-Q", "10-Q/A"})
# Duration windows in days; a 52/53-week fiscal year runs 357-371 days, a 13/14-week quarter 84-98.
ANNUAL_DAYS = range(350, 380)
QUARTER_DAYS = range(80, 100)


class UnknownTickerError(LookupError):
    pass


def format_cik(cik: int | str) -> str:
    text = str(cik).strip().upper().removeprefix("CIK")
    if not text.isdigit():
        raise ValueError(f"invalid CIK: {cik!r}")
    return text.zfill(10)


def _normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-")


@dataclass(frozen=True)
class CompanyProfile:
    cik: str
    name: str
    sic: str
    sic_description: str
    fiscal_year_end: str
    tickers: tuple[str, ...]
    exchanges: tuple[str, ...]


@dataclass(frozen=True)
class EdgarFact(SourcedValue):
    """``filing_fiscal_year``/``filing_fiscal_period`` are EDGAR's ``fy``/``fp``: they describe the
    filing the value came from, not the period (a comparative FY2023 figure in the FY2024 10-K has
    fy=2024). Use ``period_start``/``period_end`` to identify the period."""

    accession: str = ""
    form: str = ""
    filing_fiscal_year: int | None = None
    filing_fiscal_period: str | None = None


def _currency(unit: str) -> str | None:
    head = unit.split("/")[0]
    return head if re.fullmatch(r"[A-Z]{3}", head) else None


class CompanyFacts:
    def __init__(self, cik: str, entity_name: str, facts: dict, retrieved: date) -> None:
        self.cik = cik
        self.entity_name = entity_name
        self._facts = facts
        self.retrieved = retrieved

    def concepts(self, taxonomy: str = "us-gaap") -> list[str]:
        return sorted(self._facts.get(taxonomy, {}))

    def _rows(self, concept: str, unit: str, taxonomy: str) -> list[dict]:
        return self._facts.get(taxonomy, {}).get(concept, {}).get("units", {}).get(unit, [])

    def _series(self, concept, unit, taxonomy, forms, days, as_of) -> list[EdgarFact]:
        latest: dict[tuple[str | None, str], dict] = {}
        for row in self._rows(concept, unit, taxonomy):
            if row.get("form") not in forms:
                continue
            filed = date.fromisoformat(row["filed"])
            if as_of is not None and filed > as_of:
                continue
            start = row.get("start")
            if start is not None:
                length = (date.fromisoformat(row["end"]) - date.fromisoformat(start)).days
                if length not in days:
                    continue
            key = (start, row["end"])
            current = latest.get(key)
            if current is None or (row["filed"], row["accn"]) >= (current["filed"], current["accn"]):
                latest[key] = row
        facts = [self._fact(concept, unit, taxonomy, row) for row in latest.values()]
        return sorted(facts, key=lambda f: (f.period_end, f.period_start or date.min))

    def _fact(self, concept: str, unit: str, taxonomy: str, row: dict) -> EdgarFact:
        return EdgarFact(
            value=float(row["val"]),
            unit=unit,
            source="SEC EDGAR",
            reference=f"CIK{self.cik} {taxonomy}:{concept} accn {row['accn']} ({row['form']})",
            retrieved=self.retrieved,
            period_start=date.fromisoformat(row["start"]) if "start" in row else None,
            period_end=date.fromisoformat(row["end"]),
            filed=date.fromisoformat(row["filed"]),
            currency=_currency(unit),
            accession=row["accn"],
            form=row["form"],
            filing_fiscal_year=row.get("fy"),
            filing_fiscal_period=row.get("fp"),
        )

    def history(self, concept: str, unit: str = "USD", taxonomy: str = "us-gaap", as_of: date | None = None) -> list[EdgarFact]:
        """Every 10-K/10-Q value of a concept, one per filing and period (no deduplication), so
        restatements between filings stay visible. Sorted by filing date."""
        rows = [r for r in self._rows(concept, unit, taxonomy)
                if r.get("form") in ANNUAL_FORMS | QUARTERLY_FORMS
                and (as_of is None or date.fromisoformat(r["filed"]) <= as_of)]
        facts = [self._fact(concept, unit, taxonomy, row) for row in rows]
        return sorted(facts, key=lambda f: (f.filed, f.accession, f.period_end))

    def annual(self, concept: str, unit: str = "USD", taxonomy: str = "us-gaap", as_of: date | None = None) -> list[EdgarFact]:
        """Fiscal-year values (or year-end instants) from 10-K filings: per period the latest
        filing that was public on ``as_of``."""
        return self._series(concept, unit, taxonomy, ANNUAL_FORMS, ANNUAL_DAYS, as_of)

    def quarterly(self, concept: str, unit: str = "USD", taxonomy: str = "us-gaap", as_of: date | None = None) -> list[EdgarFact]:
        """Discrete quarters from 10-Q filings; year-to-date rows are excluded. Q4 is not filed
        separately: derive it as fiscal year minus nine-month YTD."""
        return self._series(concept, unit, taxonomy, QUARTERLY_FORMS, QUARTER_DAYS, as_of)


class SecEdgar:
    def __init__(self, client: HttpClient, cache: DiskCache) -> None:
        self._client = client
        self._cache = cache

    def _json(self, url: str) -> tuple[dict, datetime]:
        body, fetched = self._cache.fetch(url, self._client.get, MAX_AGE)
        return json.loads(body), fetched

    def cik_for_ticker(self, ticker: str) -> str:
        wanted = _normalize_ticker(ticker)
        tickers, _ = self._json(TICKERS_URL)
        for entry in tickers.values():
            if _normalize_ticker(entry["ticker"]) == wanted:
                return format_cik(entry["cik_str"])
        raise UnknownTickerError(f"ticker {ticker!r} not found in SEC company_tickers.json")

    def profile(self, cik: int | str) -> CompanyProfile:
        cik = format_cik(cik)
        data, _ = self._json(SUBMISSIONS_URL.format(cik=cik))
        return CompanyProfile(
            cik=cik,
            name=data["name"],
            sic=data.get("sic", ""),
            sic_description=data.get("sicDescription", ""),
            fiscal_year_end=data.get("fiscalYearEnd", ""),
            tickers=tuple(data.get("tickers", [])),
            exchanges=tuple(data.get("exchanges", [])),
        )

    def company_facts(self, cik: int | str) -> CompanyFacts:
        cik = format_cik(cik)
        data, fetched = self._json(COMPANY_FACTS_URL.format(cik=cik))
        return CompanyFacts(cik, data.get("entityName", ""), data.get("facts", {}), fetched.date())
