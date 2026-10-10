"""Qualitative context gathered from public websites (news, guidance, events, third-party views),
added to a report as a separate section. Every bullet must name its source URL and a date;
these items never feed the calculations."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

URL = re.compile(r"https?://[^\s)\]>]+")
DATE = re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b")


# Fewer distinct sites than this is reported as narrow coverage.
MIN_SITES = 10

PRESS_WIRES = {"businesswire.com", "prnewswire.com", "globenewswire.com", "accesswire.com", "newsfilecorp.com"}
MAJOR_MEDIA = {"reuters.com", "apnews.com", "bloomberg.com", "cnbc.com", "wsj.com", "ft.com", "nytimes.com",
               "barrons.com", "marketwatch.com", "economist.com", "bbc.com", "bbc.co.uk", "theguardian.com",
               "washingtonpost.com", "axios.com", "fortune.com", "latimes.com", "theinformation.com"}
OFFICIAL_SUFFIXES = (".gov", ".europa.eu", ".gov.uk")
OFFICIAL_PREFIXES = ("investor.", "investors.", "ir.")


class ContextError(ValueError):
    pass


@dataclass(frozen=True)
class Coverage:
    bullets: int
    pages: int                 # distinct URLs
    sites: set[str]            # distinct hosts without "www."
    by_kind: dict[str, int]    # distinct sites per kind


def _site(url: str) -> str:
    host = (urlparse(url.rstrip(".,;")).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _kind(site: str) -> str:
    if site == "sec.gov" or site.endswith(OFFICIAL_SUFFIXES) or site.startswith(OFFICIAL_PREFIXES):
        return "officieel"
    if site in PRESS_WIRES:
        return "persbericht"
    if site in MAJOR_MEDIA:
        return "grote media"
    return "overig"


def coverage(lines: list[str]) -> Coverage:
    """How broad the research was: bullets, distinct pages and distinct sites, by kind of source."""
    bullets = [line for line in lines if line.lstrip().startswith(("- ", "* "))]
    urls = {u.rstrip(".,;") for line in bullets for u in URL.findall(line)}
    sites = {_site(u) for u in urls} - {""}
    return Coverage(len(bullets), len(urls), sites, dict(Counter(_kind(s) for s in sites)))


def load(path: Path) -> list[str]:
    """Markdown lines of the context file; raises when a bullet lacks a URL or a YYYY-MM-DD date."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    bad = [line for line in lines if line.lstrip().startswith(("- ", "* "))
           and not (URL.search(line) and DATE.search(line))]
    if bad:
        raise ContextError("every context bullet needs a source URL and a date (YYYY-MM-DD); fix:\n"
                           + "\n".join(f"  {line}" for line in bad))
    if not any(line.lstrip().startswith(("- ", "* ")) for line in lines):
        raise ContextError(f"{path} contains no bullets")
    return lines


def coverage_lines(c: Coverage) -> list[str]:
    kinds = ", ".join(f"{k} {c.by_kind[k]}" for k in ("officieel", "persbericht", "grote media", "overig")
                      if k in c.by_kind)
    out = [f"Dekking: {c.bullets} punten uit {c.pages} pagina's van {len(c.sites)} verschillende site(s) "
           f"({kinds}).", ""]
    if len(c.sites) < MIN_SITES:
        out += [f"> **Smalle dekking:** minder dan {MIN_SITES} verschillende sites; de context kan eenzijdig zijn.", ""]
    return out


def section(lines: list[str], number: str = "10") -> list[str]:
    return [f"## {number}. Context uit openbare bronnen (kwalitatief)", "",
            "Verzameld van openbare websites. Ter duiding en controle; deze punten worden **niet** in de "
            "berekeningen gebruikt. Getallen hieruit zijn secundair zolang ze niet in een officiële bron "
            "(SEC-filing, jaarverslag) terugkomen.", ""] + coverage_lines(coverage(lines)) + lines + [""]
