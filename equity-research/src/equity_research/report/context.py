"""Qualitative context gathered from public websites (news, guidance, events, third-party views),
added to a report as a separate section. Every bullet must name its source URL and a date;
these items never feed the calculations."""

from __future__ import annotations

import re
from pathlib import Path

URL = re.compile(r"https?://\S+")
DATE = re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b")


class ContextError(ValueError):
    pass


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


def section(lines: list[str], number: str = "10") -> list[str]:
    return [f"## {number}. Context uit openbare bronnen (kwalitatief)", "",
            "Verzameld van openbare websites. Ter duiding en controle; deze punten worden **niet** in de "
            "berekeningen gebruikt. Getallen hieruit zijn secundair zolang ze niet in een officiële bron "
            "(SEC-filing, jaarverslag) terugkomen.", ""] + lines + [""]
