"""SEC EDGAR XBRL fundamentals.

`companyfacts` returns every XBRL fact a filer has ever tagged, which means one
request yields a decade of audited income statement, balance sheet and cash flow
data. That is the primary source here: it is free, needs no API key, and it is
the same 10-K text a careful investor would read rather than a vendor's
pre-chewed summary.

Filers tag the same economic concept under different element names, and change
which one they use over time. Every field below is therefore a priority list of
candidate concepts, merged period by period: the first concept that reports a
given year wins, later concepts backfill years it is missing.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Iterable

from ..models import Company, FiscalYear
from ..net import FetchError, HttpClient
from ..sectors import sector_for_sic

log = logging.getLogger(__name__)

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# Annual report forms, including foreign private issuers.
ANNUAL_FORMS = ("10-K", "10-KT", "20-F", "40-F")

# A reported annual period, allowing for 52/53-week fiscal calendars.
_MIN_ANNUAL_DAYS = 330
_MAX_ANNUAL_DAYS = 400
# How far a balance-sheet instant may sit from an income-statement period end
# and still be treated as the same fiscal year.
_ANCHOR_TOLERANCE_DAYS = 20
# Minimum gap between two anchor dates for them to be distinct fiscal years.
_MIN_YEAR_GAP_DAYS = 300

# ---- concept maps ------------------------------------------------------

DURATION_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": (
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "tax_expense": ("IncomeTaxExpenseBenefit",),
    "net_income": (
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ),
    "interest_expense": (
        "InterestExpense",
        "InterestExpenseDebt",
        "InterestIncomeExpenseNet",
    ),
    "sga": (
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    ),
    "cfo": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsForCapitalImprovements",
    ),
    "depreciation_amortization": (
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
        "Depreciation",
    ),
    "dividends_paid": (
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfDividends",
    ),
    "buybacks": ("PaymentsForRepurchaseOfCommonStock",),
}

INSTANT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "short_term_investments": (
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ),
    "long_term_investments": (
        "LongTermInvestments",
        "MarketableSecuritiesNoncurrent",
    ),
    "inventory": ("InventoryNet",),
    "receivables": (
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
    ),
    "ppe_gross": ("PropertyPlantAndEquipmentGross",),
    "ppe_net": ("PropertyPlantAndEquipmentNet",),
    "goodwill": ("Goodwill",),
    "intangibles": (
        "FiniteLivedIntangibleAssetsNet",
        "IntangibleAssetsNetExcludingGoodwill",
    ),
    "retained_earnings": ("RetainedEarningsAccumulatedDeficit",),
    "long_term_debt": (
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
    ),
    "short_term_debt": (
        "DebtCurrent",
        "ShortTermBorrowings",
        "LongTermDebtCurrent",
    ),
}

PER_SHARE_CONCEPTS: dict[str, tuple[str, ...]] = {
    "eps_diluted": ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
    "dividends_per_share": (
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    ),
}

SHARE_COUNT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "diluted_shares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
    "shares_outstanding": (
        "CommonStockSharesOutstanding",
        "CommonStockSharesIssued",
    ),
}


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _unit_values(concept_data: dict[str, Any], unit_keys: Iterable[str]) -> list[dict]:
    """Facts from the first matching unit bucket (USD, shares, USD/shares...)."""
    units = concept_data.get("units", {})
    for key in unit_keys:
        if key in units:
            return units[key]
    return []


def _is_annual_form(form: str | None) -> bool:
    if not form:
        return False
    return any(form.startswith(prefix) for prefix in ANNUAL_FORMS)


def _collect(
    taxonomy: dict[str, Any],
    concept: str,
    unit_keys: Iterable[str],
    *,
    instant: bool,
) -> dict[date, float]:
    """One concept's annual facts, keyed by period end.

    Where a filer reports the same period more than once, the most recently
    filed value wins, which picks up restatements.
    """
    data = taxonomy.get(concept)
    if not data:
        return {}
    values: dict[date, float] = {}
    best_filed: dict[date, str] = {}
    for fact in _unit_values(data, unit_keys):
        if not _is_annual_form(fact.get("form")):
            continue
        end = _parse_date(fact.get("end", ""))
        if end is None:
            continue
        start_raw = fact.get("start")
        if instant:
            # Balance-sheet facts carry no start date.
            if start_raw:
                continue
        else:
            start = _parse_date(start_raw or "")
            if start is None:
                continue
            span = (end - start).days
            if not _MIN_ANNUAL_DAYS <= span <= _MAX_ANNUAL_DAYS:
                continue
        value = fact.get("val")
        if value is None:
            continue
        filed = fact.get("filed", "")
        if end in values and filed <= best_filed.get(end, ""):
            continue
        values[end] = float(value)
        best_filed[end] = filed
    return values


def _backfilled(
    taxonomy: dict[str, Any],
    concepts: tuple[str, ...],
    unit_keys: Iterable[str],
    *,
    instant: bool,
) -> dict[date, float]:
    """Merge a priority list of concepts: earlier ones win, later ones backfill.

    Filers migrate between elements over time, so the oldest years of a series
    often live under a concept the newest years no longer use.
    """
    out: dict[date, float] = {}
    for concept in concepts:
        for end, value in _collect(taxonomy, concept, unit_keys, instant=instant).items():
            out.setdefault(end, value)
    return out


def _anchor_dates(series: Iterable[dict[date, float]]) -> list[date]:
    """Distinct fiscal period ends, newest-first clustering, returned ascending."""
    candidates: set[date] = set()
    for mapping in series:
        candidates.update(mapping.keys())
    if not candidates:
        return []
    anchors: list[date] = []
    for when in sorted(candidates, reverse=True):
        if not anchors or (anchors[-1] - when).days >= _MIN_YEAR_GAP_DAYS:
            anchors.append(when)
    return sorted(anchors)


def _nearest(mapping: dict[date, float], anchor: date, tolerance: int) -> float | None:
    """Value whose period end sits closest to `anchor` within `tolerance` days."""
    best: float | None = None
    best_gap = tolerance + 1
    for when, value in mapping.items():
        gap = abs((when - anchor).days)
        if gap < best_gap:
            best, best_gap = value, gap
    return best


def parse_companyfacts(payload: dict[str, Any]) -> tuple[list[FiscalYear], float | None]:
    """Turn a companyfacts document into annual periods, oldest first.

    Returns the fiscal years plus the latest reported shares outstanding from
    the DEI cover page, which is more current than any weighted-average count.
    """
    facts = payload.get("facts", {})
    us_gaap = facts.get("us-gaap", {})
    ifrs = facts.get("ifrs-full", {})
    dei = facts.get("dei", {})
    # Foreign filers on IFRS use a parallel taxonomy; us-gaap elements win where
    # both exist, IFRS backfills.
    taxonomy = {**ifrs, **us_gaap}

    duration: dict[str, dict[date, float]] = {
        field: _backfilled(taxonomy, concepts, ("USD",), instant=False)
        for field, concepts in DURATION_CONCEPTS.items()
    }
    instant: dict[str, dict[date, float]] = {
        field: _backfilled(taxonomy, concepts, ("USD",), instant=True)
        for field, concepts in INSTANT_CONCEPTS.items()
    }
    per_share: dict[str, dict[date, float]] = {
        field: _backfilled(taxonomy, concepts, ("USD/shares",), instant=False)
        for field, concepts in PER_SHARE_CONCEPTS.items()
    }
    share_counts: dict[str, dict[date, float]] = {
        "diluted_shares": _backfilled(
            taxonomy, SHARE_COUNT_CONCEPTS["diluted_shares"], ("shares",), instant=False
        ),
        "shares_outstanding": _backfilled(
            taxonomy, SHARE_COUNT_CONCEPTS["shares_outstanding"], ("shares",), instant=True
        ),
    }

    # Income-statement and cash-flow periods define the fiscal calendar.
    anchors = _anchor_dates(
        [duration["revenue"], duration["net_income"], duration["cfo"]]
    )
    if not anchors:
        return [], _latest_dei_shares(dei)

    years: list[FiscalYear] = []
    for anchor in anchors:
        row = FiscalYear(period_end=anchor, label=anchor.year)
        for field, mapping in duration.items():
            setattr(row, field, _nearest(mapping, anchor, _ANCHOR_TOLERANCE_DAYS))
        for field, mapping in instant.items():
            setattr(row, field, _nearest(mapping, anchor, _ANCHOR_TOLERANCE_DAYS))
        for field, mapping in per_share.items():
            setattr(row, field, _nearest(mapping, anchor, _ANCHOR_TOLERANCE_DAYS))
        for field, mapping in share_counts.items():
            setattr(row, field, _nearest(mapping, anchor, _ANCHOR_TOLERANCE_DAYS))

        # Derive what the filer did not tag directly, from what it did.
        _fill_derived(row)
        years.append(row)

    return years, _latest_dei_shares(dei)


def _fill_derived(row: FiscalYear) -> None:
    """Fill gaps by identity only. No estimates, no sector averages."""
    if row.liabilities is None and row.assets is not None and row.equity is not None:
        row.liabilities = row.assets - row.equity
    if row.equity is None and row.assets is not None and row.liabilities is not None:
        row.equity = row.assets - row.liabilities
    if row.pretax_income is None and row.net_income is not None and row.tax_expense is not None:
        row.pretax_income = row.net_income + row.tax_expense
    if (
        row.eps_diluted is None
        and row.net_income is not None
        and row.diluted_shares
    ):
        row.eps_diluted = row.net_income / row.diluted_shares
    if (
        row.diluted_shares is None
        and row.net_income is not None
        and row.eps_diluted
    ):
        row.diluted_shares = row.net_income / row.eps_diluted
    if row.ppe_gross is None and row.ppe_net is not None:
        # Gross PP&E only feeds Beneish depreciation-rate terms; using net where
        # gross is untagged is noted rather than silently equated.
        row.ppe_gross = row.ppe_net


def _latest_dei_shares(dei: dict[str, Any]) -> float | None:
    concept = dei.get("EntityCommonStockSharesOutstanding")
    if not concept:
        return None
    best_date: date | None = None
    best_value: float | None = None
    for fact in _unit_values(concept, ("shares",)):
        end = _parse_date(fact.get("end", ""))
        value = fact.get("val")
        if end is None or value is None:
            continue
        if best_date is None or end > best_date:
            best_date, best_value = end, float(value)
    return best_value


# ---- network entry points ---------------------------------------------


def load_ticker_map(client: HttpClient) -> dict[str, str]:
    """Ticker to zero-padded CIK. Cached for a week; the file rarely changes."""
    payload = client.get_json(
        COMPANY_TICKERS_URL, namespace="edgar-tickers", ttl=7 * 24 * 3600
    )
    mapping: dict[str, str] = {}
    rows = payload.values() if isinstance(payload, dict) else payload
    for row in rows:
        ticker = str(row.get("ticker", "")).upper().strip()
        cik = row.get("cik_str")
        if ticker and cik is not None:
            mapping[ticker] = str(cik).zfill(10)
    return mapping


def fetch_company(
    client: HttpClient,
    ticker: str,
    cik: str,
    *,
    with_submissions: bool = True,
) -> Company:
    """Fetch and normalise one filer's audited annual history."""
    facts = client.get_json(
        COMPANYFACTS_URL.format(cik=cik), namespace="edgar-facts"
    )
    years, dei_shares = parse_companyfacts(facts)
    company = Company(
        ticker=ticker,
        cik=cik,
        name=facts.get("entityName", ticker),
        years=years,
        shares_outstanding=dei_shares,
    )
    if dei_shares is None and years:
        company.shares_outstanding = years[-1].shares_outstanding or years[-1].diluted_shares
        company.add_note("shares outstanding taken from the last 10-K, not a cover page")

    if with_submissions:
        try:
            meta = client.get_json(
                SUBMISSIONS_URL.format(cik=cik),
                namespace="edgar-submissions",
                ttl=7 * 24 * 3600,
            )
        except FetchError as exc:
            log.debug("submissions unavailable for %s: %s", ticker, exc)
        else:
            company.name = meta.get("name") or company.name
            company.sic = meta.get("sic")
            company.sector = sector_for_sic(company.sic)
            company.fiscal_year_end = meta.get("fiscalYearEnd")

    return company
