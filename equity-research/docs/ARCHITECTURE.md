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
| `data/` | ✅ SEC EDGAR (ticker→CIK, profile/SIC, company facts with point-in-time `annual`/`quarterly`/`history`), ✅ FRED CSV, ✅ disk cache, rate limit, retries. Stooq prices and Damodaran (ERP, industry betas): built on synthetic fixtures, not yet verified live | 1, 3 |
| `fundamentals/` | ✅ XBRL tags → normalized annual statements (tag fallbacks, split detection/adjustment, point-in-time), ratios, CAGR, ROIC, FCF, consistency checks, TTM and latest balance sheet from 10-Qs | 2, 3 |
| `valuation/` | ✅ WACC (CAPM, Hamada), 2-stage FCFF DCF with fade, terminal value (Gordon + implied exit multiple), reverse DCF, sensitivity grid, bear/base/bull from history, market multiples. Peer multiples: later | 3 |
| `risk/` | ✅ beta, volatility, max drawdown (`market.py`). Altman Z (Z, Z', Z''), Beneish M, Piotroski F: phase 4 | 3, 4 |
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

Tests use synthetic fixtures only (`tests/fakes.py`), so they run without network access.
Live fetching needs `data.sec.gov`, `www.sec.gov`, `fred.stlouisfed.org`, `stooq.com` and
`pages.stern.nyu.edu` reachable and `EQUITY_RESEARCH_USER_AGENT` set; the SessionStart hook
reports both. Without Stooq/Damodaran the valuation shows value per share over a WACC range.
