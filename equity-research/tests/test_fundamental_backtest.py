import copy
from datetime import date

import numpy as np
import pytest

from equity_research.backtest import fundamental as fb
from equity_research.data.sec_edgar import CompanyFacts

from fakes import SYNTHETIC_FUNDAMENTALS
from shortterm_fakes import make_bars


def _facts():
    return CompanyFacts("0000000042", "SYNTHETIC", copy.deepcopy(SYNTHETIC_FUNDAMENTALS), date(2026, 10, 9))


def test_spearman_hand_calculated():
    assert fb.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert fb.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert fb.spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(0.9486833, abs=1e-6)  # ties get average ranks


def test_forward_return_from_next_open_to_close_a_year_later():
    bars = make_bars("SYN", np.linspace(10, 20, 400), opens=np.linspace(10, 20, 400) - 0.5, start=date(2024, 1, 1))
    entry_day = [d for d in bars.dates if d > date(2024, 4, 30)][0]
    exit_day = [d for d in bars.dates if (d - entry_day).days <= 365][-1]
    i, j = list(bars.dates).index(entry_day), list(bars.dates).index(exit_day)
    r = fb.forward_return(bars, date(2024, 4, 30), 365)
    assert r == pytest.approx(bars.close[j] / bars.open[i] - 1)


def test_forward_return_missing_when_history_ends():
    bars = make_bars("SYN", [10] * 50, start=date(2024, 1, 1))
    assert fb.forward_return(bars, date(2024, 2, 1), 365) is None


def test_observation_uses_only_filings_public_on_the_rebalance_date():
    bars = make_bars("SYN", np.linspace(10, 20, 700), start=date(2023, 1, 2))
    early = fb.observe("SYN", "3571", _facts(), bars, date(2024, 4, 30))
    assert early.fiscal_year == date(2023, 12, 31)  # FY2024 10-K was filed 2025-02-14
    late = fb.observe("SYN", "3571", _facts(), bars, date(2025, 4, 30))
    assert late.fiscal_year == date(2024, 12, 31)


def test_stale_statements_are_skipped():
    bars = make_bars("SYN", np.linspace(10, 20, 1200), start=date(2023, 1, 2))
    assert fb.observe("SYN", "3571", _facts(), bars, date(2026, 6, 30)) is None  # latest FY ended > 15 months earlier


def test_group_comparison_uses_excess_over_same_date_universe():
    obs = [fb.Observation("A", date(2020, 4, 30), date(2019, 12, 31), {"piotroski": 8}, 0.30),
           fb.Observation("B", date(2020, 4, 30), date(2019, 12, 31), {"piotroski": 2}, 0.10),
           fb.Observation("C", date(2021, 4, 30), date(2020, 12, 31), {"piotroski": 7}, -0.05),
           fb.Observation("D", date(2021, 4, 30), date(2020, 12, 31), {"piotroski": 3}, -0.15)]
    g = fb.compare(obs, "piotroski >= 7", lambda s: s["piotroski"] >= 7)
    assert g["n"] == 2
    # A: 0.30 vs the 2020 mean 0.20 -> +0.10; C: -0.05 vs the 2021 mean -0.10 -> +0.05
    assert g["mean_excess"] == pytest.approx(0.075)
    assert g["beat_rate"] == pytest.approx(1.0)
    assert g["rest_mean_excess"] == pytest.approx(-0.075)


def test_render_without_and_with_returns():
    import re
    from equity_research.backtest.__main__ import render
    signals = {"piotroski": 8, "piotroski_testable": 9, "beneish_flagged": False, "altman_zone": "safe",
               "revenue_cagr_5y": 0.12, "fcf_rising_years": 4}
    none = render([fb.Observation("A", date(2020, 4, 30), date(2019, 12, 31), signals, None)], [date(2020, 4, 30)],
                  365, "1", ["Stooq blocked"], "test")
    assert "Geen rendementen" in none
    rng = np.random.default_rng(0)
    obs = [fb.Observation(f"T{i}", date(2020 + i % 3, 4, 30), date(2019, 12, 31),
                          dict(signals, piotroski=int(rng.integers(0, 10))), float(rng.normal(0.08, 0.2)))
           for i in range(90)]
    text = render(obs, [date(2020, 4, 30)], 365, "90", [], "test")
    assert "Piotroski >= 7" in text and not re.search(r"\bNone\b|\bnan\b", text)
