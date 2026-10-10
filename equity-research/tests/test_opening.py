from datetime import date

import pytest

from equity_research.shortterm import opening
from equity_research.shortterm.opening import RiskPlan, Situation


def _study(mean_net, significant=False, holdout=0.001, lo=None):
    lo = mean_net - 0.002 if lo is None else lo
    return {"results": [{"condition": "opening gap", "value": "< -10%", "n": 3000, "p_peak_5": 0.57, "p_low_5": 0.5,
                         "rules": {"+5% until close": {"mean_net": mean_net, "ci": [lo, mean_net + 0.002],
                                                       "significant_holm": significant,
                                                       "halves": {"2025-10..2026-10": holdout}}}}]}


def _stock(ticker="AAA", open_=8.5, prev=10.0, items=()):
    return Situation(ticker, "Synthetic", prev, open_, 0.0, opening.news_label(list(items)), 5e7)


def test_buckets_and_news():
    s = _stock(open_=8.5)
    assert s.gap == pytest.approx(-0.15) and s.cells()["opening gap"] == "< -10%"
    assert _stock(open_=10.5).cells()["opening gap"] == "+3..+10%"
    assert opening.news_label([("2.02", "9.01")]) == "earnings 8-K"
    assert opening.news_label([("1.01",)]) == "deal 8-K"
    assert opening.news_label([("8.01",)]) == "other 8-K"
    assert opening.news_label([]) == "no 8-K"


def test_no_trade_unless_validated():
    d = opening.decide([_stock()], _study(0.004, significant=False), None)
    assert d.verdict == "NO TRADE" and d.tradable == [] and len(d.watch) == 1
    d = opening.decide([_stock()], _study(0.004, significant=True, holdout=-0.001), None)
    assert d.verdict == "NO TRADE"  # significant but negative in the holdout
    d = opening.decide([_stock()], _study(0.004, significant=True, holdout=0.002), None)
    assert d.tradable and d.verdict.startswith("PAPER TRADE")


def test_trade_plan_and_risk_sizing():
    plan = opening.trade_plan(20.0, target=0.05, stop=0.05)
    assert plan["limit"] == pytest.approx(21.0) and plan["stop"] == pytest.approx(19.0)
    # 1% of 10,000 at risk with a 5% stop -> at most 2,000 in the position
    assert RiskPlan(account=10_000, risk_per_trade=0.01).position_value(0.05) == pytest.approx(2_000)


def test_report_says_no_trade_and_never_buy():
    d = opening.decide([_stock()], _study(-0.001), None)
    text = opening.render(d, date(2026, 10, 12), RiskPlan(), [])
    assert "NO TRADE" in text and "Volglijst" in text
    assert "koop " not in text.lower().replace("koopsignaal", "")
