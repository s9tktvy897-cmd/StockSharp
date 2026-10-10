# Research protocol (pre-registered)

Written and committed **before** the research runner produced any result. The thresholds live in
`src/equity_research/research/protocol.py`; the git history of both files is the proof of the
order. A change after results were seen is a protocol change and is reported as such.

## Question

Is there a strategy on US common stocks (NYSE/Nasdaq) that, with realistic execution and costs,
has a positive expected net return that survives a correction for the number of strategies tried,
an untouched final holdout and higher costs? A negative answer is a valid result.

## Data and its limits

- Daily bars from Yahoo Finance (secondary, unofficial), 10 years, total-return adjusted. The price
  filter uses the price actually traded (rebuilt from the split history), not the split-adjusted one.
- 8-K filings with acceptance times from SEC EDGAR (official), including the older submission files;
  times are never moved earlier (`catalysts.calibrate_times`). SIC codes from EDGAR for sectors.
- **Survivorship bias:** the universe is today's listings (SEC ticker file). Delisted, bankrupt and
  acquired companies are missing; free sources with their full history were not available. Results
  are therefore biased upward, most for small caps and short horizons. Not corrected, only reported.
- No intraday, bid/ask, short-interest, options or news data beyond SEC filings.

## Periods

| | From | To |
|---|---|---|
| Development | data start + 260 trading days of warm-up | 2025-10-01 minus 30 days of embargo |
| Final holdout | 2025-10-01 | end of data |

Fitted models walk forward per calendar year: train on years < Y-1, choose and calibrate on Y-1,
test once on Y (purge/embargo of horizon + 3 days at each boundary; at most 1.5 million training
rows, sampled with a fixed seed). For the holdout they are trained on the development period only.

## Execution (all strategies, `research/portfolio.py`, `research/execution.py`)

Decision after the close of t with data up to t (8-Ks up to 09:00 ET of t+1); buy at the open of
t+1; sell at the close of t+h. Costs per side: slippage 10 bp + half-spread (the larger of a
liquidity tier 5/15/30 bp and half the stock's Corwin-Schultz spread) + square-root impact
(0.5 x daily volatility x sqrt(order / daily dollar volume)). Fills capped at 1% of the fill day's
dollar volume; no bar on the fill day = not filled; a history that ends early is closed at its last
close and counted. Cost stress: 1x, 2x, 3x.

## Risk layer (`research/risk.py`, the same for every strategy)

Capital 1,000,000; each signal day invests at most equity / h (h sleeves), split over at most 10
positions. Per position at most 10% of equity and at most 0.5% of equity x (1 / daily volatility).
Gross exposure <= 100% (no leverage, no shorts). At most 30% of equity per SIC major group. No new
position with a 60-day correlation > 0.8 to a held one. Price >= $2 traded, 20-day dollar volume >= $5M,
estimated spread <= 2%. A day below -3% blocks new orders the next day; a drawdown below -20% blocks
new orders for 20 trading days. No admissible order = no trade (cash).

## Strategies (fixed definitions; top 10 by score among eligible stocks each day)

| Strategy | Hypothesis | Score / condition | Horizons |
|---|---|---|---|
| MOMENTUM_12_1 | 12-month winners (skipping the last month) keep outperforming (Jegadeesh & Titman 1993) | `mom_12_1` | 5, 10, 20 |
| REVERSAL_5D | short-term overreaction in liquid stocks reverses (Lehmann 1990) | `-ret_5d`, only 20-day dollar volume >= $50M | 1, 2, 5 |
| BREAKOUT_VOLUME | volume breakouts continue (the existing scanner rule) | scanner rule | 1, 2, 5 |
| TREND_60D | trends persist in a rising market (Moskowitz et al. 2012) | `ret_60d` if close > MA50 > MA200 and SPY > its MA200 | 10, 20 |
| EARNINGS_DRIFT | prices drift after a positive earnings surprise (Bernard & Thomas 1989) | gap if an earnings 8-K (item 2.02) came after the previous close, gap >= 3% and close >= open | 5, 10, 20 |
| VOL_COMPRESSION_BREAKOUT | a breakout after quiet trading continues | `rvol` if close > prior 20-day high, RVOL >= 2, 20/120-day volatility ratio < 0.9 | 2, 5, 10 |
| EXISTING_TARGET10 | the current engine: P(+10% touched), +10% limit exit | classifier score (walk-forward) | 1, 2 |
| MODEL_A_DIRECTION | features predict the sign of the net return | P(net return > 0); only P > 0.5 | 1, 2, 5, 10, 20 |
| MODEL_B_EXPECTED_RETURN | features predict the net return | E[net return]; only E > 0 | 1, 2, 5, 10, 20 |
| MODEL_C_RISK_ADJUSTED | ranking by return per unit of risk and model doubt | (E - abs(E_ridge - E_boosting)) / (vol_20 x sqrt(h)); only numerator > 0 | 1, 2, 5, 10, 20 |

34 variants in total; each counts as a trial. Benchmarks (not candidates): random selection through
the same simulator, the equal-weighted eligible universe, SPY buy and hold.

## Criteria (development period, base costs)

1. at least 200 trades; 2. mean net return per trade >= +0.10%; 3. mean daily portfolio return > 0
with a one-sided stationary-bootstrap p-value (blocks of 20 days) that survives Holm-Bonferroni at
5% over all 34 variants; 4. Sharpe ratio above SPY's on the same days; 5. maximum drawdown >= -25%;
6. mean daily return > 0 at 2x costs; 7. positive mean daily return in >= 60% of calendar years and
in both regimes (SPY above / below its 200-day average); 8. mean per trade without the best 1% of
trades > 0. Also reported: deflated Sharpe ratio for 34 trials, 3x costs, CIs per trade clustered
by signal day.

**Holdout** (once, at the end, all variants): mean daily return > 0, mean net per trade > 0,
maximum drawdown >= -25%, mean daily return > 0 at 2x costs.

## Status

REJECTED (fails a development criterion other than Holm) / RESEARCH ONLY (passes before but not
after Holm, or fails the holdout) / PAPER TRADING CANDIDATE (passes everything) / PAPER TRADING
VALIDATED (a candidate with >= 100 closed paper trades over >= 3 months and a mean net return whose
95% interval lies above zero). No strategy is promoted on a single backtest. If nothing reaches
PAPER TRADING CANDIDATE, the verdict is **NO PROVEN EDGE**.
