# Short-term engine ("stock explosion prediction")

An addition to the long-term analysis (fundamentals, DCF, scores, screens), not a
replacement. Question: which US stocks rise at least 10% within one or two trading days after a
signal, and can that be predicted out of sample after costs? Research only: no orders, no
guarantees. Code: `src/equity_research/shortterm/`.

## Timeline of one decision

| Moment | What is known |
|---|---|
| Close of day t (16:00 ET) | the bar of t; features use bars up to and including t |
| 16:00 ET – 09:00 ET next trading day | 8-K filings accepted now are "overnight" catalysts (not in a regular-session price) |
| 09:00 ET on t+1 | decision (the daily scan) |
| Open of t+1 | entry; the overnight gap is not capturable |
| t+1 … t+h | target +10% (limit), optional stop, else exit at the close of t+h |

## Data

| Data | Source | Status |
|---|---|---|
| Daily OHLCV | Stooq (secondary) or `--bars-dir` with `<TICKER>.csv` from any licensed provider | Stooq blocked in the build environment |
| Universe | SEC `company_tickers_exchange.json`, NYSE + Nasdaq | live; current listings only (survivorship bias) |
| Catalysts | SEC 8-K: `submissions` (history, acceptance time in UTC, item codes) and the EDGAR live Atom feed | live |
| Premarket/after-hours, options, short interest, newswires | not available here (blocked or paid) | not used |

`bars.validate` flags impossible bars and close-to-close jumps that look like unadjusted splits;
flagged tickers are never candidates.

## Features (`features.py`, `catalysts.py`, `dataset.py`)

Returns 1/5/20 days, opening gap, relative volume (volume / mean of the 20 previous days),
volume trend, ATR %, volatility ratio (5d / 60d), close vs prior 20-day high (breakout), close vs
52-week high, close location in the day's range, log price, log dollar volume, universe median
1d/20d return and breadth (same day), and 8-K flags: overnight (any, earnings 2.02, deal
1.01/2.01/5.01, press 7.01/8.01, negative-leaning), during the day, recent 7 days. The item code
gives the type of event, not its direction.

## Outcomes (`labels.py`)

From the open of t+1: `hit` = high within t+1..t+h ≥ 1.10 × open; `drop` = low ≤ 0.90 × open;
close-to-open return. Rows whose window crosses a data gap (> 5 calendar days) get no outcome.

## Models and validation (`models.py`, `evaluation.py`)

Candidates: logistic regression (L2 0.1 / 10 / 1000, standardized, mean-imputed), gradient
boosting (scikit-learn, Platt-calibrated on validation), the base rate, and a fixed, unfitted
scanner rule as a benchmark. Walk-forward per calendar year Y: train on years < Y−1, choose the
model and calibrate on Y−1, test once on Y; rows within horizon + 3 days before a boundary are
dropped (embargo). Out-of-sample predictions from all test years are judged together.

**Probability gate** — a model output is shown as a probability only if, out of sample:
≥ 30 events; Brier skill score > 0 vs the base rate (measured before the first test year);
expected calibration error ≤ ½ × base rate; and the daily top-10 hit rate has a 95% Wilson lower
bound above the base rate. Otherwise the engine ranks without probabilities, and if neither the
model nor the scanner rule passes the top-10 test it lists **no candidates**.

## Backtest (`backtest.py`)

Daily top 10 (eligible: price ≥ $2, 20-day dollar volume ≥ $5M, ≥ 60 days of history). Entry at
the next open; exit at +10% (or at the open when it gaps above), else at the horizon close.
Target and stop in one bar → the stop is assumed. Costs per side: slippage 10 bp + half-spread
5/15/30 bp by dollar volume (≥ $50M / ≥ $10M / below) + commission 0 bp — assumptions, not
measured spreads. Reported: hit rate (+10%) with CI, share with a ≥ 10% fall, mean and median net
return with a 95% CI for the mean, win rate, payoff ratio, profit factor, max drawdown (each
signal day gets 1/h of the capital), by year and by market regime (universe 20-day median return
up/down), against holding every eligible stock. "Historically profitable" is only claimed when
the lower bound of the 95% CI of the mean net return is above zero.

## Daily workflow

`equity-research shortterm scan --stooq` (or `--bars-dir DIR`): data check → panel → walk-forward
tests and backtests per horizon → production model (trained up to the last year, validated on
it) → top 10 → `predictions/<date>.jsonl` → `reports/shortterm/scan_<date>.md`.
`equity-research shortterm evaluate` compares logged picks with the bars that came after;
`equity-research shortterm catalysts` lists new 8-Ks. GitHub Actions
(`.github/workflows/equity-research.yml`) runs the tests on every change and the scan on weekdays
at 08:45 New York (from the default branch; needs the `EQUITY_RESEARCH_USER_AGENT` secret).

**Model improvement without overfitting**: new model ideas are judged on the same walk-forward
protocol; the most recent test year is not used to tune. Prediction logs are the truly unseen
test: compare their realized hit rate with the predicted probabilities before trusting changes.

## Known limits

Survivorship bias (current listings only); daily bars cannot show premarket/after-hours moves or
the order of intraday highs and lows; spreads are assumed; 8-K text is not read automatically;
small, low-priced stocks dominate +10% moves and are partly excluded by the liquidity filter.
