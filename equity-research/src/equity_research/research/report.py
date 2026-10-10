"""Dutch Markdown report of a research run: every variant with its status, criteria, development
and holdout results, cost stress and benchmarks. Negative results are shown like positive ones."""

from __future__ import annotations

from equity_research.research import protocol

CRITERIA_NL = {
    "min_trades": f"≥ {protocol.MIN_TRADES} trades",
    "min_edge": f"≥ {protocol.MIN_EDGE_PER_TRADE:.2%} netto per trade",
    "significant_unadjusted": "significant (p < 5%)",
    "significant_holm": "significant na Holm-correctie",
    "beats_spy_sharpe": "Sharpe boven SPY",
    "max_drawdown": f"max. drawdown ≥ {protocol.MAX_DRAWDOWN:.0%}",
    "cost_stress_2x": "winstgevend bij 2× kosten",
    "positive_years": f"≥ {protocol.MIN_POSITIVE_YEAR_SHARE:.0%} van de jaren positief",
    "both_regimes": "positief in stijgende én dalende markt",
    "not_extreme_driven": "positief zonder beste 1% trades",
}


def _p(x, d=2):
    if x is None:
        return "–"
    return f"{x * 100:.{d}f}%".replace(".", ",")


def _n(x, d=2):
    return "–" if x is None else f"{x:.{d}f}".replace(".", ",")


def render(js: dict, meta: dict) -> str:
    v = js["variants"]
    candidates = [r for r in v if r["status"] in ("PAPER TRADING CANDIDATE", "PAPER TRADING VALIDATED")]
    verdict = "PAPER TRADING CANDIDATE" if candidates else (
        "RESEARCH ONLY" if any(r["status"] == "RESEARCH ONLY" for r in v) else "NO PROVEN EDGE")
    L = [f"# Onderzoek naar een handelsvoordeel — {meta['date']}", "",
         "> Historische simulatie met realistische uitvoering en kosten. Geen beleggingsadvies, geen garantie. "
         "Alleen resultaten die uit de code en de data volgen; negatieve uitkomsten staan er net zo in.", "",
         f"**Eindoordeel van deze run: {verdict}**", "",
         "## 1. Opzet", "",
         f"- Protocol vooraf vastgelegd: `docs/RESEARCH_PROTOCOL.md` (commit {meta.get('protocol_commit', '?')}); "
         f"code {meta.get('code', '?')}.",
         f"- Data: {meta['bars_source']}; {meta['tickers']} aandelen met koersen, {js['excluded']} uitgesloten wegens "
         f"datafouten; SEC 8-K's: {meta['sec']}.",
         f"- Ontwikkelperiode tot {meta['dev_end']}, finale holdout vanaf {protocol.HOLDOUT_START} (eenmalig geëvalueerd).",
         f"- {len(protocol.GRID)} varianten getest; elke variant telt mee in de Holm-correctie en de deflated Sharpe.",
         "- **Survivorship bias:** het universum bestaat uit huidige noteringen; verdwenen bedrijven ontbreken. "
         "Resultaten zijn daardoor te gunstig, vooral bij kleine aandelen.", ""]
    for note in js.get("notes", []):
        L.append(f"- {note}")
    L += ["", "## 2. Overzicht (ontwikkelperiode, basiskosten)", "",
          "| Variant | Status | Trades | Netto/trade (95%-BI per signaaldag) | CAGR | Sharpe | Max. DD | 2× kosten (gem./dag) | Holdout netto/trade | Holdout Sharpe |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(v, key=lambda r: (protocol.STATUSES.index(r["status"]) * -1, -(r["dev"].get("sharpe") or -9))):
        d, h = r["dev"], r["holdout"]
        ci = r["trade_ci"]
        L.append(f"| {r['variant']} | {r['status']} | {d.get('trade_trades', 0)} | {_p(d.get('trade_expected_value'))} "
                 f"({_p(ci[0])} – {_p(ci[1])}) | {_p(d.get('cagr'), 1)} | {_n(d.get('sharpe'))} | {_p(d.get('max_drawdown'), 1)} | "
                 f"{_p(r['dev_2x'].get('mean_daily'), 3)} | {_p(h.get('trade_expected_value'))} | {_n(h.get('sharpe'))} |")
    L += ["", "## 3. Benchmarks (zelfde periodes)", "", "| Benchmark | CAGR | Sharpe | Max. DD |", "|---|---|---|---|"]
    for k, b in js["benchmarks"].items():
        L.append(f"| {k} | {_p(b.get('cagr'), 1)} | {_n(b.get('sharpe'))} | {_p(b.get('max_drawdown'), 1)} |")
    L += ["", "Gelijkgewogen universum zonder kosten (bovengrens voor passief); RANDOM gaat door dezelfde "
          "simulatie met kosten en risicolaag als de strategieën.", "",
          "## 4. Criteria per variant", ""]
    keys = list(CRITERIA_NL)
    L += ["| Variant | " + " | ".join(CRITERIA_NL[k] for k in keys) + " | Holdout |",
          "|---|" + "---|" * (len(keys) + 1)]
    for r in v:
        c = r["criteria"]
        L.append(f"| {r['variant']} | " + " | ".join("ja" if c.get(k) else "nee" for k in keys)
                 + f" | {'ja' if r['holdout_ok'] else 'nee'} |")
    L += ["", "## 5. Details per variant", ""]
    for r in v:
        d = r["dev"]
        years = ", ".join(f"{y}: {_p(m, 3)}" for y, m in r["years"].items())
        L += [f"### {r['variant']} — {r['status']}", "",
              f"- Periode {r['period'][0]} – {r['period'][1]}; trades {d.get('trade_trades', 0)}, winstkans "
              f"{_p(d.get('trade_win_rate'), 1)}, gem. winst {_p(d.get('trade_avg_win'))}, gem. verlies "
              f"{_p(d.get('trade_avg_loss'))}, profit factor {_n(d.get('trade_profit_factor'))}.",
              f"- Portefeuille: CAGR {_p(d.get('cagr'), 1)}, Sharpe {_n(d.get('sharpe'))} (SPY zelfde dagen "
              f"{_n(r['spy_sharpe'])}), Sortino {_n(d.get('sortino'))}, max. drawdown {_p(d.get('max_drawdown'), 1)}, "
              f"Calmar {_n(d.get('calmar'))}, gem. belegd {_p(d.get('exposure'), 0)}, omloop {_n(d.get('turnover'), 1)}×/jaar, "
              f"gem. kosten heen+terug {_p(d.get('avg_cost'))}.",
              f"- Gem. dagrendement {_p(d.get('mean_daily'), 3)} (95%-BI blokbootstrap {_p(r['daily_ci'][0], 3)} – "
              f"{_p(r['daily_ci'][1], 3)}; p = {_n(r['p_value'], 4)}); deflated Sharpe (34 proeven) "
              f"{_n(r['deflated_sharpe'], 3)}.",
              f"- Kostenstress: gem. dagrendement 2× {_p(r['dev_2x'].get('mean_daily'), 3)}, 3× "
              f"{_p(r['dev_3x'].get('mean_daily'), 3)}.",
              f"- Per jaar (gem. dagrendement): {years or '–'}; stijgende markt {_p(r['regimes']['rising'], 3)}, "
              f"dalende markt {_p(r['regimes']['falling'], 3)}.",
              f"- Holdout: trades {r['holdout'].get('trade_trades', 0)}, netto/trade "
              f"{_p(r['holdout'].get('trade_expected_value'))}, Sharpe {_n(r['holdout'].get('sharpe'))}, max. DD "
              f"{_p(r['holdout'].get('max_drawdown'), 1)}, 2× kosten gem./dag {_p(r['holdout_2x'].get('mean_daily'), 3)}.",
              f"- Geblokkeerd door de risicolaag: {sum(r['blocked'].values())} ({', '.join(f'{k}: {n}' for k, n in sorted(r['blocked'].items(), key=lambda x: -x[1])[:4]) or '–'}); "
              f"niet uitgevoerd: {sum(r['cancelled'].values())}; noodstop (drawdown −20%, 20 dagen pauze, daarna herstart) "
              f"{d.get('kill_switches', 0)}×; deelvullingen {d.get('partial_fills', 0)}.",
              (f"- Gekozen modellen: {', '.join(f'{k}: {m}' for k, m in r['chosen'].items())}." if r["chosen"] else ""),
              ""]
    L += ["## 6. Beperkingen", "",
          "- Survivorship bias (zie boven); geen intraday-, bied/laat- of nieuwsdata buiten SEC.",
          "- Kosten en marktimpact zijn modellen (aannames); bij beweeglijke kleine aandelen zijn echte kosten vaak hoger.",
          "- Yahoo is een onofficiële bron; datafouten zijn gecontroleerd maar niet uit te sluiten.",
          "- Een positieve backtest is geen bewijs: alleen na de holdout en een paper-tradingperiode kan een strategie verder.", ""]
    return "\n".join(L)
