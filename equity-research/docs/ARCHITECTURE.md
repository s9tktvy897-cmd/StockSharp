# Architecture

Goal: a reproducible, source-traceable pipeline for fundamental equity analysis.
Every number either comes from a cited source or is computed from such numbers.

```
            ┌──────────────┐   SourcedValue   ┌──────────────┐
 sources ──▶│ data/        │─────────────────▶│ fundamentals/│ normalized statements, ratios
 (EDGAR,    │ adapters +   │                  └──────┬───────┘
  FRED,     │ disk cache   │                         │
  prices)   └──────────────┘          ┌──────────────┼───────────────┐
                                      ▼              ▼               ▼
                               ┌────────────┐ ┌────────────┐ ┌────────────┐
                               │ valuation/ │ │ screening/ │ │ risk/      │
                               │ DCF, WACC, │ │ value,     │ │ Altman,    │
                               │ reverse,   │ │ growth,    │ │ Beneish,   │
                               │ multiples  │ │ Piotroski  │ │ vol, DD    │
                               └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
                                     └──────────────┼──────────────┘
                                                    ▼
                          ┌────────────┐     ┌────────────┐
                          │ backtest/  │     │ report/    │──▶ reports/<TICKER>_<date>.md
                          │ point-in-  │     │ markdown   │
                          │ time tests │     └────────────┘
                          └────────────┘
```

## Packages (`src/equity_research/`)

| Module | Responsibility | Phase |
|---|---|---|
| `provenance.py` | `SourcedValue`, `Assumption`: value + source metadata; missing data is explicit | 0 |
| `data/` | Source adapters (SEC EDGAR companyfacts, FRED, Damodaran, prices) with on-disk cache, rate limiting, and the filing date of every fact (needed for point-in-time backtests) | 1 |
| `fundamentals/` | Map XBRL tags → normalized income/balance/cash-flow statements; ratios, CAGR, ROIC, FCF | 2 |
| `valuation/` | WACC (CAPM), 2-stage FCFF DCF, terminal value (Gordon + exit multiple), reverse DCF, sensitivity grid, scenarios, multiples | 3 |
| `risk/` | Altman Z (Z, Z', Z''), Beneish M, Piotroski F, volatility, beta, max drawdown, leverage | 4 |
| `screening/` | Value and growth screens built from the above, thresholds from `METHODOLOGY.md` | 4 |
| `backtest/` | Point-in-time screen replay, forward returns vs benchmark, hit rate, IC, drawdown; bias checklist | 5 |
| `report/` | Markdown report: facts, assumptions, valuation, risks, data-quality section | 6 |
| `cli.py` | `equity-research analyze AAPL`, `screen`, `backtest` | 6 |

## Design rules

- **Pure calculation functions** (no I/O) in fundamentals/valuation/risk, so they are
  unit-testable against textbook examples.
- **I/O only in `data/`**; everything downstream works on cached, typed data.
- **Fail loudly**: invalid inputs (WACC ≤ g, negative share count, mixed currencies) raise
  errors instead of returning a number.
- **Point-in-time**: every fact keeps `filed` (date it became public) next to `period_end`.

## Environment note

In the cloud session where this was scaffolded, the egress proxy blocked `data.sec.gov`;
PyPI was reachable. Data adapters must therefore be developed against recorded fixtures,
and live fetching needs either a local run or the host added to the environment's network
allowlist.
