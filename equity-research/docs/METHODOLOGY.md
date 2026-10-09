# Methodology

Formulas and thresholds used by the system. Each one gets a unit test with a worked example
before it is used in an analysis. Sources are standard references (Damodaran, *Investment
Valuation*; McKinsey, *Valuation*; the original papers for the scores).

## Fundamentals (phase 2, `fundamentals/`)

Statements come from SEC company facts, one normalized line item per list of synonym XBRL
tags (`fundamentals/concepts.py`, priority order). A tag switch over the years and any
disagreement > 0.5% between tags for the same period are reported as data-quality issues.

- **Stock splits** are inferred from the filings: a later filing restating the share count of
  the same period by a common split ratio (whole number, 3/2, 5/4, 5/2, 4/3; within 2%) marks a
  split between the two filing dates. Share counts and per-share values filed before it are
  adjusted. Only filings public on the as-of date are used (no look-ahead).
- **Optional components** (marketable securities, debt parts): a component a company never
  reports counts as 0, with a note; a gap in a component it does report is missing data.
- FCF = operating cash flow − capex (payments for PP&E).
- Margins: gross/operating/net profit, FCF ÷ revenue. FCF conversion = FCF ÷ net income.
- Effective tax rate = income tax ÷ pretax income (undefined for pretax ≤ 0).
  NOPAT = operating income × (1 − effective tax rate).
- Total debt = long-term debt (non-current + current) + commercial paper + short-term
  borrowings. Operating leases are excluded.
- Net debt = total debt − cash − current marketable securities. Non-current marketable
  securities are left out here and treated as non-operating assets in the valuation.
- Invested capital = equity + total debt − cash − all marketable securities (McKinsey's
  financing view). ROIC = NOPAT ÷ average invested capital; undefined when the average is ≤ 0.
  Companies with large securities portfolios and negative working capital (e.g. Apple) have
  negative or tiny invested capital, so ROIC is also reported as return on capital including
  cash = NOPAT ÷ average (equity + total debt).
- ROE = net income ÷ average equity. Buybacks can shrink equity and inflate ROE.
- Accruals ratio (Sloan, 1996) = (net income − operating cash flow) ÷ average total assets.
- Net debt / EBITDA, EBITDA = operating income + D&A (cash-flow statement).
- Interest coverage = operating income ÷ interest expense.
- Shareholder payout = (dividends paid + buybacks) ÷ FCF. Dilution = y/y change in
  split-adjusted diluted weighted shares.
- CAGR = (end ÷ start)^(1/n) − 1, defined only for positive start and end.

## DCF (FCFF, two-stage)

- FCFF = EBIT × (1 − t) + D&A − capex − ΔNWC
- WACC = E/V · r_e + D/V · r_d · (1 − t), with r_e = r_f + β · ERP (CAPM)
- Terminal value (Gordon) = FCFF_{n+1} / (WACC − g), requires WACC > g
- Cross-check terminal value with an exit EV/EBIT multiple; report both.
- Equity value = EV − net debt − minorities + non-operating assets; per share on diluted shares.
- Always report: TV share of EV, sensitivity grid (WACC ±2pp × g ±1pp), bear/base/bull.

## Reverse DCF

Solve for the stage-1 growth rate that makes DCF value = current market price.

## Quality and risk scores

- Piotroski F-score (Piotroski, 2000): 9 binary tests; ≥ 7 strong, ≤ 3 weak.
- Altman Z (1968) for manufacturers; Z'' (1995) for non-manufacturers/emerging markets.
  Not applicable to banks/insurers -- the system must refuse and say so.
- Beneish M-score (1999), 8-variable: > −1.78 flags possible earnings manipulation.

## Classification (initial thresholds, to be validated in backtests)

- **Undervalued**: base-case intrinsic value ≥ 1.25 × price (25% margin of safety),
  Piotroski ≥ 5, Altman not in distress zone, Beneish below threshold.
- **Growth**: revenue CAGR 5y ≥ 10%, positive and rising FCF in ≥ 3 of last 5 years,
  ROIC > WACC.

Thresholds are hypotheses. Phase 5 tests them point-in-time; results and their biases are
documented here once available.
