# Controle fundamentele engine over sectoren — 2026-10-10

> Werkt de DCF-/scoremotor betrouwbaar buiten Apple? Uitgevoerd met `python -m equity_research.valuation <TICKER>`
> en `python -m equity_research.risk <TICKER>` op live SEC-data (companyfacts, 2026-10-10), Yahoo-koersen (secundair),
> FRED en Damodaran. Geen beleggingsadvies; de waarden hieronder zijn modeluitkomsten met aannames.

| Ticker | Sector / grootte | Uitkomst na de fixes | Oorzaak bij weigering |
|---|---|---|---|
| MSFT | technologie, large cap | volledige DCF; base $364,62 bij koers $535,07 (−32%); reverse DCF: koers impliceert 21,5% omzetgroei | – |
| UFPT | medische technologie, small cap | volledige DCF; base $300,87 bij koers $288,97 (+4%) | – |
| PG | consumentengoederen, large cap | WACC 6,44%; DCF geweigerd | geen RONIC-historie (gaten in schuldposten in eerdere jaren) |
| JNJ | gezondheidszorg, large cap | DCF geweigerd | `long_term_debt_current` niet gerapporteerd op de laatste balansdatum; geen rentekosten-reeks |
| CAT | industrie, large cap | DCF geweigerd | schuld met bedrijfseigen XBRL-tags per segment; standaardtags ontbreken |
| BOOT | consumentengoederen, mid cap | DCF geweigerd | geen standaardtag voor rentekosten (alleen netto rente) |
| JPM | financiële dienstverlening | niet van toepassing | banken (SIC 6000–6799) vragen een dividend-/excess-return-model; nog niet gebouwd |
| XOM | energie | geweigerd met reden | ticker wijst nu naar de nieuwe holding ExxonMobil Holdings Corp (CIK 2115436) zonder XBRL-historie; de cijfers staan onder het oude CIK |

## Gevonden en opgeloste fouten

1. Schuld- of effectenregel die het bedrijf niet meer rapporteert blokkeerde de DCF (MSFT, JNJ, CAT, BOOT):
   een regel die laatst als 0 werd gerapporteerd telt nu als 0; een regel die meer dan twee jaar vóór de
   balansdatum voor het laatst voorkwam telt als 0 met een **gelabelde aanname** (datum van de laatste melding).
2. Werkkapitaal en RONIC werden daardoor uit 2016–2018 berekend (MSFT): nu uit de laatste jaren.
3. Afschrijvingen: MSFT tagt alleen `Depreciation`; nu laatste reserve (onderschat D&A → conservatief).
4. Kas: PG tagt sinds 2019 kas inclusief geblokkeerde kas; nu reserve (overschat kas licht).
5. Crash bij ontbrekende capex in de multiples (UFPT) en bij een bedrijf zonder jaarcijfers (XOM): nu
   "ontbreekt" respectievelijk een duidelijke weigering.
6. Marktwaarde in de fundamentele backtest gebruikte de split-gecorrigeerde koers × het toenmalige aantal
   aandelen: na een latere split veel te laag (o.a. Altman Z). Nu de toen verhandelde koers.

## Conclusie

De motor verzint niets en weigert liever, maar rekent in deze steekproef maar voor 2 van de 8 bedrijven een
volledige DCF. Verdere dekking vraagt bedrijfsspecifieke XBRL-tags of handmatige invoer met bron
(`--cost-of-debt ... --cost-of-debt-source ...`), en een apart model voor banken en verzekeraars.
De voorspellende waarde van de scores: zie `reports/backtest/fundamental_validation_2026-10-10.md`
(geen enkele screen of factor aantoonbaar na correctie voor meervoudig testen).
