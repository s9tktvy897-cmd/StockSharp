"""Corporate events from SEC 8-K filings (official; no news is ever made up).

Each 8-K carries item codes (2.02 results, 1.01 material agreement, ...) and an acceptance time
(UTC; checked against the EDGAR Atom feed). Relative to a row for trading day t, whose decision
is taken at 09:00 ET on the next trading day, a filing is:

- *day*: accepted after the previous decision and up to 16:00 ET on t -- the market could react
  on t, so the news is (partly) in the close of t;
- *overnight*: accepted after 16:00 ET on t and up to the decision -- not yet in a regular-session
  price (after-hours trading is not observed here).

The item code tells the type of event, not whether it is good or bad news; that needs the text
(press release exhibit), which this module links but does not judge."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from equity_research.shortterm.bars import Bars

NEW_YORK = ZoneInfo("America/New_York")
DECISION_TIME = time(9, 0)
CLOSE_TIME = time(16, 0)
RECENT_DAYS = 7
FORMS = ("8-K", "8-K/A")
CURRENT_FEED_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include"
                    "&start={start}&count=100&output=atom")

ITEMS = {
    "1.01": "material definitive agreement", "1.02": "termination of a material agreement",
    "1.03": "bankruptcy or receivership", "2.01": "completed acquisition or disposition",
    "2.02": "results of operations", "2.03": "new direct financial obligation", "2.04": "triggering event on debt",
    "2.05": "exit or disposal costs", "2.06": "material impairment", "3.01": "delisting notice",
    "3.02": "unregistered sale of equity", "3.03": "modification of shareholder rights",
    "4.01": "change of auditor", "4.02": "non-reliance on prior financial statements", "5.01": "change in control",
    "5.02": "director or officer change", "5.03": "amendment of articles or bylaws", "5.07": "shareholder vote",
    "7.01": "Regulation FD disclosure", "8.01": "other events", "9.01": "financial statements and exhibits",
}
EARNINGS = {"2.02"}
DEAL = {"1.01", "2.01", "5.01"}
PRESS = {"7.01", "8.01"}
NEGATIVE = {"1.02", "1.03", "2.04", "2.05", "2.06", "3.01", "3.02", "4.01", "4.02"}


@dataclass(frozen=True)
class Filing:
    ticker: str
    cik: str
    accession: str
    form: str
    items: tuple[str, ...]
    accepted: datetime  # UTC
    url: str

    @property
    def accepted_et(self) -> datetime:
        return self.accepted.astimezone(NEW_YORK)


def describe(items: tuple[str, ...]) -> str:
    codes = set(items)
    for label, group in (("earnings", EARNINGS), ("deal", DEAL), ("negative event", NEGATIVE), ("press release", PRESS)):
        if codes & group:
            return label
    return "other" if codes - {"9.01"} else "exhibits only"


def leaning(items: tuple[str, ...]) -> str:
    negative = sorted(set(items) & NEGATIVE)
    if negative:
        return "negative-leaning (" + ", ".join(f"{c} {ITEMS[c]}" for c in negative) + ")"
    return "unknown direction"


def item_text(items: tuple[str, ...]) -> str:
    return "; ".join(f"{c} {ITEMS.get(c, 'item')}" for c in items if c != "9.01") or "9.01 exhibits"


def _filing_url(cik: str, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}-index.htm"


def parse_submissions(data: dict, ticker: str) -> list[Filing]:
    recent = data.get("filings", {}).get("recent", {})
    cik = str(data.get("cik", "")).zfill(10)
    out = []
    for i, form in enumerate(recent.get("form", [])):
        if form not in FORMS:
            continue
        accepted = datetime.fromisoformat(recent["acceptanceDateTime"][i].replace("Z", "+00:00"))
        items = tuple(x.strip() for x in (recent.get("items", [""] * (i + 1))[i] or "").split(",") if x.strip())
        accession = recent["accessionNumber"][i]
        out.append(Filing(ticker.upper(), cik, accession, form, items, accepted.astimezone(timezone.utc),
                          _filing_url(cik, accession)))
    return sorted(out, key=lambda f: f.accepted)


def _ny_offset(moment: datetime) -> timedelta:
    """Hours New York is behind UTC at ``moment`` (4 in summer, 5 in winter)."""
    return -moment.astimezone(NEW_YORK).utcoffset()


def _sample(filings: list[Filing]) -> list[Filing]:
    """The latest filing, plus the latest one from the other daylight-saving season if any."""
    if not filings:
        return []
    latest = filings[-1]
    other = next((f for f in reversed(filings) if _ny_offset(f.accepted) != _ny_offset(latest.accepted)), None)
    return [latest] + ([other] if other else [])


def calibrate_times(filings: list[Filing], accepted_on_index, tolerance_minutes: int = 2) -> tuple[list[Filing], str]:
    """Check the submissions acceptance times against the filing index pages (``accepted_on_index``
    returns the time the page shows). Checked live 2026-10-09: for some filings -- per filing, not
    per filer -- the submissions time is the true time plus the New York UTC offset (4-5 h late).
    Shifting a time earlier could leak news that was not yet public, so times are never corrected:
    late times are kept (conservative); a time EARLIER than the filing page drops the filer's 8-Ks."""
    sample = _sample(filings)
    if not sample:
        return filings, "no filings"
    diffs = [(f.accepted - accepted_on_index(f.url)) for f in sample]
    tol = timedelta(minutes=tolerance_minutes)
    if any(d < -tol for d in diffs):
        return [], "unreliable (submissions times earlier than the filing pages: " + \
            ", ".join(f"{d.total_seconds() / 3600:+.1f}h" for d in diffs) + ")"
    if all(abs(d) <= tol for d in diffs):
        return filings, "verified"
    late = max(d for d in diffs).total_seconds() / 3600
    return filings, f"late by up to {late:.0f}h in the submissions data (kept as is: never earlier than the truth)"


def parse_current_feed(xml_text: str) -> list[Filing]:
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_text.encode("latin-1", errors="replace") if isinstance(xml_text, str) else xml_text)
    out = []
    for entry in root.findall("a:entry", ns):
        title = entry.findtext("a:title", "", ns)
        match = re.match(r"^(\S+) - .+ \((\d{10})\) \(", title)
        if not match or match.group(1) not in FORMS:
            continue
        summary = entry.findtext("a:summary", "", ns)
        accession = re.search(r"AccNo:</b>\s*(\S+)", summary)
        link = entry.find("a:link", ns)
        out.append(Filing("", match.group(2), accession.group(1) if accession else "", match.group(1),
                          tuple(re.findall(r"Item (\d+\.\d+):", summary)),
                          datetime.fromisoformat(entry.findtext("a:updated", "", ns)).astimezone(timezone.utc),
                          link.get("href") if link is not None else ""))
    return out


def _at(day: date, clock: time) -> float:
    return datetime.combine(day, clock, NEW_YORK).timestamp()


def next_weekday(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


FEATURES = ("cat_overnight_any", "cat_overnight_earnings", "cat_overnight_deal", "cat_overnight_press",
            "cat_overnight_negative", "cat_day_any", "cat_day_earnings", "cat_recent_any", "cat_recent_negative",
            "cat_reaction_earnings")


def features(bars: Bars, filings: list[Filing], last_decision: datetime | None = None) -> dict[str, np.ndarray]:
    """Event flags per row of ``bars``; the last row's decision time is ``last_decision`` (default:
    09:00 ET on the next weekday)."""
    n = len(bars)
    decisions = np.array([_at(bars.dates[i + 1], DECISION_TIME) for i in range(n - 1)]
                         + ([last_decision.timestamp() if last_decision else _at(next_weekday(bars.dates[-1]), DECISION_TIME)]
                            if n else []))
    starts = np.concatenate([[_at(bars.dates[0], DECISION_TIME)], decisions[:-1]]) if n else np.array([])
    closes = np.array([_at(d, CLOSE_TIME) for d in bars.dates])
    out = {name: np.zeros(n) for name in FEATURES}
    groups = {"any": None, "earnings": EARNINGS, "deal": DEAL, "press": PRESS, "negative": NEGATIVE}
    for f in filings:
        t = f.accepted.timestamp()
        codes = set(f.items)
        i = int(np.searchsorted(decisions, t, side="left"))  # first row whose decision is at or after t
        if i < n and t > starts[i]:
            when = "day" if t <= closes[i] else "overnight"
            for name, group in groups.items():
                key = f"cat_{when}_{name}"
                if key in out and (group is None or codes & group):
                    out[key][i] = 1
        if codes & EARNINGS:
            # earnings released after the previous close and up to this close: today's bar is the reaction
            k = int(np.searchsorted(closes, t, side="left"))
            if k < n and (k > 0 or t > closes[0] - 86400):
                out["cat_reaction_earnings"][k] = 1
        lo = int(np.searchsorted(decisions, t, side="left"))
        hi = int(np.searchsorted(decisions, t + RECENT_DAYS * 86400, side="left"))
        for row in range(lo, min(hi, n)):
            out["cat_recent_any"][row] = 1
            if codes & NEGATIVE:
                out["cat_recent_negative"][row] = 1
    return out
