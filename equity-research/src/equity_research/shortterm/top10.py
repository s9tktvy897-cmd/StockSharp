"""Daily candidate list: at most ``top_n`` eligible stocks ranked by the model (or the fixed
scanner rule), each with its signals, catalysts, historical reliability and risks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from equity_research.shortterm import catalysts as cat
from equity_research.shortterm.backtest import BacktestResult
from equity_research.shortterm.catalysts import Filing
from equity_research.shortterm.config import Config
from equity_research.shortterm.dataset import Panel
from equity_research.shortterm.evaluation import OutOfSample


@dataclass
class Candidate:
    rank: int
    ticker: str
    name: str
    last_close: float
    last_date: date
    source: str
    score: float
    probability: dict[int, float | None]
    drop_probability: dict[int, float | None]
    history: dict[int, dict]  # out-of-sample top-N stats per horizon
    signals: dict[str, float]
    catalysts: list[Filing] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    conclusion: str = ""


SIGNALS = ("ret_1d", "ret_5d", "gap", "rvol", "volume_trend", "breakout_20", "dist_52w_high", "close_location",
           "atr_pct")


def _window_filings(filings: list[Filing], day: date, days: int = 7) -> list[Filing]:
    return [f for f in filings if 0 <= (day - f.accepted_et.date()).days <= days]


def select(panel: Panel, ranking: np.ndarray, ranked_by: str, probabilities: dict[int, np.ndarray | None],
           oos: dict[int, OutOfSample], backtests: dict[int, BacktestResult], source: str, names: dict[str, str],
           filings: dict[str, list[Filing]] | None, data_problems: dict[str, list[str]], config: Config,
           allowed: bool, drop_probabilities: dict[int, np.ndarray | None] | None = None
           ) -> tuple[list[Candidate], list[str]]:
    """Returns the candidates and the reasons why the list is short or empty."""
    notes = []
    if not len(panel.dates):
        return [], ["no rows to rank"]
    latest = max(panel.dates)
    rows = np.where((panel.dates == latest) & panel.eligible & np.isfinite(ranking))[0]
    excluded = 0
    keep = []
    for row in rows[np.argsort(-ranking[rows], kind="stable")]:
        ticker = panel.tickers[row]
        recent = _window_filings((filings or {}).get(ticker, []), latest)
        if data_problems.get(ticker) or any(set(f.items) & {"3.01", "1.03", "4.02"} for f in recent):
            excluded += 1
            continue
        keep.append(row)
    if excluded:
        notes.append(f"{excluded} aandelen uitgesloten wegens datafouten of een 8-K over delisting, faillissement of "
                     "onbetrouwbare eerdere cijfers")
    if not allowed:
        notes.append("geen rangschikking slaagde voor de toets buiten de trainingsdata, dus geen enkel aandeel is kandidaat")
        return [], notes

    out = []
    for rank, row in enumerate(keep[:config.top_n], 1):
        ticker = panel.tickers[row]
        signals = {name: float(panel.column(name)[row]) for name in SIGNALS}
        recent = _window_filings((filings or {}).get(ticker, []), latest)
        probability = {h: (float(p[row]) if p is not None and oos[h].gate.passed else None)
                       for h, p in probabilities.items()}
        drop_probability = {h: (float(p[row]) if p is not None else None)
                            for h, p in (drop_probabilities or {}).items()}
        history = {h: backtests[h].summary for h in backtests}
        pct = lambda x: f"{x * 100:.1f}%".replace(".", ",")
        risks = [f"gemiddelde dagbeweging (ATR) {pct(signals['atr_pct'])} van de koers"]
        h_max = max(backtests)
        if backtests[h_max].summary.get("trades"):
            s = backtests[h_max].summary
            risks.append(f"in de backtest daalde {pct(s['drop_rate'])} van de top-picks binnen {h_max} dag(en) 10% of meer")
        if signals["gap"] > 0.05 or signals["ret_1d"] > 0.10:
            risks.append("al sterk gestegen: een deel van de beweging kan al in de koers zitten (terugvalrisico)")
        spread = config.costs.per_side(panel.dollar_volume[row])
        risks.append(f"aangenomen kosten {pct(spread).replace(',0%', '%')} per kant "
                     f"(liquiditeit {panel.dollar_volume[row] / 1e6:,.0f} mln USD/dag)".replace(",", "."))
        for f in recent:
            if set(f.items) & cat.NEGATIVE:
                risks.append(f"8-K {cat.leaning(f.items)} op {f.accepted_et:%Y-%m-%d}")
        validated = [h for h, p in probability.items() if p is not None]
        up = max((p for p in probability.values() if p is not None), default=None)
        down = max((p for p in drop_probability.values() if p is not None), default=None)
        conclusion = (f"#{rank} op {ranked_by}. "
                      + (f"Gekalibreerde kans beschikbaar voor {', '.join(f'{h}d' for h in validated)}. " if validated
                         else "Geen gevalideerde kans: alleen een rangschikking. ")
                      + ("De kans op een daling van 10% of meer is vergelijkbaar of groter: vooral een beweeglijk "
                         "aandeel, geen richting. " if up is not None and down is not None and down >= 0.75 * up else "")
                      + "Een kandidaat voor onderzoek, geen handelsopdracht.")
        out.append(Candidate(rank, ticker, names.get(ticker, ""), float(panel.price[row]), latest, source,
                             float(ranking[row]), probability, drop_probability, history, signals, recent, risks,
                             conclusion))
    if len(out) < config.top_n:
        notes.append(f"{len(out)} van maximaal {config.top_n} aandelen voldeden aan de voorwaarden")
    return out, notes
