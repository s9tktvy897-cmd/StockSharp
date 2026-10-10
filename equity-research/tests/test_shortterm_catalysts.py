from datetime import date, datetime, timedelta, timezone

import numpy as np

from equity_research.shortterm import catalysts
from equity_research.shortterm.catalysts import Filing

from shortterm_fakes import make_bars

# SYNTHETIC submissions in the layout of data.sec.gov/submissions (checked live 2026-10-09).
SUBMISSIONS = {"cik": "42", "name": "SYNTHETIC CO", "tickers": ["SYN"], "filings": {"recent": {
    "accessionNumber": ["A-1", "A-2", "A-3", "A-4"],
    "form": ["8-K", "10-Q", "8-K", "8-K"],
    "items": ["2.02,9.01", "", "1.01", "3.01"],
    # 2020-01-07 21:30Z = 16:30 ET (after the close of Tue 7 Jan); 2020-01-08 15:00Z = 10:00 ET (during Wed 8 Jan)
    "acceptanceDateTime": ["2020-01-07T21:30:00.000Z", "2020-01-07T22:00:00.000Z", "2020-01-08T15:00:00.000Z",
                           "2020-01-03T13:00:00.000Z"],
    "filingDate": ["2020-01-07", "2020-01-07", "2020-01-08", "2020-01-03"],
}}}

ATOM = """<?xml version="1.0" encoding="ISO-8859-1" ?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>8-K - SYNTHETIC CO (0000000042) (Filer)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/42/x/A-9-index.htm"/>
<summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-10-09 &lt;b&gt;AccNo:&lt;/b&gt; A-9 &lt;b&gt;Size:&lt;/b&gt; 1 KB
&lt;br&gt;Item 2.02: Results of Operations and Financial Condition
&lt;br&gt;Item 9.01: Financial Statements and Exhibits</summary>
<updated>2026-10-09T17:26:20-04:00</updated><category scheme="https://www.sec.gov/" label="form type" term="8-K"/>
</entry></feed>"""


def test_parse_submissions_keeps_8k_with_items_and_utc_time():
    filings = catalysts.parse_submissions(SUBMISSIONS, "SYN")
    assert [f.accession for f in filings] == ["A-4", "A-1", "A-3"]  # sorted by acceptance, 10-Q dropped
    assert filings[1].items == ("2.02", "9.01")
    assert filings[1].accepted == datetime(2020, 1, 7, 21, 30, tzinfo=timezone.utc)
    assert filings[1].accepted_et.hour == 16 and filings[1].accepted_et.minute == 30


def test_parse_current_feed():
    [f] = catalysts.parse_current_feed(ATOM)
    assert f.cik == "0000000042" and f.accession == "A-9" and f.items == ("2.02", "9.01")
    assert f.accepted == datetime(2026, 10, 9, 21, 26, 20, tzinfo=timezone.utc)


def test_item_classification():
    assert catalysts.describe(("2.02", "9.01")) == "earnings"
    assert "negative" in catalysts.leaning(("3.01",))
    assert catalysts.leaning(("8.01",)) == "unknown direction"


def test_features_split_overnight_from_intraday():
    # trading days from Mon 2020-01-06: 06, 07, 08, 09, ...
    bars = make_bars("SYN", [10] * 6, start=date(2020, 1, 6))
    f = catalysts.features(bars, catalysts.parse_submissions(SUBMISSIONS, "SYN"))
    day = {d: i for i, d in enumerate(bars.dates)}
    # earnings 16:30 ET on Tue 7 Jan: overnight for the decision after Tue's close (row of 7 Jan)
    assert f["cat_overnight_earnings"][day[date(2020, 1, 7)]] == 1
    assert f["cat_overnight_any"][day[date(2020, 1, 6)]] == 0
    # the agreement at 10:00 ET on Wed 8 Jan: the market saw it during Wed -> intraday on the row of 8 Jan
    assert f["cat_day_any"][day[date(2020, 1, 8)]] == 1
    assert f["cat_overnight_any"][day[date(2020, 1, 8)]] == 0
    # negative-leaning filing (3.01, 3 Jan) is before the series: counted in the recent window of 6 Jan
    assert f["cat_recent_negative"][day[date(2020, 1, 6)]] == 1


def test_no_filing_after_decision_leaks_into_features():
    bars = make_bars("SYN", [10] * 3, start=date(2020, 1, 6))
    late = Filing("SYN", "42", "Z", "8-K", ("2.02",), datetime(2020, 1, 8, 14, 0, tzinfo=timezone.utc), "u")  # 09:00 ET Wed
    f = catalysts.features(bars, [late])
    # decision for the row of Tue 7 Jan is taken at 09:00 ET Wed; a filing at exactly that time counts,
    # one a second later would not
    assert f["cat_overnight_earnings"][1] == 1
    later = Filing("SYN", "42", "Z", "8-K", ("2.02",), datetime(2020, 1, 8, 14, 0, 1, tzinfo=timezone.utc), "u")
    assert catalysts.features(bars, [later])["cat_overnight_earnings"][1] == 0


def _filing(accepted_utc):
    return Filing("SYN", "42", f"A-{accepted_utc:%m%d%H}", "8-K", ("2.02",), accepted_utc, f"u{accepted_utc:%m%d}")


def test_correct_submission_times_need_no_change():
    filings = [_filing(datetime(2025, 7, 31, 20, 30, tzinfo=timezone.utc)),
               _filing(datetime(2026, 1, 29, 21, 30, tzinfo=timezone.utc))]
    index = {f.url: f.accepted for f in filings}  # the filing pages agree
    fixed, status = catalysts.calibrate_times(filings, lambda url: index[url])
    assert status == "verified" and fixed == filings


def test_shifted_times_are_kept_never_moved_earlier():
    # Live 2026-10-09: per filing (not per filer) some submissions times are the true time + the New York
    # offset. Moving any filing earlier could leak future news, so times are kept as they are (late at worst).
    true = [datetime(2025, 7, 30, 20, 30, tzinfo=timezone.utc), datetime(2026, 1, 29, 21, 30, tzinfo=timezone.utc)]
    shifted = [_filing(datetime(2025, 7, 31, 0, 30, tzinfo=timezone.utc)), _filing(datetime(2026, 1, 30, 2, 30, tzinfo=timezone.utc))]
    index = {f.url: t for f, t in zip(shifted, true)}
    kept, status = catalysts.calibrate_times(shifted, lambda url: index[url])
    assert kept == shifted
    assert status.startswith("late")


def test_mixed_times_are_kept_too():
    filings = [_filing(datetime(2025, 7, 31, 20, 30, tzinfo=timezone.utc)),
               _filing(datetime(2026, 1, 29, 21, 30, tzinfo=timezone.utc))]
    index = {filings[0].url: filings[0].accepted, filings[1].url: filings[1].accepted - timedelta(hours=5)}
    kept, status = catalysts.calibrate_times(filings, lambda url: index[url])
    assert kept == filings and status.startswith("late")


def test_times_earlier_than_the_filing_page_are_dropped():
    filings = [_filing(datetime(2025, 7, 31, 20, 30, tzinfo=timezone.utc))]
    index = {filings[0].url: filings[0].accepted + timedelta(hours=3)}  # data says earlier than the truth
    kept, status = catalysts.calibrate_times(filings, lambda url: index[url])
    assert kept == [] and status.startswith("unreliable")


def test_company_reads_older_submission_files_and_sic():
    import json
    from equity_research.shortterm.sources import Listing, ShortTermSources
    older = {"accessionNumber": ["A-0"], "form": ["8-K"], "items": ["2.02"],
             "acceptanceDateTime": ["2015-02-03T21:30:00.000Z"], "filingDate": ["2015-02-03"]}
    main = dict(SUBMISSIONS, sic="3571", filings=dict(SUBMISSIONS["filings"],
                files=[{"name": "CIK0000000042-submissions-001.json"}]))
    every = catalysts.parse_submissions(main, "SYN") + catalysts.parse_submissions(
        {"cik": "42", "filings": {"recent": older}}, "SYN")
    true_time = {f.url: f.accepted for f in every}

    class Fake(ShortTermSources):
        def __init__(self):
            self.urls = []

        def _get(self, url, max_age):
            self.urls.append(url)
            return json.dumps(older if url.endswith("-001.json") else main).encode()

        def accepted_on_index(self, url):
            return true_time[url]

    fake = Fake()
    company = fake.company(Listing("SYN", "0000000042", "SYNTHETIC CO", "Nasdaq"), full_history=True)
    assert company.sic == "3571" and company.timing == "verified"
    assert [f.accession for f in company.filings] == ["A-0", "A-4", "A-1", "A-3"]
    assert fake.urls[1].endswith("CIK0000000042-submissions-001.json")


def test_earnings_reaction_flag_covers_close_to_close():
    bars = make_bars("SYN", [10] * 5, start=date(2020, 1, 6))
    day = {d: i for i, d in enumerate(bars.dates)}
    f = catalysts.features(bars, catalysts.parse_submissions(SUBMISSIONS, "SYN"))
    # earnings 16:30 ET Tue 7 Jan: the market reacts on Wed 8 Jan -> flag on the row of 8 Jan (known at its close)
    assert f["cat_reaction_earnings"][day[date(2020, 1, 8)]] == 1
    assert f["cat_reaction_earnings"][day[date(2020, 1, 7)]] == 0
    assert f["cat_reaction_earnings"][day[date(2020, 1, 9)]] == 0
    # an earnings release at 15:00 ET on Thu 9 Jan (before the close) is the reaction of 9 Jan itself
    intraday = Filing("SYN", "42", "E", "8-K", ("2.02",), datetime(2020, 1, 9, 20, 0, tzinfo=timezone.utc), "u")
    g = catalysts.features(bars, [intraday])
    assert g["cat_reaction_earnings"][day[date(2020, 1, 9)]] == 1
    # one second after Thursday's close it belongs to Friday
    after = Filing("SYN", "42", "E", "8-K", ("2.02",), datetime(2020, 1, 9, 21, 0, 1, tzinfo=timezone.utc), "u")
    assert catalysts.features(bars, [after])["cat_reaction_earnings"][day[date(2020, 1, 10)]] == 1
