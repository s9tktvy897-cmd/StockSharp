"""Damodaran Online (NYU Stern) data pages: industry betas and the implied equity risk premium.

The pages are HTML tables with a header row; columns are found by name, so a changed layout
fails loudly instead of returning a wrong number. Layouts verified live on 2026-10-09 (Betas.html
and histimpl.html, both "January 2026"). Each page states its data date, which goes into the
reference."""

from __future__ import annotations

import re
from datetime import date, timedelta
from html.parser import HTMLParser

from equity_research.data.cache import DiskCache
from equity_research.data.http import HttpClient
from equity_research.provenance import MissingDataError, SourcedValue

BASE = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/"
BETAS_URL = BASE + "Betas.html"
# histimpl.html is maintained yearly; implpr.html stopped at 2016 (both checked live 2026-10-09).
IMPLIED_ERP_URL = BASE + "histimpl.html"
MAX_ERP_AGE_YEARS = 2
MAX_AGE = timedelta(days=7)
SOURCE = "Damodaran Online (NYU Stern)"


class _Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_tables(html: str) -> list[list[list[str]]]:
    parser = _Tables()
    parser.feed(html)
    return parser.tables


def _find(html: str, required: str) -> tuple[list[str], list[list[str]]]:
    """The first table row whose cells include ``required`` is the header; rows after it are data."""
    for table in parse_tables(html):
        for index, row in enumerate(table):
            if any(cell.lower() == required.lower() for cell in row):
                return [c.lower() for c in row], table[index + 1:]
    raise ValueError(f"no table with a {required!r} column; page layout changed?")


def _column(header: list[str], *names: str) -> int:
    for name in names:
        if name.lower() in header:
            return header.index(name.lower())
    raise ValueError(f"none of the columns {names} found in {header}")


def page_date(html: str) -> str | None:
    """The data date a Damodaran page states, e.g. 'January 2026'."""
    text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    match = re.search(r"(?:Date(?: of Analysis)?\s*:\s*(?:Data used is as of\s+)?)([A-Z][a-z]+ \d{4})", text)
    return match.group(1) if match else None


def _dated(url: str, html: str) -> str:
    when = page_date(html)
    return f"{url} (data as of {when})" if when else f"{url} (page states no date)"


def _number(text: str) -> float:
    cleaned = text.replace(",", "").replace("$", "").strip()
    return float(cleaned[:-1]) / 100 if cleaned.endswith("%") else float(cleaned)


def industry_beta(html: str, industry: str, retrieved: date, url: str) -> SourcedValue:
    header, rows = _find(html, "Industry Name")
    name_col = _column(header, "Industry Name")
    beta_col = _column(header, "Unlevered beta corrected for cash", "Unlevered beta")
    names = [row[name_col] for row in rows if len(row) > beta_col]
    for row in rows:
        if len(row) > beta_col and row[name_col].lower() == industry.strip().lower():
            return SourcedValue(value=_number(row[beta_col]), unit="beta", source=SOURCE,
                                reference=f"{_dated(url, html)} industry {row[name_col]!r}, column {header[beta_col]!r}",
                                retrieved=retrieved)
    raise MissingDataError(f"industry {industry!r} not in Damodaran betas; choose one of: {', '.join(names)}")


def implied_erp(html: str, retrieved: date, url: str) -> SourcedValue:
    header, rows = _find(html, "Year")
    year_col = _column(header, "Year")
    erp_col = _column(header, "Implied Premium (FCFE)", "Implied ERP (FCFE)", "Implied Premium")
    dated = [(int(row[year_col]), row) for row in rows
             if len(row) > erp_col and re.fullmatch(r"\d{4}", row[year_col]) and row[erp_col]]
    if not dated:
        raise ValueError("implied ERP table has no data rows")
    year, row = max(dated, key=lambda item: item[0])
    if retrieved.year - year > MAX_ERP_AGE_YEARS:
        raise MissingDataError(f"implied ERP table ends in {year}; too old for a valuation in {retrieved.year}")
    return SourcedValue(value=_number(row[erp_col]), unit="ratio", source=SOURCE,
                        reference=f"{_dated(url, html)} year {year}, column {header[erp_col]!r} (start of {year + 1})",
                        retrieved=retrieved, period_end=date(year, 12, 31))


class Damodaran:
    def __init__(self, client: HttpClient, cache: DiskCache) -> None:
        self._client = client
        self._cache = cache

    def _page(self, url: str) -> tuple[str, date]:
        body, fetched = self._cache.fetch(url, self._client.get, MAX_AGE)
        return body.decode("utf-8", errors="replace"), fetched.date()

    def industry_beta(self, industry: str) -> SourcedValue:
        html, retrieved = self._page(BETAS_URL)
        return industry_beta(html, industry, retrieved, BETAS_URL)

    def implied_erp(self) -> SourcedValue:
        html, retrieved = self._page(IMPLIED_ERP_URL)
        return implied_erp(html, retrieved, IMPLIED_ERP_URL)
