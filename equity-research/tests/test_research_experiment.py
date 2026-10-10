"""End-to-end check of the research runner on SYNTHETIC data (the pipeline works and is honest);
never evidence about real markets."""

from datetime import date

import numpy as np

from equity_research.research import experiment, protocol
from equity_research.research.protocol import Variant

from shortterm_fakes import planted_universe


def _inputs(signal: bool, seed: int):
    universe = planted_universe(n_tickers=25, n_days=1300, seed=seed, signal=signal)
    spy = universe.pop("T00")
    return experiment.Inputs(universe, spy, None, {}, {})


def _patch(monkeypatch):
    monkeypatch.setattr(protocol, "HOLDOUT_START", date(2023, 7, 1))
    monkeypatch.setattr(protocol, "BOOTSTRAP_REPS", 200)
    monkeypatch.setattr(protocol, "TOP_N", 3)


def test_runner_produces_statuses_and_rejects_noise(monkeypatch):
    _patch(monkeypatch)
    variants = [Variant("REVERSAL_5D", 1), Variant("BREAKOUT_VOLUME", 1), Variant("MODEL_B_EXPECTED_RETURN", 1)]
    run = experiment.run_all(_inputs(False, 5), variants, progress=lambda s: None)
    statuses = {r.variant.name: r.status for r in run["results"]}
    assert set(statuses) == {v.name for v in variants}
    assert all(s in protocol.STATUSES for s in statuses.values())
    assert all(s != "PAPER TRADING CANDIDATE" for s in statuses.values())  # pure noise: no edge
    r = run["results"][0]
    assert r.period[1] <= (protocol.HOLDOUT_START.isoformat())
    assert all(d >= protocol.HOLDOUT_START.isoformat() for d, _ in r.holdout_curve)
    assert "SPY_BUY_AND_HOLD development" in run["benchmarks"]
    js = experiment.to_json(run, _inputs(False, 5))
    assert js["variants"][0]["status"] == statuses[variants[0].name]


def test_dev_scores_never_use_holdout_rows(monkeypatch):
    _patch(monkeypatch)
    inputs = _inputs(True, 7)
    p = experiment.prepare(inputs)
    from equity_research.research import strategies
    f = strategies.fitted_scores("MODEL_B_EXPECTED_RETURN", p.panel, 1, p.labels[1], p.usable, p.vol20,
                                 p.dev_end, p.holdout_start)
    dates = p.panel.dates
    assert not np.any(np.isfinite(f.dev[np.array([d > p.dev_end for d in dates])]))
    assert not np.any(np.isfinite(f.holdout[np.array([d < p.holdout_start for d in dates])]))


def test_paper_signals_only_for_candidates(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from equity_research import ledger
    from equity_research.research import signals
    _patch(monkeypatch)
    p = experiment.prepare(_inputs(True, 7))
    book = ledger.Ledger(tmp_path / "l.jsonl")
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    none = {"variants": [{"variant": "REVERSAL_5D 1d", "status": "RESEARCH ONLY"}]}
    assert signals.log_paper_trades(none, p, book, "x", now, {}) == {}
    assert book.records == []  # no candidate: explicit no trade
    one = {"variants": [{"variant": "BREAKOUT_VOLUME 1d", "status": "PAPER TRADING CANDIDATE"}]}
    logged = signals.log_paper_trades(one, p, book, "x", now, {})
    assert logged["BREAKOUT_VOLUME 1d"] == len(book.records) > 0
    assert all(r["payload"]["paper_trade"] for r in book.records) and book.verify() == []
