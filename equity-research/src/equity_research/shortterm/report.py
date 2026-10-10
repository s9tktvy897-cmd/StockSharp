"""Daily Markdown report of the short-term engine (Dutch)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from equity_research.report.format import MISSING, nl, pct
from equity_research.shortterm import catalysts as cat
from equity_research.shortterm.catalysts import Filing
from equity_research.shortterm.engine import EngineResult
from equity_research.shortterm.models import SCANNER_RULE

DISCLAIMER = ("> **Onderzoek, geen beleggingsadvies en geen garantie.** Het doel (+10% binnen 1–2 handelsdagen) is "
              "zeldzaam en risicovol; ook de beste kandidaten halen het meestal niet en kunnen fors dalen. Er worden "
              "geen orders geplaatst. Kansen worden alleen getoond als het model buiten de trainingsdata aantoonbaar "
              "en gekalibreerd beter is dan de basiskans.")


def _table(header, rows):
    return ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"] + \
           ["| " + " | ".join(str(c).replace("|", "/") for c in row) + " |" for row in rows] + [""]


def _summary_row(label, s, max_dd=None):
    if not s.get("trades"):
        return [label, "0", MISSING, MISSING, MISSING, MISSING, MISSING, MISSING, MISSING]
    lo, hi = s["mean_net_ci"]
    return [label, s["trades"], f"{pct(s['hit_rate'])} ({pct(s['hit_ci'][0])}–{pct(s['hit_ci'][1])})",
            pct(s["drop_rate"]), f"{pct(s['mean_net'], 2)} ({pct(lo, 2)}–{pct(hi, 2)})", pct(s["median_net"], 2),
            pct(s["win_rate"]), nl(s["payoff_ratio"], 2), pct(max_dd) if max_dd is not None else MISSING]


SUMMARY_HEADER = ["", "Trades", "+10% gehaald (95%-BI)", "≥10% gedaald", "Gem. netto (95%-BI)", "Mediaan netto",
                  "Winstgevend", "Winst/verlies", "Max. drawdown"]


def render(r: EngineResult, live_filings: list[Filing], names: dict[str, str], missing: list[str],
           evaluation: dict | None, code_version: str, timing: dict[str, str] | None = None) -> str:
    c = r.config
    L = [f"# Kortetermijnscan (+{pct(c.target, 0)} binnen 1–2 handelsdagen) — {r.scan_time:%Y-%m-%d %H:%M} UTC", "",
         DISCLAIMER, ""]

    # 1. data
    L += ["## 1. Data en status", ""]
    L += _table(["", ""], [
        ["Koersbron", r.bars_source or "geen"],
        ["Aandelen met koersdata", f"{r.universe_size} (in aanmerking na filters: "
                                   f"{int(r.panel.eligible[r.panel.dates == r.latest_date].sum()) if r.latest_date else 0})"],
        ["Laatste handelsdag in de data", str(r.latest_date) if r.latest_date else MISSING],
        ["Katalysatoren", "SEC 8-K (officieel, op acceptatietijd)" if r.panel.catalysts_used else "niet gebruikt"],
        ["Filters", f"koers ≥ {nl(c.min_price, 2)} USD, gem. dagomzet (20d) ≥ {nl(c.min_dollar_volume / 1e6, 0)} mln USD, "
                    f"≥ {c.min_history} handelsdagen historie, geen datafouten, geen 8-K over delisting/faillissement"],
        ["Code", code_version],
    ])
    problems = [p for ps in r.data_problems.values() for p in ps]
    notes = [f"Datafouten (koers controleren; deze aandelen zijn geen kandidaat): {len(problems)} ({'; '.join(problems[:5])}{' …' if len(problems) > 5 else ''})"] if problems else []
    notes += [f"Ontbrekende bron: {m}" for m in missing] + [f"Opmerking: {n}" for n in r.notes]
    if timing:
        late = sorted(t for t, v in timing.items() if v.startswith("late"))
        dropped = sorted(t for t, v in timing.items() if v.startswith("unreliable"))
        notes.append(f"8-K-tijden gecontroleerd tegen de SEC-filingpagina's voor {len(timing)} aandelen; bij "
                     f"{len(late)} staan sommige tijden 4–5 uur te laat in de SEC-data (zo gelaten: nieuws lijkt hooguit "
                     "later, nooit eerder dan het openbaar was)"
                     + (f"; te vroeg en daarom niet gebruikt: {', '.join(dropped)}" if dropped else ""))
    notes.append("Survivorship bias: het universum bestaat uit nu genoteerde aandelen (SEC-lijst); verdwenen aandelen "
                 "ontbreken, wat historische resultaten te gunstig kan maken.")
    notes.append("Niet beschikbaar in deze omgeving: premarket/after-hours-koersen, optievolume, short interest, "
                 "persberichten buiten SEC. Deze signalen worden dus niet gebruikt.")
    L += [f"- {n}" for n in notes] + [""]

    # 2. reliability
    L += ["## 2. Betrouwbaarheid van de modellen (buiten de trainingsdata)", "",
          "Walk-forward per jaar: trainen op eerdere jaren, model kiezen en kalibreren op het jaar ervoor, één keer "
          "testen op het jaar zelf; tussen de perioden een buffer zodat uitkomsten niet overlappen.", ""]
    if r.oos:
        rows = []
        for h, o in r.oos.items():
            g = o.gate
            rows.append([f"{h} dag(en)", f"{min(o.chosen, default=MISSING)}–{max(o.chosen, default=MISSING)}", g.n,
                         g.events, pct(g.base_rate, 2), nl(g.brier_skill, 4), nl(g.ece, 4),
                         f"{pct(g.top_k_rate, 2)} ({pct(g.top_k_ci[0], 2)}–{pct(g.top_k_ci[1], 2)})",
                         "ja" if g.passed else "nee", "ja" if o.scanner_gate.passed else "nee"])
        L += _table(["Horizon", "Testjaren", "Rijen", "+10%-gevallen", "Basiskans", "Brier-skill", "Kalibratiefout (ECE)",
                     "Top-10 trefkans (95%-BI)", "Kans tonen?", "Scannerregel bruikbaar?"], rows)
        for h, o in r.oos_drop.items():
            L.append(f"- {h}d dalingsmodel (≥10% daling): kans tonen {'ja' if o.gate.passed else 'nee'}"
                     + (f" — {o.gate.reasons[0]}" if o.gate.reasons else ""))
        for h, o in r.oos.items():
            for reason in o.gate.reasons:
                L.append(f"- {h}d model: {reason}")
            for reason in o.scanner_gate.reasons:
                L.append(f"- {h}d scannerregel: {reason}")
        L += ["", f"Scannerregel (vast, niet gefit): `{SCANNER_RULE}`.", ""]
    else:
        L += ["Niet getest: geen koersdata.", ""]

    # 3. backtest
    L += ["## 3. Backtest van de dagelijkse top-10", ""]
    if r.backtests:
        L += [f"Instap op de opening na het signaal; uitstap bij +{pct(c.target, 0)} (limiet, of op de opening bij een "
              "gap erboven), anders op het slot van de horizon"
              + (f"; stop-loss {pct(c.stop_loss, 0)}" if c.stop_loss else "; geen stop-loss")
              + ". Als doel en stop in één dagbalk vallen, telt de stop. Kosten per kant: spread naar liquiditeit "
              f"({', '.join(f'≥{nl(f / 1e6, 0)} mln: {nl(b, 0)} bp' for f, b in c.costs.half_spread_tiers)}) + "
              f"{nl(c.costs.slippage_bps, 0)} bp slippage + {nl(c.costs.commission_bps, 0)} bp commissie (aannames). "
              "Bij zeer beweeglijke aandelen zijn de werkelijke spreads meestal groter, dus de resultaten na kosten "
              "zijn eerder te gunstig dan te somber.", ""]
        rows = []
        for h in r.backtests:
            rows.append(_summary_row(f"Model {h}d", r.backtests[h].summary, r.backtests[h].max_drawdown))
            rows.append(_summary_row(f"Scannerregel {h}d", r.scanner_backtests[h].summary,
                                     r.scanner_backtests[h].max_drawdown))
            if h in r.edge_backtests:
                rows.append(_summary_row(f"Model stijging − daling {h}d", r.edge_backtests[h].summary,
                                         r.edge_backtests[h].max_drawdown))
            if h in r.return_backtests:
                rows.append(_summary_row(f"Verwacht rendement > 0 {h}d", r.return_backtests[h].summary,
                                         r.return_backtests[h].max_drawdown))
            b = r.backtests[h].benchmark
            rows.append([f"Alle aandelen {h}d (vergelijking)", b["rows"], pct(b["hit_rate"]), pct(b["drop_rate"]),
                         pct(b["mean_net_hold"], 2) + " (vasthouden)", MISSING, MISSING, MISSING, MISSING])
        L += _table(SUMMARY_HEADER, rows)
        for h, bt in r.backtests.items():
            s = bt.summary
            if s.get("trades"):
                lo = s["mean_net_ci"][0]
                verdict = ("historisch winstgevend na kosten (ondergrens 95%-BI > 0)" if lo > 0 else
                           "niet aantoonbaar winstgevend na kosten (95%-BI van het gemiddelde omvat 0 of ligt eronder)")
                L.append(f"- Model {h}d: {verdict}.")
                ratio = s["drop_rate"] / s["hit_rate"] if s["hit_rate"] else float("inf")
                L.append(f"- Richtingstoets {h}d: de top-picks haalden +10% in {pct(s['hit_rate'])} en daalden ≥10% in "
                         f"{pct(s['drop_rate'])} van de gevallen; "
                         + ("ze dalen bijna even vaak fors als ze stijgen, dus het model voorspelt vooral beweeglijkheid, "
                            "geen richting." if ratio >= 0.75 else
                            "stijgingen komen duidelijk vaker voor dan dalingen."))
        for h, bt in r.return_backtests.items():
            s = bt.summary
            verdict = ("historisch winstgevend na kosten (ondergrens 95%-BI > 0)" if s.get("trades")
                       and s["mean_net_ci"][0] > 0 else "niet aantoonbaar winstgevend na kosten")
            L.append(f"- Verwacht rendement {h}d (model voorspelt het netto resultaat van de trade, handelt alleen bij "
                     f"een positieve verwachting): {verdict}; testdagen zonder enige trade: "
                     f"{max(r.backtests[h].days - bt.days, 0) + bt.days_without_picks} van {r.backtests[h].days}.")
        L.append("")
        for h, bt in r.backtests.items():
            if bt.by_year:
                L += [f"**Per jaar en marktregime, model {h}d**", ""]
                L += _table(SUMMARY_HEADER[:-1], [_summary_row(str(y), s)[:-1] for y, s in bt.by_year.items()]
                            + [_summary_row(k.replace("rising market (20d)", "stijgende markt (20d)")
                                            .replace("falling market (20d)", "dalende markt (20d)"), s)[:-1]
                               for k, s in bt.by_regime.items()])
    else:
        L += ["Geen backtest mogelijk: geen koersdata.", ""]

    # 4. candidates
    L += ["## 4. Kandidaten", ""]
    if r.candidates:
        L += [f"Gerangschikt op: {r.ranked_by}.", ""]
        rb = r.ranking_backtest.summary if r.ranking_backtest else {}
        if rb.get("trades") and rb["mean_net_ci"][1] < 0:
            L += [f"> **Let op: deze rangschikking verloor in de backtest geld.** Gemiddeld {pct(rb['mean_net'], 2)} per "
                  f"transactie na kosten (95%-BI {pct(rb['mean_net_ci'][0], 2)} tot {pct(rb['mean_net_ci'][1], 2)}); "
                  f"+10% gehaald in {pct(rb['hit_rate'])}, ≥10% gedaald in {pct(rb['drop_rate'])}. Gebruik de lijst "
                  "om beweeglijke aandelen te vinden, niet als koopsignaal.", ""]
        elif rb.get("trades") and rb["mean_net_ci"][0] <= 0:
            L += ["> Deze rangschikking is in de backtest niet aantoonbaar winstgevend na kosten (§3).", ""]
        for k in r.candidates:
            L += [f"### {k.rank}. {k.ticker} — {k.name or 'naam onbekend'}", ""]
            probs = ", ".join(f"{h}d: {pct(p)}" if p is not None else f"{h}d: niet gevalideerd"
                              for h, p in k.probability.items())
            hist = "; ".join(f"{h}d: +10% in {pct(s['hit_rate'])} (95%-BI {pct(s['hit_ci'][0])}–{pct(s['hit_ci'][1])}), "
                             f"≥10% daling in {pct(s['drop_rate'])}" for h, s in k.history.items() if s.get("trades"))
            catalyst = "; ".join(f"{f.accepted_et:%Y-%m-%d %H:%M} ET 8-K {cat.item_text(f.items)} "
                                 f"({cat.leaning(f.items)}) {f.url}" for f in k.catalysts) or "geen 8-K in de laatste 7 dagen"
            s = k.signals
            L += _table(["", ""], [
                ["Laatste koers", f"{nl(k.last_close, 2)} USD (slot {k.last_date}; bron {k.source})"],
                ["Katalysator (SEC)", catalyst],
                ["Technisch", f"1d {pct(s['ret_1d'])}, 5d {pct(s['ret_5d'])}, gap {pct(s['gap'])}, t.o.v. 20d-top "
                              f"{pct(s['breakout_20'])}, t.o.v. 52w-top {pct(s['dist_52w_high'])}, slotpositie "
                              f"{nl(s['close_location'], 2)}"],
                ["Volume", f"RVOL {nl(s['rvol'], 1)}x, 5d/20d {nl(s['volume_trend'], 2)}x"],
                ["Kans op +10%", probs],
                ["Kans op ≥10% daling", ", ".join(f"{h}d: {pct(p)}" if p is not None else f"{h}d: niet gevalideerd"
                                                  for h, p in k.drop_probability.items()) or "niet berekend"],
                ["Historisch (top-10, buiten trainingsdata)", hist or MISSING],
                ["Risico's", "; ".join(k.risks)],
                ["Conclusie", k.conclusion],
            ])
    else:
        L += ["**Geen kandidaten vandaag.**", ""] + [f"- {n}" for n in r.notes if n] + [""]
        if r.raw_scanner:
            L += ["Ruwe scanneruitschieters (**niet gevalideerd — geen kandidaten**, alleen ter controle):", ""]
            L += _table(["Ticker", "Scannerscore", "RVOL", "1d", "Gap", "t.o.v. 20d-top"],
                        [[t, nl(score, 2), nl(s["rvol"], 1) + "x", pct(s["ret_1d"]), pct(s["gap"]), pct(s["breakout_20"])]
                         for t, score, s in r.raw_scanner])

    # 5. catalysts today
    L += ["## 5. Nieuwe 8-K-meldingen (SEC, live)", ""]
    if live_filings:
        rows = [[f"{f.accepted_et:%Y-%m-%d %H:%M}", f.ticker or MISSING, names.get(f.ticker, ""),
                 cat.describe(f.items), cat.item_text(f.items), cat.leaning(f.items), f.url] for f in live_filings[:60]]
        L += ["Het itemnummer zegt welk soort gebeurtenis het is, niet of het nieuws goed of slecht is; daarvoor moet "
              "het persbericht (exhibit 99) gelezen worden. Of het al in de koers zit, is zonder actuele koersen niet "
              "te toetsen.", ""]
        L += _table(["Tijd (ET)", "Ticker", "Naam", "Soort", "Items", "Richting", "Filing"], rows)
        if len(live_filings) > 60:
            L += [f"… en {len(live_filings) - 60} meer.", ""]
    else:
        L += ["Geen nieuwe 8-K's opgehaald.", ""]

    # 6. prediction check
    L += ["## 6. Controle van eerdere voorspellingen", ""]
    if evaluation and any(v["evaluated"] or v["pending"] for v in evaluation.values()):
        L += _table(["Horizon", "Beoordeeld", "+10% gehaald", "≥10% gedaald", "Nog open", "Gem. voorspelde kans", "Brier"],
                    [[f"{h}d", v["evaluated"], pct(v["hit_rate"]) if v["hit_rate"] is not None else MISSING,
                      v["drops"], v["pending"], pct(v.get("mean_probability")) if v.get("mean_probability") is not None
                      else MISSING, nl(v.get("brier"), 4) if v.get("brier") is not None else MISSING]
                     for h, v in evaluation.items()])
    else:
        L += ["Nog geen eerdere voorspellingen om te controleren.", ""]

    # 7. method
    L += ["## 7. Werkwijze en grenzen", "",
          "- Kenmerken per aandeel en dag gebruiken alleen gegevens tot en met dat slot; 8-K's tellen vanaf hun "
          "acceptatietijd (na het slot = nog niet in de koers).",
          "- Uitkomsten worden gemeten vanaf de opening van de volgende handelsdag: een gap vóór de opening is niet te "
          "verdienen.",
          "- Kansen alleen bij: ≥ 30 gevallen buiten de trainingsdata, Brier-skill > 0, kalibratiefout ≤ de helft van "
          "de basiskans en een top-10-trefkans waarvan de 95%-ondergrens boven de basiskans ligt.",
          "- Methode en formules: `docs/SHORT_TERM_ENGINE.md`.", ""]
    return "\n".join(L)


def write(text: str, directory: Path, scan_time: datetime) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"scan_{scan_time:%Y-%m-%d}.md"
    path.write_text(text, encoding="utf-8")
    return path
