"""Synthetic filers for testing and for offline dry runs.

The engine cannot be validated against live quotes in every environment, so the
fixtures here build EDGAR-shaped payloads and fully formed `Company` objects with
values chosen so that every formula's expected output can be worked out by hand.

`build_companyfacts` derives its element names from the concept maps in
`data.edgar`, so a fixture cannot silently drift away from the parser it tests.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .data import edgar
from .data.edgar import (
    DURATION_CONCEPTS,
    INSTANT_CONCEPTS,
    PER_SHARE_CONCEPTS,
    SHARE_COUNT_CONCEPTS,
)
from .models import Company, FiscalYear, PriceHistory

# field name -> (element, unit, is_instant)
_FIELD_SPECS: dict[str, tuple[str, str, bool]] = {}
for _field, _concepts in DURATION_CONCEPTS.items():
    _FIELD_SPECS[_field] = (_concepts[0], "USD", False)
for _field, _concepts in INSTANT_CONCEPTS.items():
    _FIELD_SPECS[_field] = (_concepts[0], "USD", True)
for _field, _concepts in PER_SHARE_CONCEPTS.items():
    _FIELD_SPECS[_field] = (_concepts[0], "USD/shares", False)
_FIELD_SPECS["diluted_shares"] = (SHARE_COUNT_CONCEPTS["diluted_shares"][0], "shares", False)
_FIELD_SPECS["shares_outstanding"] = (
    SHARE_COUNT_CONCEPTS["shares_outstanding"][0],
    "shares",
    True,
)


def build_companyfacts(
    years: list[dict[str, Any]],
    *,
    entity_name: str = "Testco Inc.",
    dei_shares: float | None = None,
    extra_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble an EDGAR companyfacts document from plain year dictionaries.

    Each year dict needs an `end` key (ISO date string) plus any `FiscalYear`
    field names. Duration facts get a start date one year earlier.
    """
    taxonomy: dict[str, Any] = {}

    for row in years:
        end = date.fromisoformat(row["end"])
        start = end - timedelta(days=364)
        filed = (end + timedelta(days=45)).isoformat()
        for field_name, value in row.items():
            if field_name == "end" or value is None:
                continue
            spec = _FIELD_SPECS.get(field_name)
            if spec is None:
                raise KeyError(f"no EDGAR element mapped for fixture field {field_name!r}")
            element, unit, is_instant = spec
            fact: dict[str, Any] = {
                "end": end.isoformat(),
                "val": value,
                "form": "10-K",
                "filed": filed,
                "fy": end.year,
                "fp": "FY",
            }
            if not is_instant:
                fact["start"] = start.isoformat()
            bucket = taxonomy.setdefault(element, {"units": {}})
            bucket["units"].setdefault(unit, []).append(fact)

    facts: dict[str, Any] = {"us-gaap": taxonomy}
    if dei_shares is not None:
        last_end = max(date.fromisoformat(r["end"]) for r in years)
        facts["dei"] = {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [
                        {
                            "end": (last_end + timedelta(days=30)).isoformat(),
                            "val": dei_shares,
                            "form": "10-K",
                            "filed": (last_end + timedelta(days=45)).isoformat(),
                        }
                    ]
                }
            }
        }
    if extra_facts:
        facts.update(extra_facts)
    return {"entityName": entity_name, "cik": 1234567, "facts": facts}


def make_price_history(
    last_close: float,
    days: int = 400,
    *,
    end: date | None = None,
    annual_drift: float = 0.0,
    source: str = "fixture",
) -> PriceHistory:
    """A smooth price path ending at `last_close`.

    Deliberately smooth: realised volatility then comes out near zero, which
    keeps the discount rate at its configured floor and makes valuation tests
    depend only on the inputs under test.
    """
    history = PriceHistory(source=source)
    end = end or date(2026, 8, 14)
    daily = (1.0 + annual_drift) ** (1 / 252) - 1.0
    for offset in range(days, 0, -1):
        history.dates.append(end - timedelta(days=offset - 1))
        history.closes.append(last_close / ((1.0 + daily) ** (offset - 1)))
    return history


def make_company(
    ticker: str = "TEST",
    *,
    name: str = "Testco Inc.",
    sector: str = "Industrials",
    years: list[FiscalYear] | None = None,
    shares_outstanding: float = 1_000_000_000.0,
    last_close: float = 100.0,
    price_days: int = 400,
) -> Company:
    company = Company(
        ticker=ticker,
        cik="0001234567",
        name=name,
        sector=sector,
        years=years or [],
        shares_outstanding=shares_outstanding,
    )
    company.prices = make_price_history(last_close, days=price_days)
    return company


def steady_compounder(
    *,
    start_year: int = 2020,
    count: int = 6,
    revenue: float = 10_000e6,
    revenue_growth: float = 0.07,
    net_margin: float = 0.18,
    gross_margin: float = 0.55,
    operating_margin: float = 0.26,
    shares: float = 1_000e6,
    share_buyback: float = 0.015,
    dividend_payout: float = 0.30,
) -> list[FiscalYear]:
    """A high-quality operating business: growing, cash generative, deleveraging.

    Built to clear every gate so that gate tests can isolate one failure at a
    time by degrading a single input. Margins, asset turnover and liquidity all
    improve slightly year over year, which is what a genuine compounder looks
    like and what the Piotroski signals are built to detect.
    """
    rows: list[FiscalYear] = []
    current_revenue = revenue
    current_shares = shares
    equity = revenue * 0.55
    long_term_debt = revenue * 0.25
    ppe_net = revenue * 0.35

    for index in range(count):
        year = start_year + index
        # Gentle operating leverage: margins widen a touch each year.
        year_gross_margin = gross_margin + 0.004 * index
        year_operating_margin = operating_margin + 0.004 * index
        net_income = current_revenue * (net_margin + 0.003 * index)
        operating_income = current_revenue * year_operating_margin
        depreciation = ppe_net * 0.12
        capex = current_revenue * 0.05
        cfo = net_income + depreciation
        eps = net_income / current_shares
        dps = eps * dividend_payout
        # Assets grow more slowly than revenue, so turnover and return on assets
        # improve rather than staying flat.
        assets = current_revenue * (1.30 - 0.01 * index)
        current_liabilities = current_revenue * 0.22
        tax_expense = operating_income * 0.21

        rows.append(
            FiscalYear(
                period_end=date(year, 12, 31),
                label=year,
                revenue=current_revenue,
                gross_profit=current_revenue * year_gross_margin,
                operating_income=operating_income,
                pretax_income=operating_income * 0.96,
                tax_expense=tax_expense,
                net_income=net_income,
                eps_diluted=eps,
                diluted_shares=current_shares,
                shares_outstanding=current_shares,
                interest_expense=long_term_debt * 0.04,
                sga=current_revenue * 0.18,
                assets=assets,
                liabilities=assets - equity,
                equity=equity,
                current_assets=current_revenue * (0.45 + 0.01 * index),
                current_liabilities=current_liabilities,
                cash=current_revenue * 0.12,
                short_term_investments=current_revenue * 0.05,
                inventory=current_revenue * 0.08,
                receivables=current_revenue * 0.11,
                ppe_gross=ppe_net * 1.8,
                ppe_net=ppe_net,
                goodwill=current_revenue * 0.10,
                intangibles=current_revenue * 0.04,
                retained_earnings=equity * 0.75,
                long_term_debt=long_term_debt,
                short_term_debt=current_revenue * 0.03,
                cfo=cfo,
                capex=capex,
                depreciation_amortization=depreciation,
                dividends_paid=dps * current_shares,
                buybacks=current_revenue * 0.04,
                dividends_per_share=dps,
            )
        )

        current_revenue *= 1.0 + revenue_growth
        current_shares *= 1.0 - share_buyback
        equity *= 1.06
        long_term_debt *= 0.97
        ppe_net *= 1.0 + revenue_growth * 0.8

    return rows


def value_trap(*, start_year: int = 2020, count: int = 6) -> list[FiscalYear]:
    """Statistically cheap, fundamentally deteriorating.

    Shrinking revenue, accruals running ahead of cash, rising leverage and a
    rising share count. Exists to confirm the gates reject a low P/E that is low
    for a reason.
    """
    rows: list[FiscalYear] = []
    revenue = 8_000e6
    shares = 500e6
    equity = 2_000e6
    debt = 4_500e6
    receivables = revenue * 0.12

    for index in range(count):
        year = start_year + index
        net_income = revenue * 0.04
        operating_income = revenue * 0.06
        # Cash conversion decays year over year: the accrual tell.
        cfo = net_income * (0.85 - index * 0.12)
        assets = revenue * 1.6
        receivables *= 1.18

        rows.append(
            FiscalYear(
                period_end=date(year, 12, 31),
                label=year,
                revenue=revenue,
                gross_profit=revenue * (0.30 - index * 0.015),
                operating_income=operating_income,
                pretax_income=operating_income - debt * 0.06,
                tax_expense=max(0.0, (operating_income - debt * 0.06) * 0.21),
                net_income=net_income,
                eps_diluted=net_income / shares,
                diluted_shares=shares,
                shares_outstanding=shares,
                interest_expense=debt * 0.06,
                sga=revenue * 0.20,
                assets=assets,
                liabilities=assets - equity,
                equity=equity,
                current_assets=revenue * 0.35,
                current_liabilities=revenue * 0.30,
                cash=revenue * 0.03,
                short_term_investments=0.0,
                inventory=revenue * 0.15,
                receivables=receivables,
                ppe_gross=revenue * 0.9,
                ppe_net=revenue * 0.5,
                goodwill=revenue * 0.25,
                intangibles=revenue * 0.08,
                retained_earnings=equity * 0.20,
                long_term_debt=debt,
                short_term_debt=revenue * 0.08,
                cfo=cfo,
                capex=revenue * 0.045,
                depreciation_amortization=revenue * 0.05,
                dividends_paid=0.0,
                buybacks=0.0,
                dividends_per_share=0.0,
            )
        )

        revenue *= 0.96
        shares *= 1.045
        equity *= 0.94
        debt *= 1.05

    return rows


# ---- offline pipeline harness ------------------------------------------

# Every FiscalYear field the fixture builder knows how to emit as XBRL.
_EMITTABLE_FIELDS = (
    "revenue", "gross_profit", "operating_income", "pretax_income",
    "tax_expense", "net_income", "eps_diluted", "diluted_shares",
    "interest_expense", "sga", "assets", "liabilities", "equity",
    "current_assets", "current_liabilities", "cash", "short_term_investments",
    "inventory", "receivables", "ppe_gross", "ppe_net", "goodwill",
    "intangibles", "retained_earnings", "long_term_debt", "short_term_debt",
    "shares_outstanding", "cfo", "capex", "depreciation_amortization",
    "dividends_paid", "buybacks", "dividends_per_share",
)


def facts_from_years(
    years: list[FiscalYear], shares: float, *, entity_name: str = "Testco Inc."
) -> dict[str, Any]:
    """Turn FiscalYear objects back into an EDGAR companyfacts document."""
    rows = []
    for year in years:
        row: dict[str, Any] = {"end": year.period_end.isoformat()}
        for name in _EMITTABLE_FIELDS:
            value = getattr(year, name)
            if value is not None:
                row[name] = value
        rows.append(row)
    return build_companyfacts(rows, entity_name=entity_name, dei_shares=shares)


@dataclass
class FixtureFiler:
    ticker: str
    cik: str
    facts: dict[str, Any]
    sic: str
    price: float
    name: str = ""


class FixtureHttpClient:
    """Serves fixture payloads for the exact URLs the pipeline requests.

    Stands in for `HttpClient` so the whole screen can run with no network at
    all: used by the tests and by `--offline` runs.
    """

    def __init__(self, filers: list[FixtureFiler]) -> None:
        self.filers = {f.ticker: f for f in filers}
        self.requested: list[str] = []

    def _filer_by_cik(self, url: str) -> FixtureFiler:
        for filer in self.filers.values():
            if filer.cik in url:
                return filer
        raise AssertionError(f"no fixture filer matches {url}")

    def get_json(self, url: str, **_kwargs: Any) -> Any:
        self.requested.append(url)
        if url == edgar.COMPANY_TICKERS_URL:
            return {
                str(index): {
                    "cik_str": int(filer.cik),
                    "ticker": filer.ticker,
                    "title": filer.name or filer.ticker,
                }
                for index, filer in enumerate(self.filers.values())
            }
        if "companyfacts" in url:
            return self._filer_by_cik(url).facts
        if "submissions" in url:
            filer = self._filer_by_cik(url)
            return {
                "name": filer.name or f"{filer.ticker} Inc.",
                "sic": filer.sic,
                "fiscalYearEnd": "1231",
            }
        if "finance.yahoo.com" in url:
            ticker = url.split("/chart/")[1].split("?")[0]
            return self._chart(self.filers[ticker].price)
        raise AssertionError(f"unexpected URL requested: {url}")

    def get_text(self, url: str, **_kwargs: Any) -> str:
        raise AssertionError(f"unexpected text fetch: {url}")

    @staticmethod
    def _chart(price: float, days: int = 400) -> dict[str, Any]:
        # A seeded random walk rather than a flat line, so realised volatility,
        # the 52-week range and drawdown are all exercised. Deterministic, and
        # rescaled to end exactly at `price` so assertions on the latest close
        # stay exact.
        end = datetime(2026, 8, 15, tzinfo=timezone.utc)
        rng = random.Random(20260815)
        daily_vol = 0.22 / math.sqrt(252)
        cumulative, total = [], 0.0
        for _ in range(days):
            total += rng.gauss(0.0, daily_vol)
            cumulative.append(total)
        final = cumulative[-1]
        closes = [price * math.exp(point - final) for point in cumulative]
        stamps = [
            int((end - timedelta(days=offset - 1)).timestamp())
            for offset in range(days, 0, -1)
        ]
        return {
            "chart": {
                "error": None,
                "result": [
                    {
                        "meta": {"regularMarketPrice": price},
                        "timestamp": stamps,
                        "indicators": {"adjclose": [{"adjclose": closes}]},
                    }
                ],
            }
        }


def demo_filers() -> list[FixtureFiler]:
    """A small synthetic universe with deliberately varied outcomes.

    Two names clear every gate at different discounts, one is a quality business
    priced too richly, and one is a value trap. Enough to exercise the whole
    report including the watchlist and the rejection reasons.

    Prices are set as multiples of each filer's final-year earnings so the
    resulting margins of safety land in a plausible range rather than the absurd
    discounts that arbitrary prices would produce.
    """
    cheap = steady_compounder(revenue=42_000e6, net_margin=0.21, shares=1_450e6)
    fair = steady_compounder(revenue=18_500e6, net_margin=0.16, shares=620e6)
    rich = steady_compounder(revenue=9_800e6, net_margin=0.19, shares=310e6)
    trap = value_trap()

    def price_at(years: list[FiscalYear], pe: float) -> float:
        eps = years[-1].eps_diluted or 1.0
        return round(eps * pe, 2)

    return [
        FixtureFiler(
            ticker="CMPD",
            cik="0000000101",
            name="Compounder Industries",
            facts=facts_from_years(cheap, 1_344e6, entity_name="Compounder Industries"),
            sic="3570",
            price=price_at(cheap, 7.0),
        ),
        FixtureFiler(
            ticker="STDY",
            cik="0000000102",
            name="Steady Consumer Co",
            facts=facts_from_years(fair, 575e6, entity_name="Steady Consumer Co"),
            sic="2000",
            price=price_at(fair, 8.5),
        ),
        FixtureFiler(
            ticker="PRCY",
            cik="0000000103",
            name="Pricey Growth Corp",
            facts=facts_from_years(rich, 287e6, entity_name="Pricey Growth Corp"),
            sic="3674",
            price=price_at(rich, 34.0),
        ),
        FixtureFiler(
            ticker="TRAP",
            cik="0000000104",
            name="Legacy Metals Group",
            facts=facts_from_years(trap, 623e6, entity_name="Legacy Metals Group"),
            sic="3310",
            # Priced high enough to clear the market-cap floor, so the demo shows
            # it rejected on business quality rather than on size.
            price=price_at(trap, 9.0),
        ),
    ]
