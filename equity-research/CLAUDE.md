# CLAUDE.md -- Equity Research System

Vaste instructies voor elke analysesessie in deze map. Deze map is een zelfstandig
Python-project; de C#/StockSharp-regels van de bovenliggende `AGENTS.md` gelden hier niet,
behalve: Engels in code en commits, nooit automatisch pushen zonder opdracht.
Chat met de gebruiker in het **Nederlands**.

**Specialisatie: Amerikaanse aandelen** (NYSE, Nasdaq), US GAAP, SEC-filings (10-K, 10-Q,
8-K), USD. Andere markten alleen op verzoek, en dan met expliciete vermelding van de
beperkingen van de bron.

## 0. Begin van elke sessie

De SessionStart-hook installeert het pakket en meldt per bron of die bereikbaar is
(`BLOCKED` = netwerkbeleid). Neem die melding over in je eerste antwoord als een bron die je nodig
hebt geblokkeerd is, en vul ontbrekende data nooit zelf in. Draai `python -m pytest -q` vóór een
analyse. Werk op de toegewezen branch, commit met een duidelijke boodschap en push alleen als
de gebruiker of de sessie-instructies daarom vragen.

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
8. **Rapport** -- template in `src/equity_research/report/`; opslaan in `reports/<TICKER>_<YYYY-MM-DD>.md`
   met `equity-research analyze <TICKER> --context reports/context/<TICKER>_<datum>.md` na het
   webonderzoek (zie §3). Daarna samenvatten in de chat: kerncijfers, oordeel, ontbrekende
   bronnen, gefaalde checks, link naar het rapport.

## 3. Bronnen (betrouwbaarheid aflopend)

| Bron | Gebruik | Opmerking |
|---|---|---|
| SEC EDGAR XBRL API (`data.sec.gov`) | Jaar/kwartaalcijfers VS | Officieel; `User-Agent` met contact verplicht; max 10 req/s |
| ESEF-filings (`filings.xbrl.org`) / jaarverslagen IR-site | Cijfers EU-bedrijven | Officiële jaarverslagen |
| FRED (St. Louis Fed) | Risicovrije rente, inflatie, BBP | Officieel |
| Damodaran Online (NYU) | Equity risk premium, sector-beta's, marges | Academisch, jaarlijks bijgewerkt |
| Yahoo Finance via yfinance | Dagkoersen alle NYSE/Nasdaq-aandelen (standaard) | Onofficieel: "secundair"; split- en dividendgecorrigeerd; cache in `data/cache/yahoo` |
| Stooq | Koershistorie (reserve) | Sinds 2026-10 een JavaScript-botcontrole i.p.v. CSV: in de praktijk onbruikbaar |

Geen blogs, fora of AI-samenvattingen als bron voor getallen. Bij tegenstrijdige bronnen:
de officiële filing wint, en het verschil wordt gerapporteerd.

**Breed webonderzoek voor context (bij elke analyse).** Zoek met WebSearch/WebFetch op zoveel
mogelijk betrouwbare sites (IR-site van het bedrijf, SEC-filings, persberichten, Reuters, AP,
Bloomberg, CNBC, WSJ, FT, vakmedia, toezichthouders zoals FDA/FTC/EU) naar: recent nieuws,
guidance en cijferdata, productnieuws, juridische en regelgevende zaken, managementwissels,
overnames, en het oordeel van analisten. Regels:
- Elk punt met **bron-URL en datum** in een contextbestand `reports/context/<TICKER>_<datum>.md`
  (één regel per punt, `- YYYY-MM-DD: ... (https://...)`, de datum van de gebeurtenis of publicatie;
  onbekend → de ophaaldatum met "(opgehaald; publicatiedatum onbekend)"); het rapport neemt dat op met
  `--context` en weigert regels zonder URL of datum.
- **Controleer** zwaarwegende claims (CEO-wissel, overname, guidance, cijferdatum) tegen een
  officiële bron (8-K/filingpagina, IR-site) en vermeld of dat gelukt is.
- Getallen van websites (koersdoelen, consensus) zijn **secundair**: alleen als context, nooit
  als invoer voor berekeningen. Zoekresultaten zonder datum of van onbekende sites niet gebruiken.
- Meld tegenstrijdige berichten en wat niet te verifiëren was.

## 4. Werken in deze map

```bash
cd equity-research
python -m pip install -e ".[dev]"
python -m pytest -q                 # alle tests moeten slagen voor een analyse

# live data (SEC eist een User-Agent met contactadres)
export EQUITY_RESEARCH_USER_AGENT="equity-research naam@voorbeeld.nl"
python -m equity_research.data AAPL           # ruwe SEC-reeksen
python -m equity_research.fundamentals AAPL   # jaarcijfers, ratio's, groei, checks, datakwaliteit
python -m equity_research.fundamentals AAPL --as-of 2020-01-01   # point-in-time
python -m equity_research.valuation AAPL      # DCF, scenario's, gevoeligheid, reverse DCF
python -m equity_research.valuation AAPL --industry "<Damodaran-industrie>"   # bottom-up beta
python -m equity_research.risk AAPL           # Piotroski, Altman, Beneish, marktrisico, screens
equity-research analyze AAPL                  # volledig rapport -> reports/AAPL_<datum>.md
equity-research backtest --tickers AAPL,MSFT     # screens point-in-time terugspelen (fase 5; zonder --tickers: hele markt)
```

- Na elk rapport: `pytest` draaien en §3 "Datakwaliteit" van het rapport nalezen; gefaalde checks
  en ontbrekende bronnen in de samenvatting aan de gebruiker noemen.

- Koers (Yahoo/Stooq), ERP en sectorbeta (Damodaran) mogen bij een geblokkeerde bron alleen met bron
  worden ingevoerd: `--price 231.50 --price-source "Nasdaq official close 2026-10-08"` (idem
  `--beta`, `--erp`, `--cost-of-debt`). Nooit een waarde uit het geheugen invullen.
- Yahoo is in de cloudomgeving pas bereikbaar als `query1.finance.yahoo.com`, `query2.finance.yahoo.com`,
  `fc.yahoo.com` en `guce.yahoo.com` zijn toegestaan; op GitHub Actions werkt het zonder meer. Damodaran is live
  gecontroleerd (2026-10-09); de ERP komt uit `histimpl.html` (`implpr.html` stopt bij 2016).

- SEC-specifiek: gebruik `CompanyFacts.annual(..., as_of=...)` -- per periode de laatst
  ingediende waarde die op `as_of` publiek was (herziene cijfers tellen pas vanaf hun
  indieningsdatum). Comparatieve cijfers in latere 10-K's zijn geen nieuwe data.
- Aandelenaantallen en per-aandeelcijfers zijn niet split-gecorrigeerd: de laatste filing per
  periode kan van vóór een split zijn (AAPL: 7:1 in 2014, 4:1 in 2020 geven gemengde reeksen).
  `fundamentals.build_annual` herkent splits uit de filings zelf en corrigeert; vermeld ze in
  "Datakwaliteit". `fy`/`fp` van EDGAR horen bij de filing, niet bij de periode
  (`filing_fiscal_year`); selecteer periodes op `period_end`.
- Q4 staat niet los in EDGAR: Q4 = boekjaar − 9 maanden YTD. YTD-regels nooit als kwartaal lezen.
- Banken, verzekeraars en REITs (SIC 6000-6799) krijgen geen Altman Z en een aangepaste
  DCF (dividend/excess-return model); controleer de SIC-code uit `SecEdgar.profile`.
- Testdata in `tests/fakes.py` is synthetisch en mag nooit in een analyse terechtkomen.

- Architectuur: `docs/ARCHITECTURE.md`. Formules en drempels: `docs/METHODOLOGY.md`.
- `data/` (cache) staat in `.gitignore`; rapporten in `reports/` worden wel gecommit.
- Nieuwe databron = nieuwe adapter in `src/equity_research/data/` die `SourcedValue`s teruggeeft.

## 5a. Kortetermijnmodule (aanvulling, geen vervanging)

De "stock explosion"-module (`src/equity_research/shortterm/`, methode in
`docs/SHORT_TERM_ENGINE.md`) zoekt dagelijks naar aandelen met een statistisch onderbouwde kans op
+10% binnen 1–2 handelsdagen. Alles hierboven blijft gelden; aanvullend:

- **Kansen alleen na de out-of-sample-poort** (`evaluation.probability_gate`): ≥ 30 gevallen,
  Brier-skill > 0, goede kalibratie en een top-10-trefkans significant boven de basiskans. Anders
  rangschikken zonder kans, en zonder geldige rangschikking: **geen kandidaten**. Noem dat expliciet.
- **Nooit** winst garanderen, nooit "koop" zeggen, nooit orders plaatsen of aan een broker koppelen
  zonder aparte toestemming van de gebruiker.
- Point-in-time: kenmerken t/m het slot van dag t, 8-K's op acceptatietijd (UTC → New York),
  instap op de opening van t+1. Nieuwe kenmerken krijgen een test dat ze niet in de toekomst kijken.
- "Historisch winstgevend" alleen als de ondergrens van het 95%-BI van het gemiddelde netto
  rendement (na kosten) boven 0 ligt. Verloor de gebruikte rangschikking geld in de backtest, dan
  staat er een waarschuwing boven de kandidaten; noem die ook in de chat. Toon bij elke kans op +10%
  ook de kans op ≥10% daling (richtingstoets).
- Modelverbetering via hetzelfde walk-forward-protocol; het laatste testjaar niet gebruiken om te
  tunen. Vergelijk daarna met de voorspellingslog (`predictions/`, `shortterm evaluate`).
- Nieuws: alleen officiële bronnen (SEC 8-K) of door de gebruiker gelicentieerde bronnen; het
  itemnummer zegt het soort gebeurtenis, niet de richting. Verzin nooit nieuws.

```bash
equity-research shortterm catalysts --hours 24     # nieuwe 8-K's (SEC, live)
equity-research shortterm scan                     # hele markt via Yahoo; of --bars-dir <map met TICKER.csv>
equity-research shortterm evaluate --no-sec        # eerdere voorspellingen controleren
```

## 5. Consistentiechecks (na elke analyse)

- Balans sluit: activa = passiva + eigen vermogen (tolerantie 0,5%).
- FCF = operationele kasstroom − capex, en komt overeen met de gerapporteerde componenten.
- Aantal aandelen sprongen > 20% j/j verklaard (split, emissie, overname)?
- DCF: terminale waarde als % van EV vermelden; > 75% = waarschuwing.
- WACC > terminale groei, anders weigert het model te rekenen.
- Eenheden en valuta consistent (duizenden vs. miljoenen, USD vs. EUR).
