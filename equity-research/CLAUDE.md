# CLAUDE.md -- Equity Research System

Vaste instructies voor elke analysesessie in deze map. Deze map is een zelfstandig
Python-project; de C#/StockSharp-regels van de bovenliggende `AGENTS.md` gelden hier niet,
behalve: Engels in code en commits, nooit automatisch pushen zonder opdracht.
Chat met de gebruiker in het **Nederlands**.

**Specialisatie: Amerikaanse aandelen** (NYSE, Nasdaq), US GAAP, SEC-filings (10-K, 10-Q,
8-K), USD. Andere markten alleen op verzoek, en dan met expliciete vermelding van de
beperkingen van de bron.

## 1. Harde regels (nooit overtreden)

1. **Verzin nooit financiële gegevens.** Elk getal in een analyse komt uit een bron
   (zie §3) of uit een berekening op zulke getallen. Ontbreekt een waarde: zeg dat het
   ontbreekt, laat het veld leeg (`None`) en vermeld het in de rapportsectie
   "Datakwaliteit". Nooit schatten "uit het geheugen", nooit een getal uit trainingsdata.
2. **Elk getal heeft herkomst.** Gebruik `SourcedValue` (`src/equity_research/provenance.py`):
   waarde, eenheid, valuta, periode, bron, URL/document-id, ophaaldatum. Rapporten tonen bij
   elk kerngetal de bron.
3. **Aannames zijn geen data.** Groeivoeten, marges, WACC-componenten en terminale groei
   zijn *aannames*: altijd expliciet gelabeld, onderbouwd en in een gevoeligheidsanalyse
   gevarieerd. Aannames staan apart van feiten in het rapport.
4. **Rekenen gebeurt in Python, niet in je hoofd.** Elke berekening loopt via de modules
   in `src/`; nieuwe formules krijgen eerst een test met een met de hand nagerekend of
   uit een standaardwerk overgenomen voorbeeld (TDD).
5. **Controleer jezelf.** Na elke analyse: draai `pytest`, voer de consistentiechecks uit
   (§5) en vermeld afwijkingen. Een check die faalt wordt gemeld, niet weggepoetst.
6. **Geen look-ahead in backtests.** Gebruik alleen data die op de beslisdatum publiek was
   (indieningsdatum van het rapport, niet het einde van de periode). Benoem survivorship
   bias als het universum geen gedeliste aandelen bevat.
7. **Geen beleggingsadvies.** Rapporten zijn analyses met onzekerheidsmarges, geen
   koop/verkoop-opdrachten. Eindig met risico's en wat de these zou ontkrachten.

## 2. Vaste analysemethode (volgorde aanhouden)

1. **Afbakening** -- ticker, beurs, valuta, boekjaar, peildatum.
2. **Data ophalen** -- minimaal 5 (bij voorkeur 10) jaar jaarcijfers + recente kwartalen,
   koersen, aantal aandelen (verwaterd), netto schuld. Cache alles in `data/` met herkomst.
3. **Datakwaliteit** -- ontbrekende jaren, herziene cijfers, eenmalige posten,
   valutawisselingen, aandelensplitsingen. Rapporteer alles.
4. **Fundamentele analyse** -- groei (omzet, EPS, FCF; CAGR), winstgevendheid
   (bruto/operationele/netto marge, ROIC, ROE), kasstroomkwaliteit (FCF/netto winst,
   accruals), balans (netto schuld/EBITDA, rentedekking, current ratio), kapitaalallocatie
   (dividend, inkoop, verwatering).
5. **Kwaliteits- en risicoscores** -- Piotroski F-score, Altman Z-score (juiste variant
   voor de sector), Beneish M-score, volatiliteit, max drawdown, beta.
6. **Waardering** --
   - DCF (FCFF, 2 fasen; WACC via CAPM; terminale waarde met Gordon-groei én exit-multiple
     ter controle; terminale groei ≤ langetermijn nominale BBP-groei/risicovrije rente);
   - reverse DCF: welke groei prijst de markt in?
   - multiples t.o.v. eigen historie en sectorgenoten (EV/EBIT, P/E, P/FCF, EV/Sales);
   - gevoeligheidstabel WACC × terminale groei, plus bear/base/bull-scenario.
7. **Classificatie** -- ondergewaardeerd (koers < intrinsieke waarde met veiligheidsmarge
   ≥ 25% in het base-scenario én kwaliteitsscore niet zwak) en/of groeiaandeel (criteria in
   `docs/METHODOLOGY.md`). Het oordeel volgt uit de cijfers, niet andersom.
8. **Rapport** -- template in `src/equity_research/report/`; opslaan in `reports/<TICKER>_<YYYY-MM-DD>.md`.

## 3. Bronnen (betrouwbaarheid aflopend)

| Bron | Gebruik | Opmerking |
|---|---|---|
| SEC EDGAR XBRL API (`data.sec.gov`) | Jaar/kwartaalcijfers VS | Officieel; `User-Agent` met contact verplicht; max 10 req/s |
| ESEF-filings (`filings.xbrl.org`) / jaarverslagen IR-site | Cijfers EU-bedrijven | Officiële jaarverslagen |
| FRED (St. Louis Fed) | Risicovrije rente, inflatie, BBP | Officieel |
| Damodaran Online (NYU) | Equity risk premium, sector-beta's, marges | Academisch, jaarlijks bijgewerkt |
| Stooq / yfinance | Koershistorie | Onofficieel: markeren als "secundair", controleren op splitsingen |

Geen blogs, fora of AI-samenvattingen als bron voor getallen. Bij tegenstrijdige bronnen:
de officiële filing wint, en het verschil wordt gerapporteerd.

## 4. Werken in deze map

```bash
cd equity-research
python -m pip install -e ".[dev]"
python -m pytest -q                 # alle tests moeten slagen voor een analyse

# live data (SEC eist een User-Agent met contactadres)
export EQUITY_RESEARCH_USER_AGENT="equity-research naam@voorbeeld.nl"
python -m equity_research.data AAPL
```

- SEC-specifiek: gebruik `CompanyFacts.annual(..., as_of=...)` -- per periode de laatst
  ingediende waarde die op `as_of` publiek was (herziene cijfers tellen pas vanaf hun
  indieningsdatum). Comparatieve cijfers in latere 10-K's zijn geen nieuwe data.
- Q4 staat niet los in EDGAR: Q4 = boekjaar − 9 maanden YTD. YTD-regels nooit als kwartaal lezen.
- Banken, verzekeraars en REITs (SIC 6000-6799) krijgen geen Altman Z en een aangepaste
  DCF (dividend/excess-return model); controleer de SIC-code uit `SecEdgar.profile`.
- Testdata in `tests/fakes.py` is synthetisch en mag nooit in een analyse terechtkomen.

- Architectuur: `docs/ARCHITECTURE.md`. Formules en drempels: `docs/METHODOLOGY.md`.
- `data/` (cache) staat in `.gitignore`; rapporten in `reports/` worden wel gecommit.
- Nieuwe databron = nieuwe adapter in `src/equity_research/data/` die `SourcedValue`s teruggeeft.

## 5. Consistentiechecks (na elke analyse)

- Balans sluit: activa = passiva + eigen vermogen (tolerantie 0,5%).
- FCF = operationele kasstroom − capex, en komt overeen met de gerapporteerde componenten.
- Aantal aandelen sprongen > 20% j/j verklaard (split, emissie, overname)?
- DCF: terminale waarde als % van EV vermelden; > 75% = waarschuwing.
- WACC > terminale groei, anders weigert het model te rekenen.
- Eenheden en valuta consistent (duizenden vs. miljoenen, USD vs. EUR).
