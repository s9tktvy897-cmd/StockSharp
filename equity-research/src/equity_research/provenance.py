"""Source-traceable values: every number carries where it came from."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SourcedValue:
    """A fact taken from an external source. ``value`` is None when the source has no data."""

    value: float | None
    unit: str
    source: str
    reference: str
    retrieved: date
    period_start: date | None = None
    period_end: date | None = None
    filed: date | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if not self.source or not self.reference:
            raise ValueError("source and reference are required for every fact")

    @property
    def is_missing(self) -> bool:
        return self.value is None

    def require(self) -> float:
        """Return the value, or raise if missing -- never substitute a guess."""
        if self.value is None:
            raise MissingDataError(f"{self.source} has no value for {self.reference}")
        return self.value


@dataclass(frozen=True)
class Assumption:
    """A modelling input chosen by the analyst, kept apart from facts."""

    name: str
    value: float
    rationale: str

    def __post_init__(self) -> None:
        if not self.rationale:
            raise ValueError(f"assumption {self.name!r} needs a rationale")


class MissingDataError(LookupError):
    pass
