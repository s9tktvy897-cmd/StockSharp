# Methodology

Formulas and thresholds used by the system. Each one gets a unit test with a worked example
before it is used in an analysis. Sources are standard references (Damodaran, *Investment
Valuation*; McKinsey, *Valuation*; the original papers for the scores).

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
