---
name: brede-bronnen
description: Breed webonderzoek over honderden pagina's en tientallen betrouwbare sites voor een aandelenanalyse (equity-research). Gebruik bij elke analyse van een aandeel, vóór `equity-research analyze --context`, en als de gebruiker vraagt om nieuws, context of "alle bronnen" over een bedrijf.
---

# Breed bronnenonderzoek voor een aandelenanalyse

Doel: zo veel mogelijk **betrouwbare, verschillende** bronnen bekijken (richtwaarde: ≥ 100 bekeken
pagina's, ≥ 25 verschillende sites bij een groot bedrijf; bij kleine bedrijven is er minder, en dat
wordt dan gemeld, niet opgevuld). Kwaliteit gaat vóór aantal: een onbekende of ongedateerde site telt
niet mee. Alle regels uit `equity-research/CLAUDE.md` blijven gelden (niets verzinnen, elk punt met
URL en datum, websitegetallen zijn secundair en gaan nooit de berekeningen in).

## 1. Uitwaaieren: acht zoekagenten tegelijk

Start in **één bericht** acht `Agent`-aanroepen (`subagent_type: general-purpose`), één per categorie.
Geef elke agent: ticker, bedrijfsnaam, CIK, sector, de peildatum, en deze opdracht:

> Zoek met WebSearch en WebFetch (minstens 15 zoekopdrachten, open de beste resultaten) naar
> <categorie> over <bedrijf> (<ticker>) van de afgelopen 12 maanden. Gebruik alleen betrouwbare
> sites met een datum op de pagina. Verzin niets; neem een getal alleen over zoals het op de
> pagina staat. Lever:
> (a) punten in exact dit formaat, één per regel:
>     `- YYYY-MM-DD: <feit in het Nederlands> (**officieel** | **secundair** | **gerucht**): <URL>`
>     (datum van publicatie of gebeurtenis; onbekend → ophaaldatum + "(opgehaald; publicatiedatum onbekend)");
> (b) een lijst `- YYYY-MM-DD: geraadpleegd, geen nieuw punt: <URL>` van bekeken pagina's zonder nieuw feit;
> (c) tegenstrijdigheden en wat niet te vinden of te openen was (betaalmuur, blokkade).

| # | Categorie | Voorbeelden van bronnen |
|---|---|---|
| 1 | Officieel | SEC EDGAR: 8-K, 10-Q/10-K, DEF 14A, S-1/S-3 (emissies), SC 13D/G; IR-site; persberichten (Business Wire, PR Newswire, GlobeNewswire) |
| 2 | Persbureaus en financiële media | Reuters, AP, Bloomberg, CNBC, WSJ, FT, Barron's, MarketWatch, NYT, Fortune, Axios |
| 3 | Toezicht en juridisch | FDA, FTC, DOJ, SEC-handhaving, CFPB, FCC, NHTSA, FAA, EU-Commissie, CMA, rechtbanken (CourtListener), USPTO — wat bij de sector past |
| 4 | Vakmedia van de sector | bv. Fierce Biotech/Endpoints/STAT (biotech), The Verge/Ars Technica/AnandTech (tech), Utility Dive (energie), Automotive News |
| 5 | Analisten en consensus (secundair) | ratingwijzigingen, koersdoelen, transcripties van de cijferpresentatie, kredietbeoordelaars (S&P, Moody's, Fitch) |
| 6 | Concurrenten, klanten, toeleveranciers | hun filings en persberichten die het bedrijf noemen; marktaandeel; contracten |
| 7 | Management, governance, insiders | bestuurswissels, beloning, Form 4 (insiderhandel), activistische aandeelhouders, overnames |
| 8 | Internationaal en macro | grote niet-Engelstalige media (Nikkei, Handelsblatt, Caixin, Les Echos, FD) bij buitenlandse omzet; handelsbeleid, importheffingen, sectorcijfers van overheden |

## 2. Samenvoegen en controleren (zelf, niet uitbesteden)

1. Ontdubbel: hetzelfde feit uit meerdere bronnen wordt één punt met alle URL's.
2. **Controleer** zwaarwegende claims (CEO-wissel, overname, guidance, cijferdatum, rechtszaak,
   FDA-besluit) tegen de officiële bron (8-K/filingpagina, IR-site, toezichthouder) en zet erbij
   **Geverifieerd** of **niet geverifieerd**.
3. Tegenstrijdige berichten: beide noemen; de officiële filing wint.
4. Schrijf `equity-research/reports/context/<TICKER>_<YYYY-MM-DD>.md` met de kopjes Management,
   Recente cijfers en verwachtingen, Producten, Juridisch en regelgeving, Concurrentie en keten,
   Analisten (secundair), en als laatste `### Geraadpleegd zonder nieuw punt` (lijst (b)).
   Een `### Niet bereikbaar`-kopje noemt betaalmuren en blokkades (zonder opsommingsteken, of met URL en datum).
5. Draai `equity-research analyze <TICKER> --context reports/context/<TICKER>_<datum>.md`. Het rapport
   toont automatisch de **dekking** (punten, pagina's, verschillende sites per soort) en waarschuwt
   bij minder dan 10 sites.

## 3. In de chat melden

Aantal bekeken pagina's en verschillende sites (uit de dekkingsregel), welke categorieën weinig
opleverden, wat niet geverifieerd kon worden, en tegenstrijdigheden.
