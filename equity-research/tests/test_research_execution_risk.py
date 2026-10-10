from datetime import date

import numpy as np
import pytest

from equity_research.research import portfolio
from equity_research.research.execution import CostModel, fillable_value
from equity_research.research.portfolio import ExitRule, MarketData
from equity_research.research.risk import Order, PortfolioState, RiskLimits, RiskManager

from shortterm_fakes import make_bars, trading_days


def test_cost_model_hand_calculated():
    m = CostModel(commission_bps=1, slippage_bps=10, tiers=((10e6, 5.0), (0.0, 30.0)), impact_coef=0.5)
    # liquid stock, tiny order: 1 + 10 + 5 bp, impact 0.5 * 2% * sqrt(1e4/1e8) = 0.0001
    assert m.per_side(1e4, 1e8, 0.02, None) == pytest.approx((1 + 10 + 5) / 1e4 + 0.0001)
    # a $0.50 stock: half a one-cent tick is 1%, more than the tier
    assert m.per_side(1e4, 1e8, 0.0, 0.50) == pytest.approx((1 + 10) / 1e4 + 0.01)
    # a $100 stock: the tick floor (0.005%) is below the 5 bp tier
    assert m.per_side(1e4, 1e8, 0.0, 100.0) == pytest.approx((1 + 10 + 5) / 1e4)
    # stress doubles everything but commission
    assert m.stressed(2.0).per_side(1e4, 1e8, 0.0, None) == pytest.approx(1 / 1e4 + 2 * 15 / 1e4)


def test_fill_is_capped_by_participation():
    assert fillable_value(50_000, 1e6, 0.01) == 10_000
    assert fillable_value(5_000, 1e6, 0.01) == 5_000
    assert fillable_value(5_000, 0.0, 0.01) == 0.0


def _order(ticker="A", value=10_000, price=10, dv=1e7, vol=0.02, spread=0.005, sector="35"):
    return Order(ticker, date(2024, 1, 2), 1.0, value, price, dv, vol, spread, sector)


def _state(**kw):
    base = dict(equity=100_000, invested=0.0, positions={}, sector_of={})
    base.update(kw)
    return PortfolioState(**base)


def test_risk_layer_blocks_and_sizes():
    rm = RiskManager(RiskLimits(max_position=0.10, risk_per_position=0.005, max_sector=0.30, min_price=2,
                                min_dollar_volume=5e6, max_spread=0.02))
    d = rm.check([_order(price=1.5), _order("B", dv=1e6), _order("C", spread=0.05), _order("D")], _state(),
                 sleeve_value=50_000, slots=1)
    reasons = [r for _, r in d.blocked]
    assert reasons == ["price below minimum", "dollar volume below minimum", "spread above maximum"]
    # D: share 50k, max position 10k, risk budget 0.005*100k/0.02 = 25k, requested 10k -> 10k
    assert [o.ticker for o in d.accepted] == ["D"] and d.accepted[0].value == pytest.approx(10_000)
    # a volatile stock gets a smaller position: 0.005 * 100k / 0.10 = 5k
    d = rm.check([_order("E", vol=0.10)], _state(), sleeve_value=50_000, slots=1)
    assert d.accepted[0].value == pytest.approx(5_000)


def test_sector_and_exposure_limits():
    rm = RiskManager(RiskLimits(max_sector=0.30, max_gross_exposure=1.0, risk_per_position=1.0))
    s = _state(invested=25_000, positions={"X": 25_000}, sector_of={"X": "35"})
    d = rm.check([_order("A", value=10_000, sector="35")], s, sleeve_value=50_000, slots=1)
    assert d.accepted[0].value == pytest.approx(5_000)  # only 5k room left in sector 35
    s = _state(invested=99_800, positions={"X": 99_800}, sector_of={"X": "10"})
    d = rm.check([_order("A")], s, sleeve_value=50_000, slots=1)
    assert d.accepted == [] and "no room" in d.blocked[0][1]


def test_correlation_limit():
    rm = RiskManager(RiskLimits(risk_per_position=1.0), correlation=lambda a, b, d: 0.95)
    d = rm.check([_order("A")], _state(positions={"X": 1.0}, invested=1.0), sleeve_value=50_000, slots=1)
    assert d.accepted == [] and "correlation with X" in d.blocked[0][1]


def test_drawdown_and_daily_loss_block_new_orders():
    rm = RiskManager(RiskLimits(drawdown_limit=-0.20, daily_loss_limit=-0.03, cooloff_days=5))
    s = _state(drawdown=-0.25, day=10)
    rm.update(s)
    assert s.blocked_until == 15
    assert rm.check([_order()], s, 50_000).accepted == []
    s = _state(last_return=-0.04, day=3)
    rm.update(s)
    assert s.blocked_until == 4
    s.day = 5
    assert rm.check([_order()], s, 50_000, slots=1).accepted


def _market(prices: dict[str, tuple], start=date(2024, 1, 1)):
    universe = {}
    for t, (o, h, l, c) in prices.items():
        universe[t] = make_bars(t, c, opens=o, highs=h, lows=l, volumes=np.full(len(c), 1e7), start=start)
    return MarketData(universe)


NO_COST = CostModel(slippage_bps=0, tiers=((0.0, 0.0),), impact_coef=0.0, tick=0.0)
LOOSE = RiskLimits(max_position=1.0, risk_per_position=10.0, max_spread=1.0, max_sector=1.0, min_dollar_volume=0)


def test_portfolio_enters_next_open_and_exits_at_horizon_close():
    n = 30
    flat = np.full(n, 10.0)
    o = flat.copy(); h = flat.copy(); l = flat.copy(); c = flat.copy()
    o[21], c[21], h[21] = 11.0, 12.0, 12.0   # entry day: opens at 11
    o[22], c[22], h[22], l[22] = 12.0, 13.2, 13.2, 12.0
    m = _market({"A": (o, h, l, c)})
    days = list(m.bars["A"].dates)
    res = portfolio.simulate(m, {days[20]: [("A", 1.0)]}, days, ExitRule(horizon=2), NO_COST,
                             RiskManager(LOOSE), top_n=1, capital=100_000)
    t = res.trades[0]
    assert t.entry_date == days[21] and t.exit_date == days[22] and t.reason == "time"
    assert t.net == pytest.approx(13.2 / 11.0 - 1)   # the jump before the open (10 -> 11) is not captured
    assert t.entry_value == pytest.approx(100_000 / 2)  # sleeve = equity / horizon
    equity = np.cumprod(1 + res.returns)[-1] * 100_000
    assert equity == pytest.approx(100_000 + 50_000 * (13.2 / 11 - 1))


def test_stop_gaps_through_and_fills_at_the_open():
    n = 30
    flat = np.full(n, 10.0)
    o = flat.copy(); h = flat.copy(); l = flat.copy(); c = flat.copy()
    o[22], h[22], l[22], c[22] = 7.0, 7.2, 6.8, 7.0   # gap far below a 10% stop
    m = _market({"A": (o, h, l, c)})
    days = list(m.bars["A"].dates)
    res = portfolio.simulate(m, {days[20]: [("A", 1.0)]}, days, ExitRule(horizon=5, stop=0.10), NO_COST,
                             RiskManager(LOOSE), top_n=1, capital=100_000)
    t = res.trades[0]
    assert t.reason == "stop (gap below)" and t.net == pytest.approx(7.0 / 10.0 - 1)  # not the -10% stop price


def test_missing_bar_on_fill_day_cancels_the_order():
    n = 30
    a = make_bars("A", np.full(n, 10.0), volumes=np.full(n, 1e7))
    days = list(a.dates)
    keep = np.array([i != 21 for i in range(n)])
    from equity_research.shortterm.bars import Bars
    halted = Bars("A", a.dates[keep], a.open[keep], a.high[keep], a.low[keep], a.close[keep], a.volume[keep], "x")
    m = MarketData({"A": halted})
    res = portfolio.simulate(m, {days[20]: [("A", 1.0)]}, days, ExitRule(horizon=2), NO_COST,
                             RiskManager(LOOSE), top_n=1, capital=100_000)
    assert res.trades == [] and sum(res.cancelled.values()) == 1


def test_participation_cap_gives_a_partial_fill():
    n = 30
    a = make_bars("A", np.full(n, 10.0), volumes=np.full(n, 1_000.0))  # $10k a day
    m = MarketData({"A": a})
    days = list(a.dates)
    res = portfolio.simulate(m, {days[20]: [("A", 1.0)]}, days, ExitRule(horizon=1), NO_COST,
                             RiskManager(LOOSE), top_n=1, capital=100_000)
    assert res.trades == [] and res.cancelled  # 1% of $10k = $100 < minimum order: not filled
    a = make_bars("A", np.full(n, 10.0), volumes=np.full(n, 300_000.0))  # $3M a day -> 1% = $30k
    m = MarketData({"A": a})
    res = portfolio.simulate(m, {days[20]: [("A", 1.0)]}, days, ExitRule(horizon=1), NO_COST,
                             RiskManager(LOOSE), top_n=1, capital=100_000)
    assert res.trades[0].partial and res.trades[0].entry_value == pytest.approx(30_000)


def test_no_trade_when_there_are_no_picks():
    a = make_bars("A", np.full(30, 10.0))
    m = MarketData({"A": a})
    res = portfolio.simulate(m, {}, list(a.dates), ExitRule(horizon=1), NO_COST, RiskManager(LOOSE))
    assert res.trades == [] and np.allclose(res.returns, 0) and res.no_trade_days == 30


def test_kill_switch_fires_once_per_breach_and_trading_restarts():
    # A stock that falls 3% every day: the strategy keeps buying it and keeps losing.
    n = 200
    closes = 100 * 0.97 ** np.arange(n)
    a = make_bars("A", closes, opens=closes / 0.97, volumes=np.full(n, 1e9))  # falls during each day
    m = MarketData({"A": a})
    days = list(a.dates)
    picks = {d: [("A", 1.0)] for d in days[25:]}
    limits = RiskLimits(max_position=1.0, risk_per_position=10.0, max_spread=1.0, max_sector=1.0,
                        min_dollar_volume=0, min_price=0, daily_loss_limit=-0.99, drawdown_limit=-0.20,
                        cooloff_days=10, max_participation=1.0)
    res = portfolio.simulate(m, picks, days, ExitRule(horizon=1), NO_COST, RiskManager(limits), top_n=1,
                             capital=100_000)
    assert res.kill_switches >= 2                       # it restarted after the cool-off and fired again
    entries = sorted({t.entry_date for t in res.trades})
    assert entries[-1] > days[150]                      # trading resumed late in the period
    from equity_research.research import stats
    assert stats.max_drawdown(res.returns) < -0.30      # the real drawdown is reported, not capped at -20%


def test_vectorized_correlations_match_the_pairwise_ones():
    rng = np.random.default_rng(1)
    n = 120
    base = rng.normal(0, 0.02, n)
    universe = {}
    for k, mix in enumerate((1.0, 0.9, 0.0, -0.8)):
        r = mix * base + np.sqrt(max(1 - mix * mix, 0)) * rng.normal(0, 0.02, n)
        closes = 50 * np.cumprod(1 + r)
        universe[f"S{k}"] = make_bars(f"S{k}", closes)
    m = MarketData(universe)
    day = m.bars["S0"].dates[100]
    many = m.correlations("S0", ["S1", "S2", "S3"], day)
    for t, c in zip(["S1", "S2", "S3"], many):
        assert c == pytest.approx(m.correlation("S0", t, day), abs=1e-6)
    rm = RiskManager(RiskLimits(risk_per_position=10.0, max_correlation=0.8, max_spread=1.0, min_dollar_volume=0),
                     correlation_many=m.correlations)
    d = rm.check([_order("S0")], _state(positions={"S1": 1.0}, invested=1.0), 50_000, slots=1)
    assert d.accepted == [] and "S1" in d.blocked[0][1]
