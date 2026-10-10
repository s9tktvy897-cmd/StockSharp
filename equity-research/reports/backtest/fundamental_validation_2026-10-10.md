# Backtest langetermijnscreens — 2026-10-10

> Onderzoek naar het verleden, geen voorspelling of advies. Rendementen zijn overrendementen t.o.v. het gelijkgewogen gemiddelde van het universum op dezelfde datum.

## 1. Opzet

- Universum: 600 aandelen, point-in-time gekozen: genoteerd vóór 2017, de 300 hoogste 20-daagse dollaromzet op 2017-04-28 plus 300 willekeurige (seed 20261010) met >= 1 mln USD/dag; Yahoo Finance (secundair)
- Herbalancering: 2017-04-30, 2018-04-30, 2019-04-30, 2020-04-30, 2021-04-30, 2022-04-30, 2023-04-30, 2024-04-30, 2025-04-30
- Horizon: 365 dagen, instap op de eerste opening na de datum, uitstap op het laatste slot binnen de horizon
- Point-in-time: jaarcijfers zoals op de herbalanceringsdatum ingediend (latere herzieningen tellen niet), splits pas na de split; jaarcijfers ouder dan 15 maanden worden overgeslagen
- Waarnemingen: 4517, met rendement: 4517
- Code: adeca9e

**Vertekeningen:** survivorship bias (alleen nu genoteerde aandelen; verdwenen bedrijven ontbreken, wat resultaten te gunstig maakt); de volgorde van de SEC-lijst bevoordeelt grote bedrijven; drempels komen uit de literatuur en zijn niet op deze data afgesteld; geen transactiekosten (jaarlijkse herbalancering).

**Ontbrekend:** SEC CAF: HTTP 404 for https://data.sec.gov/api/xbrl/companyfacts/CIK0001368493.json; SEC DIA: HTTP 404 for https://data.sec.gov/api/xbrl/companyfacts/CIK0001041130.json; SEC HIO: HTTP 404 for https://data.sec.gov/api/xbrl/companyfacts/CIK0000910068.json; SEC IGD: HTTP 404 for https://data.sec.gov/api/xbrl/companyfacts/CIK0001285890.json; SEC ISD: HTTP 404 for https://data.sec.gov/api/xbrl/companyfacts/CIK0001534880.json; SEC MDY: HTTP 404 for https://data.sec.gov/api/xbrl/companyfacts/CIK0000936958.json; NBIX 2018-04-30: float division by zero; SEC PEO: HTTP 404 for https://data.sec.gov/api/xbrl/companyfacts/CIK0000216851.json …

## 2. Screens

| Screen | n | Gem. overrendement | Mediaan | Beter dan universum (95%-BI) | t | n rest | Gem. rest |
|---|---|---|---|---|---|---|---|
| Piotroski >= 7 (strong) | 785 | -0,1% | -1,3% | 48,2% (44,7%–51,6%) | -0,08 | 1276 | 1,3% |
| Piotroski <= 3 (weak) | 100 | 23,2% | -13,9% | 34,0% (25,5%–43,7%) | 1,43 | 1961 | -0,4% |
| Beneish flagged | 55 | 9,9% | -7,4% | 43,6% (31,4%–56,7%) | 1,01 | 1081 | 1,1% |
| Altman distress zone | 722 | -0,1% | -9,9% | 40,3% (36,8%–43,9%) | -0,04 | 2243 | -0,5% |
| Revenue CAGR 5y >= 10% | 1134 | 2,3% | -2,7% | 47,2% (44,3%–50,1%) | 1,51 | 2779 | -0,2% |
| FCF positive and rising >= 3 of 5 years | 2224 | -1,3% | -2,9% | 46,0% (44,0%–48,1%) | -1,33 | 2031 | 1,4% |

- Piotroski >= 7 (strong): geen aantoonbaar verschil met het universum (|t| = 0,08)
- Piotroski <= 3 (weak): geen aantoonbaar verschil met het universum (|t| = 1,43)
- Beneish flagged: geen aantoonbaar verschil met het universum (|t| = 1,01)
- Altman distress zone: geen aantoonbaar verschil met het universum (|t| = 0,04)
- Revenue CAGR 5y >= 10%: geen aantoonbaar verschil met het universum (|t| = 1,51)
- FCF positive and rising >= 3 of 5 years: geen aantoonbaar verschil met het universum (|t| = 1,33)

## 3. Voorspellende waarde per factor (rangcorrelatie met het rendement, per datum)

| Factor | Data | Gem. IC | t (over data) |
|---|---|---|---|
| earnings_yield | 9 | 0,033 | 0,83 |
| fcf_yield | 9 | 0,020 | 0,41 |
| book_to_market | 9 | -0,044 | -0,60 |
| piotroski | 9 | 0,045 | 1,71 |
| revenue_cagr_5y | 9 | 0,072 | 2,18 |

**Voegt de Piotroski-score iets toe aan simpele waarderingsfactoren?** (zelfde aandelen en data)

| Samenstelling | Data | Gem. IC | t |
|---|---|---|---|
| value | 9 | -0,006 | -0,10 |
| value_plus_piotroski | 9 | 0,011 | 0,22 |

Een |t| boven 2 is een aanwijzing, geen bewijs: er zijn meerdere factoren getest en het aantal herbalanceringsdata is klein. Geen transactiekosten.

## 4. Rangcorrelatie Piotroski-score en rendement (per datum, ≥ 10 aandelen)

| Datum | Spearman |
|---|---|
| 2017-04-30 | 0,015 |
| 2018-04-30 | 0,122 |
| 2019-04-30 | 0,064 |
| 2020-04-30 | -0,059 |
| 2021-04-30 | 0,014 |
| 2022-04-30 | 0,129 |
| 2023-04-30 | 0,144 |
| 2024-04-30 | 0,052 |
| 2025-04-30 | -0,075 |

Gemiddeld 0,045 over 9 data.
