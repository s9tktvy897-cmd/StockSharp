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

### Implementation (phase 3, `valuation/`)

- **Base period**: trailing twelve months from the latest 10-Q (fiscal year + current YTD −
  prior-year YTD); balance sheet and diluted shares from the same filing. Cash flows fall one
  year apart from the base period end and are discounted to the valuation date.
- **Forecast**: 5 years at the stage-1 revenue growth, then 5 years fading linearly to terminal
  growth. EBIT margin, tax rate, D&A and capex (% of revenue) are constant; ΔNWC = NWC% × Δrevenue.
- **Terminal FCFF** = NOPAT_{n+1} × (1 − g / RONIC): the reinvestment needed to grow at g when new
  capital earns RONIC. The model refuses g ≥ RONIC and WACC ≤ g. The exit-multiple cross-check
  is reported as the implied EV/EBIT of the Gordon terminal value.
- **Equity bridge**: EV + cash + all marketable securities − debt (book) − minority interest;
  operating leases are not counted as debt (consistent with FCFF before lease payments).
- **WACC inputs**: r_f = 10-year Treasury (FRED DGS10). ERP = Damodaran implied ERP (FCFE). Beta:
  manual > bottom-up (Damodaran unlevered industry beta, re-levered with Hamada at market D/E; the
  industry is an analyst choice) > 60-month regression vs S&P 500. Cost of debt = interest
  expense / average debt of the latest year that reports interest (flagged when stale). Tax =
  mean effective rate of the last 3 years. E at market value, D at book value.
- **Default assumptions** (`valuation/assumptions.py`), each with a rationale:
  stage-1 growth bear/base/bull = min/median/max of the 3/5/10-year revenue CAGRs; EBIT margin
  = min of 5y / mean of 3y / max of 5y; tax, D&A, capex, NWC = 3-year means; terminal growth =
  market-implied 10-year inflation (FRED T10YIE, zero real growth) capped at r_f; RONIC = 3-year
  mean return on capital incl. cash (bear: RONIC = WACC, no excess returns on new capital).
- **Manual inputs** are accepted only with a source text (`--price … --price-source …`) and are
  labelled "manual input" in the output.

## Reverse DCF

Solve for the stage-1 growth rate that makes DCF value = current market price (bisection over
−50%…+100%; the model reports when no growth in that range reproduces the price).

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
