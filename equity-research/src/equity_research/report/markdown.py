"""Markdown analysis report (Dutch) following the fixed method of CLAUDE.md section 2.

Facts carry their source, assumptions are listed apart from facts with their rationale, and
everything that is missing or doubtful goes into the data-quality section. The report never
turns the numbers into a buy or sell instruction."""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

from equity_research.data.fred import SERIES_URL
from equity_research.data.sec_edgar import COMPANY_FACTS_URL, SUBMISSIONS_URL, EdgarFact
from equity_research.fundamentals import analysis
from equity_research.fundamentals.checks import CheckResult
from equity_research.fundamentals.concepts import DEBT_COMPONENTS
from equity_research.provenance import DerivedValue, SourcedValue
from equity_research.report.format import MISSING, bn, by_unit, multiple, nl, pct
from equity_research.risk.assess import RiskAssessment
from equity_research.risk.scores import BENEISH_THRESHOLD
from equity_research.valuation import assumptions as default_assumptions
from equity_research.valuation.run import ValuationRun

TABLE_YEARS = 10
METRIC_YEARS = 5
VERDICT = {True: "voldoet", False: "voldoet niet", None: "onbekend"}
MARK = {True: "✔", False: "✘", None: "?"}
SCREEN_NAMES = {"undervalued": "Ondergewaardeerd", "growth": "Groeiaandeel"}


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(cell.replace("|", "/") for cell in row) + " |" for row in rows]
    return out + [""]


def _fy(d: date) -> str:
    return f"FY{d.year}"


def _source(v) -> str:
    if v is None:
        return "ontbreekt"
    if isinstance(v, EdgarFact):
        return f"SEC EDGAR {v.form} {v.accession} (ingediend {v.filed})"
    if isinstance(v, SourcedValue):
        when = f", {v.period_end}" if v.period_end else ""
        return f"{v.source}{when}: {v.reference}"
    if isinstance(v, DerivedValue):
        if v.value is None:
            return f"niet berekend: {v.missing_reason}"
        return v.note or v.formula
    return ""


def _filing_url(cik: str, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"


def _git_revision() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).parent, timeout=5).stdout.strip() or "onbekend"
    except (OSError, subprocess.SubprocessError):
        return "onbekend"


def _metric_rows(r: ValuationRun, years: list[date], names: list[tuple[str, str]]) -> list[list[str]]:
    rows = []
    for name, label in names:
        series = r.metrics.get(name, {})
        rows.append([label] + [by_unit(series[y].value, series[y].unit) if y in series else MISSING for y in years])
    return rows


def _item_rows(r: ValuationRun, years: list[date], names: list[tuple[str, str, str]]) -> list[list[str]]:
    return [[label] + [by_unit(f.value if (f := r.st.get(item, y)) else None, unit) for y in years]
            for item, label, unit in names]


def render(r: ValuationRun, a: RiskAssessment, checks: list[CheckResult], generated: date) -> str:
    p, st = r.profile, r.st
    years = st.fiscal_years[-TABLE_YEARS:]
    recent = st.fiscal_years[-METRIC_YEARS:]
    latest = years[-1] if years else None
    latest_10k = st.get("revenue", latest) if latest else None
    ttm_parts = r.flows["revenue"].inputs
    latest_10q = ttm_parts[1] if len(ttm_parts) == 3 else None
    L: list[str] = []

    # --- title ------------------------------------------------------------------------------
    L += [f"# {p.name} ({r.ticker}) — aandelenanalyse per {r.today}", "",
          "> **Analyse, geen beleggingsadvies.** Elk getal komt uit de genoemde bron of is daaruit berekend; "
          "aannames staan apart (§6.2) en worden in §6.4 gevarieerd. Ontbrekende of twijfelachtige gegevens "
          "staan in §3. Gegenereerd op " f"{generated} met equity-research (code {_git_revision()}).", ""]

    # --- 1. scope ---------------------------------------------------------------------------
    fye = p.fiscal_year_end
    L += ["## 1. Afbakening", ""]
    L += _table(["", ""], [
        ["Ticker / beurs", f"{r.ticker} / {', '.join(p.exchanges) or MISSING}"],
        ["Onderneming", f"{p.name}, CIK {p.cik}, SIC {p.sic} ({p.sic_description})"],
        ["Valuta / boekhouding", "USD / US GAAP"],
        ["Boekjaar eindigt", f"{fye[2:]}-{fye[:2]} (dag-maand)" if len(fye) == 4 else MISSING],
        ["Peildatum", str(r.today)],
        ["Laatste jaarcijfers", f"{_fy(latest)}, 10-K {latest_10k.accession} (ingediend {latest_10k.filed})"
         if latest_10k else MISSING],
        ["Laatste kwartaalcijfers", f"TTM tot {r.flows['revenue'].period_end}, 10-Q {latest_10q.accession} "
                                    f"(ingediend {latest_10q.filed})" if latest_10q else
         "geen 10-Q na de laatste 10-K (TTM = boekjaar)"],
    ])

    # --- 2. data ----------------------------------------------------------------------------
    L += ["## 2. Data", "", "Bedragen in mld USD, aandelen in mld, winst per aandeel in USD.", ""]
    lines = [("revenue", "Omzet", "USD"), ("gross_profit", "Brutowinst", "USD"),
             ("operating_income", "Operationele winst (EBIT)", "USD"), ("net_income", "Nettowinst", "USD"),
             ("operating_cash_flow", "Operationele kasstroom", "USD"), ("capex", "Investeringen (capex)", "USD"),
             ("total_assets", "Totaal activa", "USD"), ("equity", "Eigen vermogen", "USD"),
             ("diluted_shares", "Verwaterde aandelen", "shares"), ("eps_diluted", "Winst per aandeel (verw.)",
                                                                  "USD/shares")]
    rows = _item_rows(r, years, lines)
    rows.insert(6, ["Vrije kasstroom (FCF)"] + [by_unit(r.metrics["fcf"][y].value, "USD") for y in years])
    ttm = {"revenue": r.flows["revenue"], "operating_income": r.flows["operating_income"],
           "net_income": r.flows["net_income"], "operating_cash_flow": r.flows["operating_cash_flow"],
           "capex": r.flows["capex"]}
    ttm_column = [bn(ttm[item].value) if item in ttm else MISSING for item, _, _ in lines]
    ocf, capex = r.flows["operating_cash_flow"].value, r.flows["capex"].value
    ttm_column.insert(6, bn(ocf - capex) if ocf is not None and capex is not None else MISSING)
    for row, cell in zip(rows, ttm_column):
        row.append(cell)
    L += _table([""] + [_fy(y) for y in years] + [f"TTM {r.flows['revenue'].period_end}"], rows)
    accessions = ", ".join(f"{_fy(y)} {f.accession}" for y in years if (f := st.get("revenue", y)))
    L += [f"Bron: SEC EDGAR XBRL companyfacts (CIK {p.cik}), opgehaald {r.facts.retrieved}; per boekjaar de laatst "
          f"ingediende 10-K-waarde{' die op ' + str(st.as_of) + ' openbaar was' if st.as_of else ''}; "
          f"aandelen en winst per aandeel split-gecorrigeerd (§3). TTM = boekjaar + lopend jaar tot nu − "
          f"zelfde periode vorig jaar (10-Q). Omzet per jaar uit: {accessions}.", ""]

    # --- 3. data quality --------------------------------------------------------------------
    L += ["## 3. Datakwaliteit", ""]
    passed = [c for c in checks if c.passed is True]
    failed = [c for c in checks if c.passed is False]
    unknown = [c for c in checks if c.passed is None]
    L += [f"**Consistentiechecks:** {len(passed)} van {len(checks)} geslaagd"
          f"{', ' + str(len(failed)) + ' gefaald' if failed else ''}"
          f"{', ' + str(len(unknown)) + ' niet uitvoerbaar' if unknown else ''} "
          "(balans sluit binnen 0,5%, sprongen in aandelenaantal > 20%, teken capex, één valuta).", ""]
    for c in failed + unknown:
        L.append(f"- {'GEFAALD' if c.passed is False else 'niet uitvoerbaar'}: {c.name} {c.period_end or ''} — {c.detail}")
    first = years[0] if years else None
    findings = [f"aandelensplitsing {s.factor}:1 tussen de filings van {s.last_filed_before} en "
                f"{s.first_filed_after}, afgeleid uit {s.evidence.count('->')} herziene vergelijkende cijfers; "
                "aandelen en winst per aandeel van daarvoor zijn gecorrigeerd" for s in st.splits]
    for issue in st.issues:
        if issue.startswith("stock split"):
            continue
        dates = [date.fromisoformat(d) for d in re.findall(r"(?<!\d)(?:19|20)\d{2}-\d{2}-\d{2}(?!\d)", issue)]
        if not dates or not first or max(dates) >= first:
            findings.append(issue)
    if latest:
        for name, series in r.metrics.items():
            m = series.get(latest)
            if m and (m.missing_reason or m.note):
                findings.append(f"{name} {_fy(latest)}: {m.missing_reason or m.note}")
    tax_recent = [(y, r.metrics["effective_tax_rate"][y].value) for y in recent
                  if y in r.metrics.get("effective_tax_rate", {}) and r.metrics["effective_tax_rate"][y].value is not None]
    if tax_recent and max(v for _, v in tax_recent) - min(v for _, v in tax_recent) > 0.05:
        spread = ", ".join(f"{_fy(y)} {pct(v)}" for y, v in tax_recent)
        findings.append(f"het effectieve belastingtarief schommelt sterk ({spread}); eenmalige posten worden niet "
                        "automatisch herkend — controleer de belastingtoelichting in de 10-K")
    if isinstance(r.cost_of_debt, DerivedValue) and r.cost_of_debt.note and "stale" in r.cost_of_debt.note:
        findings.append(f"kosten vreemd vermogen uit {r.cost_of_debt.note.split(' ')[0]}: rentelasten worden daarna niet "
                        "meer apart gerapporteerd (verouderd)")
    for label, v in (("koers", r.price), ("beta", r.beta), ("ERP", r.erp), ("kosten vreemd vermogen", r.cost_of_debt)):
        if isinstance(v, SourcedValue) and v.source.startswith("manual input"):
            findings.append(f"{label} handmatig ingevoerd: {v.reference}")
        if isinstance(v, SourcedValue) and "secondary" in v.source:
            findings.append(f"{label} uit een secundaire bron ({v.source})")
    for m in r.missing:
        findings.append(f"niet bereikbaar of ontbrekend: {m}")
    if a.market_missing:
        findings.append(f"marktrisico niet berekend (koersdata niet bereikbaar): {a.market_missing}")
    L += ["", "**Bevindingen:**", ""] + [f"- {f}" for f in findings] + [""]

    # --- 4. fundamentals --------------------------------------------------------------------
    L += ["## 4. Fundamentele analyse", "", "Formules: `docs/METHODOLOGY.md`. "
          f"'{MISSING}' = niet berekenbaar (reden in §3).", ""]
    growth = analysis.growth(st, metrics=r.metrics)
    labels = {"revenue": "Omzet", "operating_income": "EBIT", "net_income": "Nettowinst", "eps_diluted": "Winst per aandeel",
              "fcf": "Vrije kasstroom"}
    L += ["### 4.1 Groei (CAGR tot " + (_fy(latest) if latest else MISSING) + ")", ""]
    L += _table(["", "3 jaar", "5 jaar", "10 jaar"],
                [[labels[item]] + [pct(by_n[n].value) if n in by_n else MISSING for n in (3, 5, 10)]
                 for item, by_n in growth.items()])
    header = [""] + [_fy(y) for y in recent]
    sections = [
        ("4.2 Winstgevendheid", [("gross_margin", "Brutomarge"), ("operating_margin", "Operationele marge"),
                                 ("net_margin", "Nettomarge"), ("roe", "ROE"), ("roic", "ROIC"),
                                 ("return_on_capital_incl_cash", "Rendement op kapitaal incl. kas")]),
        ("4.3 Kasstroomkwaliteit", [("fcf", "Vrije kasstroom (mld)"), ("fcf_margin", "FCF-marge"),
                                    ("fcf_conversion", "FCF / nettowinst"), ("accruals_ratio", "Accruals-ratio")]),
        ("4.4 Balans", [("total_debt", "Schuld (mld)"), ("net_debt", "Netto schuld (mld)"),
                        ("net_debt_to_ebitda", "Netto schuld / EBITDA"), ("interest_coverage", "Rentedekking"),
                        ("current_ratio", "Current ratio")]),
        ("4.5 Kapitaalallocatie", [("shareholder_payout", "Dividend + inkoop / FCF"),
                                   ("diluted_shares_change", "Verandering verwaterde aandelen")]),
    ]
    for title, names in sections:
        rows = _metric_rows(r, recent, names)
        if title.startswith("4.5"):
            rows = _item_rows(r, recent, [("dividends_paid", "Dividend betaald (mld)", "USD"),
                                          ("buybacks", "Inkoop eigen aandelen (mld)", "USD")]) + rows
        L += [f"### {title}", ""] + _table(header, rows)
    L += ["Netto schuld = schuld − kas − kortlopende effecten; de langlopende effecten tellen in de waardering als "
          "niet-operationele activa (§6). ROIC is niet gedefinieerd als het geïnvesteerd vermogen ≤ 0 is en wordt "
          "extreem als het bijna nul is (veel effecten, negatief werkkapitaal); dan is het rendement op kapitaal "
          "incl. kas de bruikbare maatstaf.", ""]

    # --- 5. scores --------------------------------------------------------------------------
    L += ["## 5. Kwaliteits- en risicoscores", ""]
    if a.years:
        L += _table(["", *[_fy(y) for y in a.years], "Norm"], [
            ["Piotroski F-score"] + [f"{a.piotroski[y].value} van {a.piotroski[y].testable}" for y in a.years]
            + ["≥ 7 sterk, ≤ 3 zwak"],
            ["Altman"] + [(f"{line.result.variant} {nl(line.result.value, 2)} ({line.result.zone})"
                           if line.result and line.result.value is not None else MISSING) for line in a.altman.values()]
            + ["Z: > 2,99 veilig, < 1,81 nood; Z'': > 2,60 / < 1,10"],
            ["Beneish M-score"] + [nl(m.value, 2) if m.value is not None else MISSING for m in a.beneish.values()]
            + [f"> {nl(BENEISH_THRESHOLD, 2)} = signaal"],
        ])
        L += [f"Piotroski-signalen {_fy(a.years[-1])}:", ""]
        L += [f"- {MARK[s.passed]} {s.detail}" for s in a.piotroski[a.years[-1]].signals.values()] + [""]
        notes = {line.note for line in a.altman.values() if line.note}
        L += [f"- Altman: {n}" for n in notes]
        z_latest = a.altman[a.years[-1]].result
        if z_latest and z_latest.components.get("x2_retained_earnings", 0) < 0:
            L.append("- Altman: de ingehouden winst is negatief (bijv. door inkoop van eigen aandelen); dat drukt X2 "
                     "zonder dat het financiële nood aangeeft.")
        L.append("")
    if a.market:
        L += _table(["Marktrisico (Yahoo/Stooq, secundair)", "Waarde"], [
            [f"Volatiliteit ({a.market['months']} maandrendementen, op jaarbasis)", pct(a.market["volatility"])],
            ["Grootste daling (5 jaar)", pct(a.market["max_drawdown"])],
            ["Beta t.o.v. S&P 500", nl(a.market["beta"], 2)]])
    else:
        L += ["Marktrisico (volatiliteit, grootste daling, beta): niet berekend — koersdata niet bereikbaar (§3).", ""]

    # --- 6. valuation -----------------------------------------------------------------------
    L += ["## 6. Waardering", "", "### 6.1 Feiten (met bron)", ""]
    facts_rows = [[f"{label} (TTM)", bn(v.value), _source(v.inputs[1] if len(v.inputs) == 3 else
                                                         (v.inputs[0] if v.inputs else v))]
                  for label, v in (("Omzet", r.flows["revenue"]), ("EBIT", r.flows["operating_income"]))]
    for item, label in (("cash", "Kas"), ("short_term_investments", "Kortlopende effecten"),
                        ("long_term_investments", "Langlopende effecten"), *[(c, c.replace("_", " ")) for c in
                                                                              DEBT_COMPONENTS],
                        ("minority_interest", "Minderheidsbelang")):
        v = r.balance.get(item)
        facts_rows.append([f"{label} ({r.balance.period_end})", bn(v.value), _source(v)])
    if r.diluted:
        facts_rows.append(["Verwaterde aandelen (mld)", nl(r.diluted.value / 1e9, 3), _source(r.diluted)])
    if r.outstanding:
        facts_rows.append(["Uitstaande aandelen (mld)", nl(r.outstanding.value / 1e9, 3), _source(r.outstanding)])
    for label, v, shown in (("Risicovrije rente", r.rf, pct(r.rf.value, 2) if r.rf else MISSING),
                            ("Verwachte inflatie (10 jaar)", r.inflation, pct(r.inflation.value, 2) if r.inflation else MISSING),
                            ("Aandelenrisicopremie", r.erp, pct(r.erp.value, 2) if r.erp else MISSING),
                            ("Beta", r.beta, nl(r.beta.value, 2) if r.beta else MISSING),
                            ("Koers (USD)", r.price, nl(r.price.value, 2) if r.price else MISSING),
                            ("Kosten vreemd vermogen (voor belasting)", r.cost_of_debt,
                             pct(r.cost_of_debt.value, 2) if r.cost_of_debt and r.cost_of_debt.value is not None
                             else MISSING)):
        facts_rows.append([label, shown, _source(v)])
    L += _table(["Gegeven", "Waarde", "Bron"], facts_rows)

    L += ["### 6.2 Aannames (geen data)", ""]
    if r.scenarios:
        names = [n for n in default_assumptions.REQUIRED]
        rows = []
        for n in names:
            cells = [pct(r.scenarios[s][n].value, 2) if n in r.scenarios[s] else MISSING for s in ("bear", "base", "bull")]
            base = r.scenarios["base"].get(n)
            rows.append([n] + cells + [base.rationale if base else r.scenarios.missing.get(n, MISSING)])
        L += _table(["Aanname", "Bear", "Base", "Bull", "Onderbouwing (base)"], rows)
        L += [f"Fase 1: {default_assumptions.HIGH_GROWTH_YEARS} jaar omzetgroei volgens de aanname, daarna "
              f"{default_assumptions.FADE_YEARS} jaar lineair naar de terminale groei. Bear: RONIC = WACC "
              "(nieuw kapitaal verdient alleen zijn kosten). Belastingtarief voor de WACC = base-aanname.", ""]
        for n, why in r.scenarios.missing.items():
            L.append(f"- Ontbrekende aanname {n}: {why}")
        L.append("")
    else:
        L += ["Geen aannames: risicovrije rente of inflatieverwachting ontbreekt.", ""]

    L += ["### 6.3 Kapitaalkosten (WACC)", ""]
    L += [f"WACC = {pct(r.wacc, 2)}: {r.wacc_text}." if r.wacc is not None else
          f"WACC niet bepaald — {r.wacc_text.replace('not determined, missing:', 'ontbreekt:')}.", ""]

    L += ["### 6.4 Uitkomsten", ""]
    if r.results:
        rows = [[s, bn(x.enterprise_value), bn(x.equity_value), nl(x.value_per_share, 2), pct(x.terminal_share_of_ev, 0),
                 multiple(x.implied_exit_ev_ebit)] for s, x in r.results.items()]
        rows += [[s, "geweigerd", why, "", "", ""] for s, why in r.refused.items()]
        L += _table(["Scenario", "EV (mld)", "Eigen vermogen (mld)", "Per aandeel (USD)", "Restwaarde % EV",
                     "Impliciete exit EV/EBIT"], rows)
    if r.grid:
        waccs, gs = sorted({w for w, _ in r.grid}), sorted({g for _, g in r.grid})
        title = ("Gevoeligheid base-waarde per aandeel (USD): WACC (rijen) × terminale groei (kolommen)" if r.wacc
                 else "Waarde per aandeel (USD) bij een reeks WACC's — de WACC zelf is niet bepaald (§6.3)")
        L += [f"**{title}**", ""]
        L += _table(["WACC \\ g"] + [pct(g, 2) for g in gs],
                    [[pct(w, 2)] + [nl(r.grid[(w, g)], 2) if r.grid[(w, g)] is not None else "weigert" for g in gs]
                     for w in waccs])
    if r.price and r.base_value is not None:
        L += [f"Koers {nl(r.price.value, 2)} USD tegenover base-waarde {nl(r.base_value, 2)} USD "
              f"({pct(r.base_value / r.price.value - 1)} t.o.v. de koers).", ""]
        if r.implied_growth is not None:
            L += [f"Reverse DCF: de koers impliceert {pct(r.implied_growth, 2)} omzetgroei per jaar in fase 1 "
                  f"(base-aanname {pct(r.scenarios['base']['revenue_growth'].value, 2)}).", ""]
        elif r.implied_growth_error:
            L += [f"Reverse DCF: {r.implied_growth_error}.", ""]
        if r.multiples:
            m = r.multiples
            L += _table(["Multiple (TTM)", "Waarde"], [
                ["Beurswaarde (mld)", bn(m["market_cap"])], ["Ondernemingswaarde (mld)", bn(m["enterprise_value"])],
                ["EV / omzet", multiple(m["ev_sales"])], ["EV / EBIT", multiple(m["ev_ebit"])],
                ["Koers / winst", multiple(m["pe"])], ["Koers / FCF", multiple(m["p_fcf"])],
                ["FCF-rendement", pct(m["fcf_yield"])]])
    elif not r.results:
        L += ["Geen vergelijking met de koers mogelijk: koers en/of WACC ontbreken (§3).", ""]
    if r.warnings:
        L += [f"- Waarschuwing: {w}" for w in r.warnings] + [""]

    # --- 7. classification ------------------------------------------------------------------
    L += ["## 7. Classificatie", "", "Drempels uit `docs/METHODOLOGY.md`; het zijn hypotheses tot ze in een backtest "
          "zijn getoetst. Het oordeel volgt uit de criteria, niet andersom.", ""]
    for screen in a.screens:
        name = SCREEN_NAMES.get(screen.name, screen.name)
        unknown = [c.name for c in screen.criteria.values() if c.passed is None]
        verdict = {True: f"**{name}: ja** — alle criteria voldoen.",
                   False: f"**{name}: nee** — minstens één criterium voldoet niet.",
                   None: f"**{name}: Niet te bepalen** — onbekend: {', '.join(unknown)}."}[screen.passed]
        L += [verdict, ""]
        L += _table(["Criterium", "Uitkomst", "Toelichting"],
                    [[c.name, VERDICT[c.passed], c.detail.replace("ROIC", a.roic_label, 1)
                      if c.name == "roic_above_wacc" else c.detail] for c in screen.criteria.values()])

    # --- 8. risks ---------------------------------------------------------------------------
    L += ["## 8. Risico's en wat de these zou ontkrachten", ""]
    risks = []
    rev = growth.get("revenue", {})
    if 3 in rev and 5 in rev and rev[3].value is not None and rev[5].value is not None and rev[3].value < rev[5].value:
        risks.append(f"Groeivertraging: omzetgroei over 3 jaar {pct(rev[3].value)} tegen {pct(rev[5].value)} over "
                     "5 jaar. Het base-scenario rekent met de mediaan van 3, 5 en 10 jaar.")
    if r.grid:
        values = [v for v in r.grid.values() if v is not None]
        if values:
            risks.append(f"Gevoeligheid: de waarde per aandeel loopt in de tabel van §6.4 van {nl(min(values), 2)} tot "
                         f"{nl(max(values), 2)} USD; kleine wijzigingen in WACC en terminale groei verschuiven het "
                         "oordeel sterk.")
    if "bear" in r.results and "base" in r.results:
        risks.append(f"Bear-scenario: {nl(r.results['bear'].value_per_share, 2)} USD per aandeel tegen "
                     f"{nl(r.results['base'].value_per_share, 2)} USD in het base-scenario.")
    if r.scenarios and "nwc_pct_revenue" in r.scenarios["base"] and r.scenarios["base"]["nwc_pct_revenue"].value < 0:
        risks.append(f"Werkkapitaal is negatief ({pct(r.scenarios['base']['nwc_pct_revenue'].value)} van de omzet): "
                     "groei levert in het model kas op. Als leveranciers korter krediet geven, valt dat voordeel weg.")
    for line in a.altman.values():
        if line.result and line.result.zone == "distress" and line.fits_company:
            risks.append(f"Altman {line.result.variant} in de noodzone ({nl(line.result.value, 2)}).")
    for y, m in a.beneish.items():
        if m.flagged:
            risks.append(f"Beneish M-score {_fy(y)} {nl(m.value, 2)} boven {nl(BENEISH_THRESHOLD, 2)}: "
                         "mogelijk winstmanipulatie — toelichtingen nalezen.")
    if r.missing:
        risks.append("Onvolledige gegevens (§3): conclusies die van de ontbrekende bronnen afhangen zijn open.")
    L += [f"- {x}" for x in risks] + [""]
    L += ["**Wat het base-scenario zou ontkrachten:**", ""]
    if r.scenarios and r.scenarios.complete("base"):
        b = r.scenarios["base"]
        bear = r.scenarios["bear"]
        L += [f"- Omzetgroei die in fase 1 structureel onder {pct(bear['revenue_growth'].value)} blijft "
              f"(base {pct(b['revenue_growth'].value)}).",
              f"- Een operationele marge onder {pct(bear['ebit_margin'].value)} (base {pct(b['ebit_margin'].value)}).",
              f"- Hogere kapitaalkosten: elk procentpunt WACC verschuift de waarde zoals in de tabel van §6.4."]
    if latest_10k:
        L += [f"- Kwalitatieve risico's (10-K, Item 1A 'Risk Factors') zijn niet automatisch beoordeeld: "
              f"{_filing_url(p.cik, latest_10k.accession)}"]
    L.append("")

    # --- 9. sources -------------------------------------------------------------------------
    L += ["## 9. Bronnen", ""]
    sources = [f"SEC EDGAR companyfacts: {COMPANY_FACTS_URL.format(cik=p.cik)} (opgehaald {r.facts.retrieved})",
               f"SEC EDGAR submissions: {SUBMISSIONS_URL.format(cik=p.cik)}"]
    if latest_10k:
        sources.append(f"Jaarverslag {_fy(latest)} (10-K): {_filing_url(p.cik, latest_10k.accession)}")
    if latest_10q:
        sources.append(f"Kwartaalverslag tot {latest_10q.period_end} (10-Q): {_filing_url(p.cik, latest_10q.accession)}")
    for label, series in (("FRED 10-jaars Treasury", "DGS10"), ("FRED inflatieverwachting 10 jaar", "T10YIE")):
        sources.append(f"{label}: {SERIES_URL.format(series=series)}")
    for label, v in (("Aandelenrisicopremie", r.erp), ("Beta", r.beta), ("Koers", r.price)):
        if isinstance(v, (SourcedValue, DerivedValue)) and v.value is not None:
            sources.append(f"{label}: {_source(v)}")
        else:
            sources.append(f"{label}: niet bereikbaar of niet gebruikt (§3)")
    sources.append("Methode en formules: docs/METHODOLOGY.md; architectuur: docs/ARCHITECTURE.md")
    L += [f"- {s}" for s in sources] + [""]
    return "\n".join(L)


def write_report(text: str, ticker: str, day: date, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{ticker.upper()}_{day.isoformat()}.md"
    path.write_text(text, encoding="utf-8")
    return path
