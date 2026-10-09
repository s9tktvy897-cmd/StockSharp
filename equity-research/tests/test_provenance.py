from datetime import date

import pytest

from equity_research.provenance import Assumption, MissingDataError, SourcedValue


def _fact(value):
    return SourcedValue(
        value=value,
        unit="USD",
        source="SEC EDGAR",
        reference="CIK0000320193/us-gaap/Revenues/FY2024",
        retrieved=date(2026, 10, 9),
    )


def test_require_returns_value():
    assert _fact(100.0).require() == 100.0


def test_missing_value_raises_instead_of_guessing():
    fact = _fact(None)
    assert fact.is_missing
    with pytest.raises(MissingDataError):
        fact.require()


def test_fact_without_source_is_rejected():
    with pytest.raises(ValueError):
        SourcedValue(value=1.0, unit="USD", source="", reference="x", retrieved=date(2026, 1, 1))


def test_assumption_needs_rationale():
    with pytest.raises(ValueError):
        Assumption(name="terminal_growth", value=0.02, rationale="")
