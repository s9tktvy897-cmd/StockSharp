"""Normalized line items and the XBRL concepts that report them, in priority order.

Concepts in one list must be synonyms for the same figure; the first one that has a value for
a period wins and disagreements between them are reported as data-quality issues."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineItem:
    name: str
    concepts: tuple[str, ...]
    instant: bool = False
    unit: str = "USD"
    share_basis: str | None = None  # "shares" (x split factor) or "per_share" (/ split factor)
    taxonomy: str = "us-gaap"


def _d(name, *concepts, **kw):
    return LineItem(name, concepts, **kw)


def _i(name, *concepts, **kw):
    return LineItem(name, concepts, instant=True, **kw)


LINE_ITEMS: tuple[LineItem, ...] = (
    # Income statement
    _d("revenue", "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
       "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"),
    _d("cost_of_revenue", "CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"),
    _d("gross_profit", "GrossProfit"),
    _d("research_development", "ResearchAndDevelopmentExpense"),
    _d("sga", "SellingGeneralAndAdministrativeExpense"),
    _d("operating_income", "OperatingIncomeLoss"),
    _d("interest_expense", "InterestExpense", "InterestExpenseNonoperating"),
    _d("pretax_income",
       "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
       "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
    _d("income_tax", "IncomeTaxExpenseBenefit"),
    _d("net_income", "NetIncomeLoss"),
    _d("eps_diluted", "EarningsPerShareDiluted", unit="USD/shares", share_basis="per_share"),
    _d("diluted_shares", "WeightedAverageNumberOfDilutedSharesOutstanding", unit="shares", share_basis="shares"),
    # Cash-flow statement
    # "Depreciation" alone (without amortization) is the last resort: it understates D&A, which makes
    # FCFF and EBITDA lower, i.e. conservative (MSFT reports only this concept).
    _d("depreciation_amortization", "DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
       "DepreciationAndAmortization", "Depreciation"),
    _d("stock_based_compensation", "ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"),
    _d("operating_cash_flow", "NetCashProvidedByUsedInOperatingActivities",
       "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    _d("capex", "PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    _d("dividends_paid", "PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
    _d("buybacks", "PaymentsForRepurchaseOfCommonStock"),
    # Balance sheet
    _i("total_assets", "Assets"),
    _i("current_assets", "AssetsCurrent"),
    # Fallback: filers that show restricted cash on the cash line (PG since 2019) only tag the total
    # incl. restricted cash; slightly overstates cash, so net debt is slightly understated.
    _i("cash", "CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    _i("short_term_investments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesCurrent",
       "AvailableForSaleSecuritiesDebtSecuritiesCurrent", "ShortTermInvestments"),
    _i("long_term_investments", "MarketableSecuritiesNoncurrent", "AvailableForSaleSecuritiesNoncurrent",
       "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"),
    _i("receivables", "AccountsReceivableNetCurrent"),
    _i("inventory", "InventoryNet"),
    _i("ppe_net", "PropertyPlantAndEquipmentNet"),
    _i("total_liabilities", "Liabilities"),
    _i("current_liabilities", "LiabilitiesCurrent"),
    _i("long_term_debt_noncurrent", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"),
    _i("long_term_debt_current", "LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
    _i("commercial_paper", "CommercialPaper"),
    # OtherShortTermBorrowings is left out: filers use it for commercial paper too (AAPL 10-Qs, 2020).
    _i("short_term_borrowings", "ShortTermBorrowings"),
    _i("equity", "StockholdersEquity"),
    _i("minority_interest", "MinorityInterest"),
    _i("equity_including_nci", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    _i("liabilities_and_equity", "LiabilitiesAndStockholdersEquity"),
    _i("retained_earnings", "RetainedEarningsAccumulatedDeficit"),
)

DEBT_COMPONENTS = ("long_term_debt_noncurrent", "long_term_debt_current", "commercial_paper", "short_term_borrowings")

# Components a company may simply not have: never reported means zero (with a note).
OPTIONAL_ITEMS = DEBT_COMPONENTS + ("short_term_investments", "long_term_investments", "minority_interest")

# Concepts whose restatements between filings reveal stock splits.
SPLIT_EVIDENCE_CONCEPTS = ("WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic")

ITEMS_BY_NAME = {item.name: item for item in LINE_ITEMS}
