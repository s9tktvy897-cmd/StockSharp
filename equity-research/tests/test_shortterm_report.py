import re
from datetime import date, datetime, timezone

from equity_research.shortterm import engine, predictions, report
from equity_research.shortterm.config import Config

from shortterm_fakes import make_bars, planted_universe


def _render(signal: bool, seed: int):
    universe = planted_universe(signal=signal, seed=seed)
    last = max(max(b.dates) for b in universe.values())
    r = engine.run(universe, None, Config(), {}, "SYNTHETIC", datetime(last.year, last.month, last.day, 23, tzinfo=timezone.utc))
    return r, report.render(r, [], {}, ["Stooq: blocked"], None, "test")


def test_report_with_candidates_shows_probabilities_and_disclaimer():
    r, text = _render(True, 7)
    assert "geen beleggingsadvies" in text and "geen garantie" in text
    assert "### 1. T" in text and "Kans op +10%" in text
    assert not re.search(r"\bNone\b|\bnan\b", text)


def test_report_without_edge_lists_no_candidates():
    r, text = _render(False, 11)
    assert "**Geen kandidaten vandaag.**" in text
    assert "niet gevalideerd — geen kandidaten" in text
    assert "niet aantoonbaar winstgevend" in text or "0 |" in text


def test_report_without_any_data():
    r = engine.run({}, None, Config(), {}, "", datetime(2026, 10, 9, tzinfo=timezone.utc))
    text = report.render(r, [], {}, ["no price source"], None, "test")
    assert "Geen kandidaten" in text and "Geen backtest mogelijk" in text


def test_prediction_log_round_trip_and_evaluation(tmp_path):
    universe = planted_universe(signal=True, seed=7)
    last = max(max(b.dates) for b in universe.values())
    r = engine.run(universe, None, Config(), {}, "SYNTHETIC", datetime(last.year, last.month, last.day, 23, tzinfo=timezone.utc))
    path = predictions.log(r.candidates, r.scan_time, "test", tmp_path, {1: True, 2: True})
    records = predictions.read(tmp_path)
    assert path.exists() and len(records) == len(r.candidates)
    pending = predictions.evaluate(records, universe, Config())
    assert pending[1]["pending"] == len(records)  # the next day is not in the data yet

    # a pick whose next day hit +12%
    bars = make_bars("Z", [10, 10.5], opens=[10, 10], highs=[10, 11.2], lows=[10, 9.9])
    result = predictions.evaluate([{"ticker": "Z", "signal_date": bars.dates[0].isoformat(), "probability": {"1": 0.3}}],
                                  {"Z": bars}, Config())
    assert result[1]["evaluated"] == 1 and result[1]["hits"] == 1
    assert result[1]["brier"] == (0.3 - 1) ** 2


def test_universe_excludes_warrants_and_units():
    from equity_research.shortterm.sources import is_common_stock
    assert is_common_stock("AAPL") and is_common_stock("BRK-B")
    assert not any(is_common_stock(t) for t in ("AAC-WT", "AAC-UN", "XYZ-WS", "ABC-RT", "ABC-U"))


def test_drop_model_and_direction_check_are_reported():
    r, text = _render(True, 7)
    assert "Kans op ≥10% daling" in text
    assert "Richtingstoets" in text
    assert r.oos_drop and set(r.oos_drop) == {1, 2}


def test_edge_ranking_is_backtested_and_loss_warning_shown():
    r, text = _render(True, 7)
    assert set(r.edge_backtests) == {1, 2}
    assert "Model stijging − daling" in text


def test_cost_is_formatted_with_two_decimals():
    r, text = _render(True, 7)
    assert "aangenomen kosten 0,15% per kant" in text or "aangenomen kosten 0,25% per kant" in text \
        or "aangenomen kosten 0,40% per kant" in text
