from datetime import datetime, timezone

from equity_research.shortterm import engine
from equity_research.shortterm.config import Config

from shortterm_fakes import planted_universe


def _run(signal: bool, seed: int):
    universe = planted_universe(signal=signal, seed=seed)
    last = max(max(b.dates) for b in universe.values())
    scan = datetime(last.year, last.month, last.day, 23, 0, tzinfo=timezone.utc)
    return engine.run(universe, None, Config(), {}, "SYNTHETIC", scan)


def test_planted_pattern_gives_ranked_candidates_with_probabilities():
    r = _run(True, 7)
    assert r.oos[1].gate.passed
    assert 0 < len(r.candidates) <= 10
    assert all(c.probability[2] is not None or c.probability[1] is not None for c in r.candidates)
    assert r.backtests[1].summary["trades"] > 0


def test_noise_gives_no_candidates_and_says_why():
    r = _run(False, 11)
    assert r.candidates == []
    assert any("no ranking passed" in n for n in r.notes)
    assert r.raw_scanner  # shown separately as not validated


def test_empty_universe():
    r = engine.run({}, None, Config(), {}, "none", datetime(2026, 10, 9, tzinfo=timezone.utc))
    assert r.candidates == [] and "no price history" in r.notes[0]
