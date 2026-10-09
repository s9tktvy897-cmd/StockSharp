from datetime import date

import pytest

from equity_research.data.sec_edgar import EdgarFact
from equity_research.fundamentals.statements import AnnualStatements
from equity_research.risk import scores
from equity_research.risk.scores import NotApplicableError

Y22, Y23, Y24 = date(2022, 12, 31), date(2023, 12, 31), date(2024, 12, 31)


def _fact(value, year):
    return EdgarFact(value=value, unit="USD", source="TEST", reference="synthetic", retrieved=date(2026, 10, 9),
                     period_end=year, currency="USD")


def statements(**items):
    """items: name -> {year: value}. SYNTHETIC numbers for hand-calculated examples."""
    return AnnualStatements("0", "SYNTHETIC", None,
                            {name: {y: _fact(v, y) for y, v in values.items()} for name, values in items.items()}, [])


BASE = dict(
    revenue={Y23: 900, Y24: 1000}, gross_profit={Y23: 360, Y24: 420}, net_income={Y23: 50, Y24: 80},
    operating_cash_flow={Y23: 60, Y24: 120}, total_assets={Y22: 1000, Y23: 1000, Y24: 1100},
    long_term_debt_noncurrent={Y23: 300, Y24: 280}, current_assets={Y23: 400, Y24: 500},
    current_liabilities={Y23: 300, Y24: 320}, diluted_shares={Y23: 100, Y24: 98},
)


def test_piotroski_all_nine():
    # ROA 80/1000 > 0; CFO > 0; ROA up from 50/1000; CFO/assets 0.12 > ROA; LTD/avg assets 280/1050 < 300/1000;
    # current ratio 1.56 > 1.33; shares 98 <= 100; gross margin 42% > 40%; turnover 1000/1000 > 900/1000
    result = scores.piotroski(statements(**BASE), Y24)
    assert result.value == 9
    assert result.testable == 9


def test_piotroski_signal_fails_and_missing_is_counted():
    items = dict(BASE, net_income={Y23: 50, Y24: 40})  # ROA 4% < 5% last year
    result = scores.piotroski(statements(**items), Y24)
    assert result.value == 8
    assert result.signals["delta_roa"].passed is False

    items = {k: v for k, v in BASE.items() if k != "gross_profit"}
    result = scores.piotroski(statements(**items), Y24)
    assert result.testable == 8 and result.value == 8
    assert result.signals["delta_gross_margin"].passed is None


ALTMAN = dict(current_assets={Y24: 500}, current_liabilities={Y24: 320}, total_assets={Y24: 1100},
              retained_earnings={Y24: 200}, operating_income={Y24: 150}, equity={Y24: 400},
              total_liabilities={Y24: 700}, revenue={Y24: 1000})


def test_altman_z_double_prime_hand_calculated():
    z = scores.altman(statements(**ALTMAN), Y24, variant="Z''")
    expected = 6.56 * 180 / 1100 + 3.26 * 200 / 1100 + 6.72 * 150 / 1100 + 1.05 * 400 / 700
    assert z.value == pytest.approx(expected)
    assert z.zone == "safe"  # > 2.60


def test_altman_original_z_uses_market_equity():
    z = scores.altman(statements(**ALTMAN), Y24, variant="Z", market_value_equity=1200)
    expected = 1.2 * 180 / 1100 + 1.4 * 200 / 1100 + 3.3 * 150 / 1100 + 0.6 * 1200 / 700 + 1.0 * 1000 / 1100
    assert z.value == pytest.approx(expected)
    assert z.zone == "grey"  # 0.196 + 0.255 + 0.450 + 1.029 + 0.909 = 2.84, between 1.81 and 2.99


def test_altman_original_without_market_value_is_missing():
    z = scores.altman(statements(**ALTMAN), Y24, variant="Z")
    assert z.value is None and "market value" in z.missing_reason


@pytest.mark.parametrize("value,variant,zone", [(1.5, "Z", "distress"), (2.5, "Z", "grey"), (3.1, "Z", "safe"),
                                                (1.0, "Z''", "distress"), (2.0, "Z''", "grey")])
def test_altman_zones(value, variant, zone):
    assert scores.altman_zone(value, variant) == zone


def test_altman_variant_by_sic():
    assert scores.altman_variant("3571") == "Z"
    assert scores.altman_variant("7372") == "Z''"
    with pytest.raises(NotApplicableError):
        scores.altman_variant("6022")


BENEISH = dict(
    receivables={Y23: 100, Y24: 150}, revenue={Y23: 1000, Y24: 1100}, gross_profit={Y23: 400, Y24: 396},
    current_assets={Y23: 500, Y24: 560}, ppe_net={Y23: 300, Y24: 320}, total_assets={Y23: 1000, Y24: 1200},
    depreciation_amortization={Y23: 50, Y24: 48}, sga={Y23: 150, Y24: 160},
    current_liabilities={Y23: 200, Y24: 260}, long_term_debt_noncurrent={Y23: 200, Y24: 260},
    net_income={Y24: 100}, operating_cash_flow={Y24: 40},
)


def test_beneish_hand_calculated():
    dsri = (150 / 1100) / (100 / 1000)
    gmi = (400 / 1000) / (396 / 1100)
    aqi = (1 - (560 + 320) / 1200) / (1 - (500 + 300) / 1000)
    sgi = 1100 / 1000
    depi = (50 / (50 + 300)) / (48 / (48 + 320))
    sgai = (160 / 1100) / (150 / 1000)
    tata = (100 - 40) / 1200
    lvgi = ((260 + 260) / 1200) / ((200 + 200) / 1000)
    expected = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi - 0.172 * sgai
                + 4.679 * tata - 0.327 * lvgi)
    m = scores.beneish(statements(**BENEISH), Y24)
    assert m.value == pytest.approx(expected)
    assert m.components["dsri"] == pytest.approx(dsri)
    assert m.flagged is (expected > -1.78)


def test_beneish_missing_component_gives_reason():
    items = {k: v for k, v in BENEISH.items() if k != "sga"}
    m = scores.beneish(statements(**items), Y24)
    assert m.value is None and "sga" in m.missing_reason
