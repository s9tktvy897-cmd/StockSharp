from datetime import date

import numpy as np
import pytest

from equity_research.shortterm import features, labels
from equity_research.shortterm.bars import Bars, parse_ohlcv_csv, validate
from equity_research.shortterm.config import Config, Costs

from shortterm_fakes import make_bars


def test_parse_ohlcv_csv_and_source():
    text = "Date,Open,High,Low,Close,Volume\n2026-10-07,10,11,9.5,10.5,1000\n2026-10-08,10.5,12,10,11,2000\n"
    bars = parse_ohlcv_csv(text, "ABC", "Stooq (secondary)")
    assert list(bars.dates) == [date(2026, 10, 7), date(2026, 10, 8)]
    assert bars.close.tolist() == [10.5, 11] and bars.volume.tolist() == [1000, 2000]
    assert bars.source == "Stooq (secondary)"


def test_validate_flags_impossible_bars_and_split_like_jumps():
    bars = make_bars("X", [10, 10, 2.5, 2.6], highs=[10, 9, 2.6, 2.7])  # high < close on day 2; 4:1-like drop
    problems = validate(bars)
    assert any("high below" in p for p in problems)
    assert any("split" in p for p in problems)


def test_rvol_uses_only_prior_days():
    volumes = [100.0] * 25 + [500.0]
    bars = make_bars("X", np.linspace(10, 12, 26), volumes=volumes)
    f = features.compute(bars)
    assert f["rvol"][-1] == pytest.approx(5.0)  # 500 / mean of the 20 previous days (100)


def test_breakout_and_gap():
    closes = [10.0] * 30 + [11.0]
    opens = [10.0] * 30 + [10.5]
    f = features.compute(make_bars("X", closes, opens=opens))
    assert f["breakout_20"][-1] == pytest.approx(0.10)  # close 11 vs prior 20-day high 10
    assert f["gap"][-1] == pytest.approx(0.05)


def test_features_have_no_look_ahead():
    rng = np.random.default_rng(1)
    closes = 20 * np.cumprod(1 + rng.normal(0, 0.02, 300))
    full = features.compute(make_bars("X", closes))
    cut = features.compute(make_bars("X", closes[:200]))
    for name in full:
        np.testing.assert_allclose(full[name][:200], cut[name], equal_nan=True, err_msg=name)


def test_labels_from_next_open():
    # day 0 signal; day 1 opens 10, high 11.2 (+12%); day 2 low 8.9 (-11%)
    bars = make_bars("X", closes=[10, 10.5, 9.5], opens=[10, 10, 10.4], highs=[10, 11.2, 10.4], lows=[10, 9.9, 8.9])
    out = labels.compute(bars, Config())
    assert out[1]["hit"][0] == 1 and out[2]["hit"][0] == 1
    assert out[1]["drop"][0] == 0 and out[2]["drop"][0] == 1
    assert out[2]["ret_close"][0] == pytest.approx(9.5 / 10 - 1)
    assert np.isnan(out[1]["hit"][2])  # no next day


def test_labels_skip_data_gaps():
    bars = make_bars("X", [10, 10, 10])
    bars = Bars("X", np.array([date(2026, 1, 5), date(2026, 1, 20), date(2026, 1, 21)]), bars.open, bars.high,
                bars.low, bars.close, bars.volume, "SYNTHETIC")
    assert np.isnan(labels.compute(bars, Config())[1]["hit"][0])


def test_cost_tiers():
    costs = Costs()
    assert costs.per_side(100e6) == pytest.approx(15 / 1e4)
    assert costs.per_side(20e6) == pytest.approx(25 / 1e4)
    assert costs.per_side(1e6) == pytest.approx(40 / 1e4)
