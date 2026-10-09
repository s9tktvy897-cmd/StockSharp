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
| `data/` | ✅ SEC EDGAR (ticker→CIK, profile/SIC, company facts with point-in-time `annual`/`quarterly`/`history`), ✅ FRED CSV, ✅ disk cache, rate limit, retries. Damodaran (ERP from histimpl.html, industry betas) verified live 2026-10-09; Stooq prices built on synthetic fixtures, not yet verified live | 1, 3 |
| `fundamentals/` | ✅ XBRL tags → normalized annual statements (tag fallbacks, split detection/adjustment, point-in-time), ratios, CAGR, ROIC, FCF, consistency checks, TTM and latest balance sheet from 10-Qs | 2, 3 |
| `valuation/` | ✅ `run.py` (end-to-end valuation, reused by risk/report), WACC (CAPM, Hamada), 2-stage FCFF DCF with fade, terminal value (Gordon + implied exit multiple), reverse DCF, sensitivity grid, bear/base/bull from history, market multiples. Peer multiples: later | 3 |
| `risk/` | ✅ beta, volatility, max drawdown (`market.py`); ✅ Piotroski F, Altman Z / Z'' (variant by SIC), Beneish M (`scores.py`) | 3, 4 |
| `screening/` | ✅ Value and growth screens (three-valued), thresholds from `METHODOLOGY.md`. Multi-ticker universe screen: phase 5 | 4 |
| `backtest/` | Point-in-time screen replay, forward returns vs benchmark, hit rate, IC, drawdown; bias checklist | 5 |
| `report/` | ✅ Markdown report in Dutch (`markdown.py`, sections follow CLAUDE.md §2: scope, data, data quality, fundamentals, scores, valuation with facts and assumptions apart, classification, risks, sources); Dutch number format (`format.py`) | 6 |
| `shortterm/` | ✅ Short-term engine (+10% in 1–2 days): bars + validation, point-in-time features, SEC 8-K catalysts, walk-forward models with a probability gate, backtest with costs, daily top 10, prediction log, report. See `SHORT_TERM_ENGINE.md` | 7 |
| `cli.py` | ✅ `equity-research {data,fundamentals,valuation,risk,analyze} TICKER`, `equity-research shortterm {scan,catalysts,evaluate}`; `screen` (universe) and `backtest`: phase 5 | 6 |

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
