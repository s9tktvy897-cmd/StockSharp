"""Smoke-test live data: ``python -m equity_research.data AAPL [--years 10]``.

Prints the SEC profile and the raw annual series of a few core concepts, each value with
its filing. No mapping or calculation happens here (that is fundamentals/)."""

from __future__ import annotations

import argparse
from pathlib import Path

from equity_research.data.cache import DiskCache
from equity_research.data.http import HttpClient, user_agent_from_env
from equity_research.data.sec_edgar import SecEdgar

CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"

CORE_CONCEPTS = [
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
    ("us-gaap", "Revenues", "USD"),
    ("us-gaap", "NetIncomeLoss", "USD"),
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivities", "USD"),
    ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment", "USD"),
    ("us-gaap", "Assets", "USD"),
    ("us-gaap", "Liabilities", "USD"),
    ("us-gaap", "StockholdersEquity", "USD"),
    ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", "shares"),
    ("dei", "EntityCommonStockSharesOutstanding", "shares"),
]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m equity_research.data")
    parser.add_argument("ticker")
    parser.add_argument("--years", type=int, default=10)
    args = parser.parse_args(argv)

    edgar = SecEdgar(HttpClient(user_agent_from_env()), DiskCache(CACHE_DIR))
    cik = edgar.cik_for_ticker(args.ticker)
    profile = edgar.profile(cik)
    print(f"{profile.name}  CIK {profile.cik}  tickers {','.join(profile.tickers)}  "
          f"exchanges {','.join(profile.exchanges)}")
    print(f"SIC {profile.sic} ({profile.sic_description})  fiscal year end {profile.fiscal_year_end}")

    facts = edgar.company_facts(cik)
    print(f"retrieved {facts.retrieved}, {len(facts.concepts())} us-gaap concepts\n")
    for taxonomy, concept, unit in CORE_CONCEPTS:
        series = facts.annual(concept, unit=unit, taxonomy=taxonomy)[-args.years:]
        print(f"{taxonomy}:{concept} [{unit}]")
        if not series:
            print("  (not reported in 10-K filings)")
        for fact in series:
            start = f"{fact.period_start} .. " if fact.period_start else ""
            print(f"  {start}{fact.period_end}  {fact.value:>20,.0f}  filed {fact.filed}  {fact.accession}")
        print()


if __name__ == "__main__":
    main()
