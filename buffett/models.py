"""Core data structures shared across the pipeline.

`FiscalYear` mirrors one audited annual period as reported in a 10-K. Every
field is optional because filers tag XBRL inconsistently: a bank has no
inventory, a software firm may not break out gross profit. The engine degrades
where a field is missing rather than substituting a guess.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date
from typing import Any

# Fields that must be present for a year to support the core analysis. Used to
# score data completeness so thin filers can be excluded honestly.
CRITICAL_FIELDS = (
    "revenue",
    "net_income",
    "assets",
    "equity",
    "cfo",
    "capex",
    "diluted_shares",
)


@dataclass
class FiscalYear:
    """One annual reporting period, as filed."""

    period_end: date
    label: int  # calendar year of period end; display only

    # Income statement
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    pretax_income: float | None = None
    tax_expense: float | None = None
    net_income: float | None = None
    eps_diluted: float | None = None
    diluted_shares: float | None = None
    interest_expense: float | None = None
    sga: float | None = None

    # Balance sheet (instant, at period end)
    assets: float | None = None
    liabilities: float | None = None
    equity: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    cash: float | None = None
    short_term_investments: float | None = None
    long_term_investments: float | None = None
    inventory: float | None = None
    receivables: float | None = None
    ppe_gross: float | None = None
    ppe_net: float | None = None
    goodwill: float | None = None
    intangibles: float | None = None
    retained_earnings: float | None = None
    long_term_debt: float | None = None
    short_term_debt: float | None = None
    shares_outstanding: float | None = None

    # Cash flow
    cfo: float | None = None
    capex: float | None = None
    depreciation_amortization: float | None = None
    dividends_paid: float | None = None
    buybacks: float | None = None
    dividends_per_share: float | None = None

    # ---- derived helpers ------------------------------------------------

    @property
    def total_debt(self) -> float | None:
        parts = [self.long_term_debt, self.short_term_debt]
        present = [p for p in parts if p is not None]
        return sum(present) if present else None

    @property
    def liquid_assets(self) -> float | None:
        """Cash plus marketable securities, added back to enterprise value."""
        parts = [self.cash, self.short_term_investments]
        present = [p for p in parts if p is not None]
        return sum(present) if present else None

    @property
    def net_cash(self) -> float | None:
        liquid, debt = self.liquid_assets, self.total_debt
        if liquid is None and debt is None:
            return None
        return (liquid or 0.0) - (debt or 0.0)

    @property
    def free_cash_flow(self) -> float | None:
        if self.cfo is None:
            return None
        # capex is reported as a positive outflow amount by EDGAR convention.
        return self.cfo - (self.capex or 0.0)

    @property
    def working_capital(self) -> float | None:
        if self.current_assets is None or self.current_liabilities is None:
            return None
        return self.current_assets - self.current_liabilities

    @property
    def tangible_equity(self) -> float | None:
        if self.equity is None:
            return None
        return self.equity - (self.goodwill or 0.0) - (self.intangibles or 0.0)

    @property
    def effective_tax_rate(self) -> float | None:
        if not self.pretax_income or self.tax_expense is None:
            return None
        if self.pretax_income <= 0:
            return None
        rate = self.tax_expense / self.pretax_income
        # Reject implausible one-off rates rather than propagating them.
        return rate if 0.0 <= rate <= 0.50 else None

    @property
    def ebit(self) -> float | None:
        """Operating income, falling back to pretax income plus interest."""
        if self.operating_income is not None:
            return self.operating_income
        if self.pretax_income is not None:
            return self.pretax_income + (self.interest_expense or 0.0)
        return None

    def completeness(self) -> float:
        present = sum(1 for name in CRITICAL_FIELDS if getattr(self, name) is not None)
        return present / len(CRITICAL_FIELDS)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["period_end"] = self.period_end.isoformat()
        return out


@dataclass
class PriceHistory:
    """Daily adjusted closes, oldest first."""

    dates: list[date] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)
    source: str = ""

    @property
    def last(self) -> float | None:
        return self.closes[-1] if self.closes else None

    @property
    def last_date(self) -> date | None:
        return self.dates[-1] if self.dates else None

    def close_on_or_before(self, target: date) -> float | None:
        """Closing price at `target`, or the most recent trading day before it."""
        chosen: float | None = None
        for when, close in zip(self.dates, self.closes):
            if when <= target:
                chosen = close
            else:
                break
        return chosen

    def window(self, days: int) -> list[float]:
        return self.closes[-days:] if days > 0 else []


@dataclass
class Company:
    """Everything known about one filer, assembled from EDGAR plus prices."""

    ticker: str
    cik: str
    name: str
    sic: str | None = None
    sector: str = "Unknown"
    years: list[FiscalYear] = field(default_factory=list)  # oldest first
    shares_outstanding: float | None = None
    prices: PriceHistory = field(default_factory=PriceHistory)
    fiscal_year_end: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def latest(self) -> FiscalYear | None:
        return self.years[-1] if self.years else None

    @property
    def price(self) -> float | None:
        return self.prices.last

    @property
    def market_cap(self) -> float | None:
        shares = self.shares_outstanding
        if shares is None and self.latest is not None:
            shares = self.latest.shares_outstanding or self.latest.diluted_shares
        if shares is None or self.price is None:
            return None
        return shares * self.price

    def recent(self, n: int) -> list[FiscalYear]:
        return self.years[-n:] if n > 0 else []

    def series(self, attr: str, n: int | None = None) -> list[float]:
        """Non-null values of one field, oldest first, optionally last n years."""
        rows = self.years if n is None else self.recent(n)
        out = []
        for row in rows:
            value = getattr(row, attr, None)
            if value is None and hasattr(FiscalYear, attr):
                value = getattr(row, attr)
            if value is not None:
                out.append(float(value))
        return out

    def completeness(self) -> float:
        if not self.years:
            return 0.0
        return sum(y.completeness() for y in self.years) / len(self.years)

    def add_note(self, note: str) -> None:
        if note not in self.notes:
            self.notes.append(note)


def field_names(cls: type) -> tuple[str, ...]:
    return tuple(f.name for f in fields(cls))
