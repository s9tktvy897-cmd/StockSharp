# Exploratory studies (2026-10-10)

Run from `equity-research/` after `python -m equity_research.research run` has filled `data/cache_research`.
They are **exploratory**: they do not change any strategy status of the pre-registered protocol, every
condition x rule is a trial in a Holm correction, and the results are in `reports/research/`.

| Script | Question | Output |
|---|---|---|
| `open_study.py data/cache_research OUT.json` | after the open (daily bars, 2017–2025): which situations reach +5/+7/+10% and what do exit rules earn? | `after_open_daily_2026-10-10.json` |
| `hourly_download.py data/cache_hourly TICKERS.json` | hourly bars (Yahoo, last ~730 days) | cache only |
| `hourly_study.py data/cache_research data/cache_hourly OUT.json` | highest point of the day after the open, its hour, giveback, exit rules (Oct 2024 – Oct 2026) | `after_open_hourly_2026-10-10.json` |
| `holding_study.py data/cache_research OUT.json` | how long must a position be held for an average result >= +5% after costs, and how likely is a loss? | `holding_period_2026-10-10.json` |
| `fundamental_bt.py OUT.md` | fundamental screens and factors on 600 point-in-time stocks | `reports/backtest/fundamental_validation_2026-10-10.md` |
