import json
from datetime import date, datetime, timezone

import numpy as np
import pytest

from equity_research import ledger
from equity_research.shortterm.config import Config

from shortterm_fakes import make_bars

NOW = datetime(2026, 10, 9, 22, 0, tzinfo=timezone.utc)


def _prediction(ticker="AAA", signal=date(2020, 1, 1), horizon=2, paper=True):
    return ledger.Prediction(
        ticker=ticker, security_id="CIK0000000042", strategy="MODEL_B_EXPECTED_RETURN", horizon=horizon,
        model_version="abc1234", dataset_version="bars-2020-01-01", signal_date=signal, direction="long",
        expected_return=0.01, probabilities={"up": 0.6}, expected_cost_per_side=0.002, paper_trade=paper,
        strategy_status="PAPER TRADING CANDIDATE")


def test_append_and_verify_hash_chain(tmp_path):
    path = tmp_path / "ledger.jsonl"
    book = ledger.Ledger(path)
    pid = book.add(_prediction(), NOW)
    assert book.status(pid) == "OPEN"
    assert book.verify() == []
    with pytest.raises(ValueError):
        book.add(_prediction(), NOW)  # the same prediction cannot be logged twice
    lines = path.read_text().splitlines()
    first = json.loads(lines[0])
    first["payload"]["expected_return"] = 0.5  # tamper with the original prediction
    lines[0] = json.dumps(first)
    path.write_text("\n".join(lines) + "\n")
    assert ledger.Ledger(path).verify()  # detected


def test_evaluation_fills_and_closes_with_costs(tmp_path):
    book = ledger.Ledger(tmp_path / "l.jsonl")
    bars = make_bars("AAA", [10, 10, 10.5, 11], opens=[10, 10, 10.2, 10.8], start=date(2020, 1, 1))
    pid = book.add(_prediction(signal=bars.dates[0], horizon=2), NOW)
    book.evaluate({"AAA": bars}, NOW, cost_per_side=lambda ticker, i: 0.001)
    assert book.status(pid) == "CLOSED"
    events = book.events(pid)
    fill = next(e for e in events if e["type"] == "FILLED")
    close = next(e for e in events if e["type"] == "CLOSED")
    assert fill["payload"]["entry_price"] == pytest.approx(10 * 1.001)
    assert close["payload"]["exit_price"] == pytest.approx(10.5 * 0.999)
    assert close["payload"]["net"] == pytest.approx(10.5 * 0.999 / (10 * 1.001) - 1)
    assert book.verify() == []


def test_open_until_horizon_passes_then_expired_or_cancelled(tmp_path):
    book = ledger.Ledger(tmp_path / "l.jsonl")
    bars = make_bars("AAA", [10, 10], start=date(2020, 1, 1))
    pid = book.add(_prediction(signal=bars.dates[0], horizon=2), NOW)
    book.evaluate({"AAA": bars}, datetime(2020, 1, 3, tzinfo=timezone.utc), cost_per_side=lambda t, i: 0.0)
    assert book.status(pid) == "FILLED"  # entered, exit day not reached yet
    gone = book.add(_prediction(ticker="ZZZ", signal=bars.dates[0]), NOW)
    book.evaluate({"AAA": bars}, datetime(2020, 2, 1, tzinfo=timezone.utc), cost_per_side=lambda t, i: 0.0)
    assert book.status(gone) == "CANCELLED"  # never any bar after the signal: not filled
    assert book.status(pid) == "EXPIRED"     # no exit bar long after the planned exit


def test_predictions_without_paper_trade_are_scored_but_not_traded(tmp_path):
    book = ledger.Ledger(tmp_path / "l.jsonl")
    bars = make_bars("AAA", [10, 10, 9, 9], start=date(2020, 1, 1))
    pid = book.add(_prediction(signal=bars.dates[0], horizon=2, paper=False), NOW)
    book.evaluate({"AAA": bars}, NOW, cost_per_side=lambda t, i: 0.0)
    assert book.status(pid) == "CLOSED"
    s = book.summary()
    assert s["paper"]["closed"] == 0 and s["predictions"]["closed"] == 1
    assert s["predictions"]["direction_hit_rate"] == 0.0  # predicted up, went down


def test_invalid_prediction_is_recorded_not_dropped(tmp_path):
    book = ledger.Ledger(tmp_path / "l.jsonl")
    pid = book.add(_prediction(ticker=""), NOW)
    book.evaluate({}, NOW, cost_per_side=lambda t, i: 0.0)
    assert book.status(pid) == "INVALID"


def test_new_ledger_must_extend_the_old_one(tmp_path):
    old = ledger.Ledger(tmp_path / "old.jsonl")
    old.add(_prediction(ticker="AAA"), NOW)
    import shutil
    shutil.copy(tmp_path / "old.jsonl", tmp_path / "new.jsonl")
    new = ledger.Ledger(tmp_path / "new.jsonl")
    new.add(_prediction(ticker="BBB"), NOW)
    assert ledger.check_extension(tmp_path / "old.jsonl", tmp_path / "new.jsonl") == []
    rewritten = ledger.Ledger(tmp_path / "other.jsonl")
    rewritten.add(_prediction(ticker="CCC"), NOW)
    assert ledger.check_extension(tmp_path / "old.jsonl", tmp_path / "other.jsonl")
    assert ledger.check_extension(tmp_path / "missing.jsonl", tmp_path / "new.jsonl") == []  # first run
