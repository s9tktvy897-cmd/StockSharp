"""``equity-research backtest [--tickers A,B | --max-tickers N] (--stooq | --bars-dir DIR) [--start 2014 --end 2025]``

Point-in-time replay of the long-term screens; writes ``reports/backtest/fundamental_<date>.md``."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np

from equity_research.backtest import fundamental as fb
from equity_research.data.__main__ import CACHE_DIR
from equity_research.data.cache import DiskCache
from equity_research.data.http import HttpClient, user_agent_from_env
from equity_research.data.sec_edgar import SecEdgar
from equity_research.report.format import MISSING, nl, pct
from equity_research.report.markdown import _git_revision
from equity_research.shortterm.sources import ShortTermSources, load
from equity_research.valuation.run import FETCH_ERRORS

REPORTS = Path(__file__).resolve().parents[3] / "reports" / "backtest"
MIN_N = 30


def render(observations: list[fb.Observation], rebalances: list[date], horizon: int, universe: str,
           missing: list[str], code: str) -> str:
    with_return = [o for o in observations if o.forward_return is not None]
    L = [f"# Backtest langetermijnscreens — {date.today()}", "",
         "> Onderzoek naar het verleden, geen voorspelling of advies. Rendementen zijn overrendementen t.o.v. het "
         "gelijkgewogen gemiddelde van het universum op dezelfde datum.", "",
         "## 1. Opzet", ""]
    L += [f"- Universum: {universe}", f"- Herbalancering: {', '.join(str(d) for d in rebalances)}",
          f"- Horizon: {horizon} dagen, instap op de eerste opening na de datum, uitstap op het laatste slot binnen de horizon",
          "- Point-in-time: jaarcijfers zoals op de herbalanceringsdatum ingediend (latere herzieningen tellen niet), "
          "splits pas na de split; jaarcijfers ouder dan 15 maanden worden overgeslagen",
          f"- Waarnemingen: {len(observations)}, met rendement: {len(with_return)}",
          f"- Code: {code}", ""]
    L += ["**Vertekeningen:** survivorship bias (alleen nu genoteerde aandelen; verdwenen bedrijven ontbreken, wat "
          "resultaten te gunstig maakt); de volgorde van de SEC-lijst bevoordeelt grote bedrijven; drempels komen uit de "
          "literatuur en zijn niet op deze data afgesteld; geen transactiekosten (jaarlijkse herbalancering).", ""]
    if missing:
        L += ["**Ontbrekend:** " + "; ".join(missing[:8]) + (" …" if len(missing) > 8 else ""), ""]
    L += ["## 2. Screens", ""]
    if not with_return:
        L += ["Geen rendementen beschikbaar (geen koersdata), dus geen uitkomsten.", ""]
        return "\n".join(L)
    rows, verdicts = [], []
    for name, rule in fb.RULES.items():
        g = fb.compare(observations, name, rule)
        if not g["n"]:
            rows.append([name, "0", MISSING, MISSING, MISSING, MISSING, str(g["rest_n"]), MISSING])
            continue
        rows.append([name, str(g["n"]), pct(g["mean_excess"]), pct(g["median_excess"]),
                     f"{pct(g['beat_rate'])} ({pct(g['beat_ci'][0])}–{pct(g['beat_ci'][1])})", nl(g["t_stat"], 2),
                     str(g["rest_n"]), pct(g.get("rest_mean_excess"))])
        if g["n"] < MIN_N:
            verdicts.append(f"{name}: te weinig waarnemingen ({g['n']} < {MIN_N}) voor een conclusie")
        elif abs(g["t_stat"]) > 2:
            verdicts.append(f"{name}: gemiddeld overrendement {pct(g['mean_excess'])} met |t| = {nl(abs(g['t_stat']), 2)} > 2 "
                            "— een aanwijzing, geen bewijs (meerdere screens getest)")
        else:
            verdicts.append(f"{name}: geen aantoonbaar verschil met het universum (|t| = {nl(abs(g['t_stat']), 2)})")
    L += ["| Screen | n | Gem. overrendement | Mediaan | Beter dan universum (95%-BI) | t | n rest | Gem. rest |",
          "|---|---|---|---|---|---|---|---|"] + ["| " + " | ".join(r) + " |" for r in rows] + [""]
    L += [f"- {v}" for v in verdicts] + [""]
    ic = fb.information_coefficients(observations, "piotroski")
    L += ["## 3. Rangcorrelatie Piotroski-score en rendement (per datum, ≥ 10 aandelen)", ""]
    if ic:
        values = [v for v in ic.values() if np.isfinite(v)]
        L += ["| Datum | Spearman |", "|---|---|"] + [f"| {d} | {nl(v, 3)} |" for d, v in ic.items()] + [""]
        if values:
            L += [f"Gemiddeld {nl(float(np.mean(values)), 3)} over {len(values)} data.", ""]
    else:
        L += ["Te weinig aandelen per datum.", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="equity-research backtest")
    p.add_argument("--tickers")
    p.add_argument("--max-tickers", type=int, default=100)
    p.add_argument("--bars-dir", type=Path)
    p.add_argument("--stooq", action="store_true")
    p.add_argument("--start", type=int, default=2014)
    p.add_argument("--end", type=int, default=date.today().year - 1)
    p.add_argument("--month", type=int, default=4, help="rebalance month (default April, after most 10-Ks)")
    p.add_argument("--horizon-days", type=int, default=365)
    args = p.parse_args(argv)

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    data = load(tickers, args.bars_dir, args.stooq, use_sec=False, max_tickers=args.max_tickers)
    edgar = SecEdgar(HttpClient(user_agent_from_env()), DiskCache(CACHE_DIR))
    rebalances = [date(y, args.month, 30 if args.month in (4, 6, 9, 11) else 28) for y in range(args.start, args.end + 1)]
    names = tickers or sorted(data.bars)
    observations, missing = [], list(data.missing)
    for ticker in names:
        try:
            cik = edgar.cik_for_ticker(ticker)
            sic, facts = edgar.profile(cik).sic, edgar.company_facts(cik)
        except FETCH_ERRORS as error:
            missing.append(f"SEC {ticker}: {error}")
            continue
        for day in rebalances:
            o = fb.observe(ticker, sic, facts, data.bars.get(ticker), day, args.horizon_days)
            if o:
                observations.append(o)
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"fundamental_{date.today()}.md"
    universe = f"{len(names)} aandelen ({data.bars_source or 'geen koersbron'})"
    path.write_text(render(observations, rebalances, args.horizon_days, universe, missing, _git_revision()),
                    encoding="utf-8")
    print(f"report written: {path} ({len(observations)} observations)")


if __name__ == "__main__":
    main()
