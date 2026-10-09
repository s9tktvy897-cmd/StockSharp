from datetime import date

import pytest

from equity_research.data import damodaran
from equity_research.data.prices import STOOQ_URL, Stooq, parse_stooq_csv, stooq_symbol
from equity_research.provenance import MissingDataError

from fakes import FakeTransport, make_cache, make_client

# SYNTHETIC CSV in Stooq's daily download layout.
CSV = "Date,Open,High,Low,Close,Volume\n2026-10-06,10,11,9,10.5,1000\n2026-10-07,10.5,12,10,11.25,1200\n"


def test_stooq_symbol():
    assert stooq_symbol("AAPL") == "aapl.us"
    assert stooq_symbol("BRK.B") == "brk-b.us"
    assert stooq_symbol("^SPX") == "^spx"


def test_parse_stooq_closes_are_secondary():
    prices = parse_stooq_csv(CSV, "aapl.us", date(2026, 10, 9), "u")
    assert [(p.period_end, p.value) for p in prices] == [(date(2026, 10, 6), 10.5), (date(2026, 10, 7), 11.25)]
    assert "secondary" in prices[0].source
    assert prices[0].currency == "USD"


def test_stooq_no_data_raises():
    with pytest.raises(MissingDataError):
        parse_stooq_csv("No data", "zzzz.us", date(2026, 10, 9), "u")


def test_stooq_adapter_uses_cache(tmp_path):
    transport = FakeTransport({STOOQ_URL.format(symbol="aapl.us"): (200, CSV.encode())})
    stooq = Stooq(make_client(transport), make_cache(tmp_path))
    assert stooq.daily_closes("AAPL")[-1].value == 11.25
    stooq.daily_closes("AAPL")
    assert len(transport.calls) == 1


# SYNTHETIC HTML shaped like Damodaran's data pages (header row followed by data rows).
BETAS_HTML = """<html><body><table>
<tr><td>Industry Name</td><td>Number of firms</td><td>Beta</td><td>D/E Ratio</td><td>Unlevered beta</td>
<td>Unlevered beta corrected for cash</td></tr>
<tr><td>Widgets</td><td>12</td><td>1.10</td><td>20.00%</td><td>0.95</td><td>1.02</td></tr>
<tr><td>Gadgets</td><td>8</td><td>1.30</td><td>10.00%</td><td>1.20</td><td>1.25</td></tr>
</table></body></html>"""

ERP_HTML = """<table><tr><td>Year</td><td>T.Bond Rate</td><td>Implied Premium (DDM)</td><td>Implied Premium (FCFE)</td></tr>
<tr><td>2024</td><td>4.58%</td><td>3.10%</td><td>4.30%</td></tr>
<tr><td>2025</td><td>4.40%</td><td>3.00%</td><td>4.20%</td></tr></table>"""


def test_industry_beta_prefers_cash_corrected_column():
    beta = damodaran.industry_beta(BETAS_HTML, "gadgets", retrieved=date(2026, 10, 9), url="u")
    assert beta.value == 1.25
    assert "Gadgets" in beta.reference and "corrected for cash" in beta.reference


def test_unknown_industry_lists_choices():
    with pytest.raises(MissingDataError) as error:
        damodaran.industry_beta(BETAS_HTML, "Spaceships", retrieved=date(2026, 10, 9), url="u")
    assert "Widgets" in str(error.value)


def test_implied_erp_latest_year_fcfe():
    erp = damodaran.implied_erp(ERP_HTML, retrieved=date(2026, 10, 9), url="u")
    assert erp.value == pytest.approx(0.042)
    assert erp.period_end == date(2025, 12, 31)


def test_unexpected_layout_fails_loudly():
    with pytest.raises(ValueError):
        damodaran.implied_erp("<table><tr><td>a</td></tr></table>", retrieved=date(2026, 10, 9), url="u")


# SYNTHETIC, shaped like histimpl.html (checked live 2026-10-09): page date line, then the table.
HISTIMPL_HTML = """<p>Date : January 2026</p><table>
<tr><td>Year</td><td>T.Bond Rate</td><td>Smoothed Growth</td><td>Implied ERP (FCFE)</td></tr>
<tr><td>2024</td><td>4.58%</td><td>4.61%</td><td>4.40%</td></tr>
<tr><td>2025</td><td>4.18%</td><td>4.61%</td><td>4.10%</td></tr></table>"""


def test_implied_erp_reads_histimpl_layout_and_page_date():
    erp = damodaran.implied_erp(HISTIMPL_HTML, retrieved=date(2026, 10, 9), url="u")
    assert erp.value == pytest.approx(0.041)
    assert "January 2026" in erp.reference


def test_stale_erp_table_is_refused():
    with pytest.raises(MissingDataError) as error:
        damodaran.implied_erp(ERP_HTML, retrieved=date(2029, 1, 5), url="u")
    assert "2025" in str(error.value)


def test_erp_url_is_the_maintained_page():
    assert damodaran.IMPLIED_ERP_URL.endswith("histimpl.html")
