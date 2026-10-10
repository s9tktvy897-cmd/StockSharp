# Eindrapport: herbouw en validatie van het handelssysteem — 2026-10-10

> Alle getallen komen uit de code en data in deze repository (commits op branch `ccr-a35d8d99-6b3wfh`).
> Historische simulaties zijn geen garantie; dit is geen beleggingsadvies. Er is niet echt gehandeld.

## 1. Executive summary

**Eindoordeel: NO PROVEN EDGE.** Van 34 vooraf vastgelegde strategievarianten (regels en modellen, horizons
1–20 dagen) haalt **geen enkele** de criteria; alle 34 zijn REJECTED. Ook 468 verkennende combinaties van
situatie × handelsregel rond de opening (dagdata, §5b) leveren geen significant positief resultaat op.
Het onderzoek op uurkoersen loopt nog en wordt apart toegevoegd.

Wat niet werkte: het oorspronkelijke +10%-model voorspelde beweeglijkheid, geen richting (top-10: +10% in
56,5%, −10% in 58,1%; −1,44% per trade), en de backtest had fouten die de uitkomst vertekenden.

Wat is aangepast en echt verbeterd:
- de backtest is nu realistisch (instap op de opening, spread/slippage/impact, deelvullingen, handelsstops,
  risicolaag, portefeuilleboekhouding) en reproduceerbaar;
- twee look-ahead-fouten (prijsfilter en marktwaarde op split-gecorrigeerde koersen) zijn hersteld;
- statistiek houdt rekening met afhankelijkheid (blokbootstrap, clustering per dag) en met meervoudig testen
  (Holm, deflated Sharpe), en de beoordeling is vooraf vastgelegd met een onaangeroerde holdout;
- voorspellingen worden nu blijvend en onveranderlijk vastgelegd (hash-keten), wat eerder niet gebeurde;
- de fundamentele motor rekent breder (MSFT, UFPT) en weigert met een reden in plaats van te crashen.

Wat níet is verbeterd: er is geen winstgevende strategie gevonden. Dat is een geldige onderzoeksuitkomst.

## 2. Root-cause-analyse: waarom verloor het systeem geld?

1. **Kosten > voorspelkracht.** Bij 1–2 dagen kost een round trip 0,35–0,70% (spread, slippage, impact).
   Vóór kosten verdienen de dagstrategieën ongeveer 0 (reversal 1d: −0,37% netto bij 0,36% kosten; oude
   +10%-model 1d: −0,79% bij 0,70%). Willekeurige daghandel verliest door kosten −48,7% per jaar.
2. **Volatiliteit ≠ richting.** Het oude model vond beweeglijke aandelen; die dalen even vaak 10% als ze
   stijgen. Na de opening sluit in elke onderzochte situatie 44–51% boven de opening.
3. **Gap-ups keren om.** Aandelen die >20% hoger openen, sluiten gemiddeld −2,15% onder de opening.
4. **Vertekeningen in de oude backtest** (nu hersteld): prijsfilter op split-gecorrigeerde koersen
   (look-ahead), keuze van de rangschikking op dezelfde testperiode als de rapportage (selectiebias),
   betrouwbaarheidsintervallen alsof trades onafhankelijk zijn, geen portefeuille- of risicobeheer
   (drawdowns −97% tot −99%), slechts 2 testjaren, en een voorspellingslog die op GitHub nooit bewaard werd.
5. **Markt:** 2017–2026 was een sterke stijgende markt (SPY Sharpe 0,79); actieve strategieën met kosten
   moeten dat eerst evenaren. Geen enkele variant kwam in de buurt.

## 3. Codewijzigingen (bestanden en functies)

| Onderdeel | Bestanden | Wat |
|---|---|---|
| Koersdata | `data/yahoo.py`, `shortterm/bars.py`, `shortterm/dataset.py` | `raw_close` (werkelijk verhandelde koers uit de splithistorie), totaalrendementskoersen, cacheformaat 2; prijsfilter op de verhandelde koers |
| Kenmerken | `shortterm/features.py`, `shortterm/catalysts.py`, `shortterm/sources.py` | 12-1-momentum, MA-afstanden, volatiliteit; earnings-reactievlag; volledige SEC-indieningshistorie en SIC (`ShortTermSources.company`); look-ahead-tests |
| Onderzoek | `research/protocol.py`, `stats.py`, `execution.py`, `risk.py`, `portfolio.py`, `strategies.py`, `experiment.py`, `report.py`, `dashboard.py`, `signals.py`, `__main__.py` | vooraf vastgelegd protocol; statistiek; kostenmodel; risicolaag; dagelijkse portefeuillesimulatie; 34 varianten; runner, rapport, dashboard; paper-signalen alleen voor kandidaten |
| Register | `ledger.py`, `ledger/ledger.jsonl`, `shortterm/__main__.py`, `.github/workflows/equity-research.yml` | onveranderlijk hash-ketenregister met statussen; dagelijkse opslag op branch `paper-ledger` met uitbreidingscontrole |
| Kortetermijnengine | `shortterm/expected.py`, `labels.py`, `engine.py`, `report.py`, `config.py` | model voor netto rendement (PR #8), registercodes |
| Fundamenteel | `backtest/fundamental.py`, `backtest/__main__.py`, `fundamentals/ttm.py`, `analysis.py`, `concepts.py`, `valuation/run.py`, `multiples.py` | marktwaarde op verhandelde koers; waarderingsfactoren en IC-toets; geschrapte regels als gelabelde 0; reserveconcepten; weigeren i.p.v. crashen |
| Documentatie | `docs/RESEARCH_PROTOCOL.md`, `docs/ARCHITECTURE.md`, `docs/SHORT_TERM_ENGINE.md`, `CLAUDE.md`, `.claude/skills/brede-bronnen` | protocol met amendement 1; werkwijze voor nieuwe sessies |

## 4. Datakwaliteit

| Bron | Status | Beperking |
|---|---|---|
| SEC EDGAR (8-K, SIC, companyfacts) | officieel; 7.552 van 7.555 bedrijven compleet | sommige tijdstempels 4–5 uur te laat (nooit vervroegd); 13 companyfacts-404's in de factortoets |
| Yahoo dagkoersen (10 jaar) | secundair; 7.553 van 7.555 tickers | **survivorship bias**: alleen huidige noteringen; 1.060 aandelen uitgesloten (777 wegens een "split-achtige" sprong — vaak een echte sprong; in de openingsstudies wél meegeteld) |
| Yahoo uurkoersen | secundair; 7.470 tickers, okt 2024 – okt 2026 | slechts 2 jaar; binnen een uur onbekend of hoog of laag eerst kwam (aangenomen: verlies eerst) |
| FRED, Damodaran | officieel / academisch | – |

Niet beschikbaar zonder betaalde bron: gedeliste aandelen met koersen (survivorship), bied/laat-koersen,
minuutdata over jaren, analistenconsensus (verrassing t.o.v. verwachting), opties, short interest, nieuwsfeeds
met tijdstempel. Er is niets betaald of aangevraagd.

## 5. Modelvergelijking (ontwikkelperiode okt 2017 – aug 2025, na kosten, met risicolaag)

| Variant | Trades | Netto per trade (95%-BI, geclusterd per dag) | Sharpe | Max. DD | Kosten heen+terug | p | Holdout netto/trade (trades) |
|---|---|---|---|---|---|---|---|
| MOMENTUM_12_1 20d | 4210 | 0,53% (−0,90% – 1,95%) | 0,18 | −25,0% | 0,56% | 0,29 | 0,30% (516) |
| EARNINGS_DRIFT 20d | 4723 | 0,40% (−0,87% – 1,56%) | 0,17 | −16,2% | 0,50% | 0,31 | 1,08% (780) |
| TREND_60D 20d | 4723 | 0,27% (−1,21% – 1,79%) | 0,09 | −25,3% | 0,60% | 0,39 | 0,22% (698) |
| MODEL_A_DIRECTION 20d | 7037 | 0,15% (−1,19% – 1,41%) | 0,06 | −29,6% | 0,44% | 0,44 | −1,02% (977) |
| MODEL_C_RISK_ADJUSTED 20d | 9039 | −0,01% (−1,22% – 1,10%) | 0,00 | −37,0% | 0,45% | 0,50 | −0,03% (1840) |
| REVERSAL_5D 5d | 17280 | −0,13% (−0,51% – 0,22%) | −0,20 | −68,6% | 0,36% | 0,71 | −0,04% (2055) |
| MODEL_A_DIRECTION 1d | 684 | −0,23% (−0,99% – 0,52%) | −0,29 | −26,3% | 0,44% | 0,72 | −0,59% (269) |
| MODEL_C_RISK_ADJUSTED 1d | 555 | −0,32% (−0,66% – 0,04%) | −0,34 | −13,6% | 0,35% | 0,87 | 0,22% (65) |
| MODEL_B_EXPECTED_RETURN 1d | 1974 | −0,32% (−0,72% – 0,09%) | −0,61 | −44,5% | 0,38% | 0,96 | −0,22% (311) |
| REVERSAL_5D 1d | 15803 | −0,37% (−0,49% – −0,25%) | −2,60 | −99,5% | 0,36% | 1,00 | −0,72% (2178) |
| BREAKOUT_VOLUME 1d | 8009 | −0,73% (−0,89% – −0,58%) | −3,90 | −99,5% | 0,55% | 1,00 | −1,02% (1750) |
| EXISTING_TARGET10 1d (oude model) | 10412 | −0,79% (−0,97% – −0,60%) | −3,27 | −99,5% | 0,70% | 1,00 | −1,40% (2200) |
| EXISTING_TARGET10 2d (oude model) | 10985 | −0,93% (−1,22% – −0,66%) | −2,40 | −99,0% | 0,70% | 1,00 | −0,92% (1941) |

Alle 34 varianten: `reports/research/research_2026-10-10.md` en het dashboard. Model A (richting), B
(verwacht rendement) en C (risicogecorrigeerd) zijn niet beter dan eenvoudige regels en niet beter dan
willekeurige selectie op dezelfde horizon (RANDOM 20d: Sharpe 0,24; RANDOM 1d: −48,7% per jaar).
Het eerder gebouwde rendementsmodel (PR #8) gaf over de hele markt 2025–2026: 1d −0,34% (95%-BI −0,50% –
−0,17%), 2d −0,01% (−0,24% – +0,21%).

### 5b. Verkennend: wat gebeurt er ná de opening? (dagdata, 2017–2025, 4,0 mln aandeel-dagen)

Instap op de opening (de openingsgap is dan bekend), uitstap met limiet +5/+7/+10%, met/zonder stop 5%,
of op het slot na 1–2 dagen; 468 combinaties, Holm-gecorrigeerd: **0 significant**.

| Situatie | P(+5% na opening) | P(−5% na opening) | Sluit boven opening | Beste regel netto/trade | Holdout |
|---|---|---|---|---|---|
| alle normale dagen (gap −3..+3%) | 4,6% | 4,8% | 49,5% | −0,44% | −0,42% |
| gap +3..+10% | 24,2% | 25,9% | 47,3% | −0,49% | −0,71% |
| gap +10..+20% | 47,1% | 53,6% | 44,2% | −0,82% | −1,26% |
| gap > +20% | 62,5% | 77,2% | 37,5% | −1,37% | −0,02% |
| gap < −10% | 58,7% | 52,2% | 47,1% | **+0,43%** (−0,24% – 1,02%; p 0,075) | +0,29% |
| earnings-8-K vóór de opening | 26,4% | 27,1% | 49,6% | −0,43% | −0,52% |
| volatiliteit > 8%/dag | 38,8% | 41,2% | 45,1% | −0,54% | −1,01% |

Een hoge kans op +5% bestaat alleen waar de kans op −5% even hoog is.

## 6. Backtestresultaten en benchmarks

| Benchmark (zelfde periode) | CAGR | Sharpe | Max. DD |
|---|---|---|---|
| SPY kopen en houden (ontwikkeling) | 14,4% | 0,79 | −33,7% |
| Gelijkgewogen universum (zonder kosten) | 18,1% | 0,83 | −41,4% |
| Willekeurig, 1 dag (met kosten en risicolaag) | −48,7% | −4,60 | −99,5% |
| Willekeurig, 20 dagen | 2,8% | 0,24 | −38,2% |
| SPY in de holdout (okt 2025 – okt 2026) | 17,7% | 1,33 | −8,9% |

Beste variant (momentum 20d): CAGR 1,1%, Sharpe 0,18, deflated Sharpe 0,05. Kostenstress 2× maakt elke
variant negatief per dag.

## 7. Risicomanagement

Geïmplementeerd en getest (`research/risk.py`, `tests/test_research_execution_risk.py`): max. positie 10%,
max. bruto blootstelling 100% (geen hefboom), max. 30% per SIC-groep, max. correlatie 0,8 met een
aangehouden positie, min. $2 verhandelde koers en $5 mln dollaromzet, max. spread 2%, max. 1% van de
dagomzet (deelvulling), positiegrootte naar volatiliteit, daglimiet −3% (geen nieuwe orders volgende dag),
drawdownlimiet −20% (20 dagen geen nieuwe orders, dan herstart), NO TRADE bij geen toelaatbare order.
Stops vullen op de opening bij een gap (geen gegarandeerde prijs). Geen enkele regel garandeert tegen
grote verliezen: de drawdowns in §5 zijn mét deze laag.

## 8. Fundamentele analyse

- Controle over 8 bedrijven in 6 sectoren (`reports/research/fundamental_engine_check_2026-10-10.md`):
  volledige DCF voor MSFT en UFPT; PG, JNJ, CAT, BOOT geweigerd met reden (ontbrekende posten/tags), JPM
  (bank) niet van toepassing, XOM (nieuwe holding zonder XBRL-historie) geweigerd met reden.
- Factortoets over 600 point-in-time gekozen aandelen, 2017–2025 (`reports/backtest/fundamental_validation_2026-10-10.md`):
  geen screen met aantoonbaar overrendement (alle |t| < 2); omzetgroei 5j IC t = 2,18 (niet significant na
  correctie); de Piotroski-score voegt niets toe aan simpele waarderingsfactoren (IC 0,011 vs −0,006).

## 9. Paper trading

De tien open voorspellingen van 2026-10-09 (VEEA, WFF, NAUT, SAIQ, APUS, GRML, FLYE, GLND, MEDS, VIVK) staan in
het register met herkomst (rapport van run 38005782062; het originele log was nooit bewaard). Status: alle
tien **OPEN** — instap is de opening van maandag 2026-10-12, uitstap het slot van 2026-10-13; ze worden
daarna automatisch gesloten door de dagelijkse workflow. Ze tellen niet als geslaagd of mislukt. Hash-keten:
intact. Er worden geen paper trades geopend zolang geen strategie PAPER TRADING CANDIDATE is (expliciete
NO TRADE). Live trading: niet geautoriseerd, geen brokerkoppeling.

## 10. Testresultaten

`python -m pytest -q`: **236 geslaagd, 0 mislukt, 0 overgeslagen** (2 waarschuwingen), was 188 bij de start.
Nieuw o.a.: look-ahead-tests per kenmerk, prijsfilter na splits, earnings-reactievlag, kostenmodel,
deelvullingen, handelsstops, gap-stops, risicolimieten, noodstop en herstart, gevectoriseerde correlatie,
statistiek (bootstrap, Holm, deflated Sharpe), protocolstatussen, runner zonder holdout-lek,
registerintegriteit en -uitbreiding, fundamentele fixes.

## 11. Openstaande problemen

1. Survivorship bias (geen gedeliste aandelen met koersen; vraagt een betaalde bron).
2. Geen echte bied/laat- of minuutdata: spreads en impact zijn modellen.
3. Uitsluiting van 777 "split-achtige" aandelen in de hoofdrun op basis van de hele historie.
4. Fundamentele motor: lage dekking (2 van 8 volledige DCF's); geen bank-/verzekeraarsmodel.
5. Uurdata dekt maar 2 jaar.

## 12. Eindoordeel

**NO PROVEN EDGE.** 34 van 34 varianten REJECTED; beste p-waarde 0,29 vóór correctie; geen variant verslaat
SPY op Sharpe; alle 1–2-dagstrategieën verliezen na kosten; 0 van 468 verkennende openingscombinaties
significant. Geen strategie wordt gepaper-traded of gepromoveerd; het systeem blijft dagelijks meten.
