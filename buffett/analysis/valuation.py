"""Intrinsic value, triangulated four ways, then margin of safety.

No single valuation method is trustworthy alone, so four run in parallel and the
spread between them becomes the confidence signal that later throttles position
size:

* Discounted owner earnings, Buffett's own measure from the 1986 letter:
  cash flow from operations less the capex actually needed to stand still.
* Earnings Power Value (Greenwald), which capitalises normalised operating
  profit and assumes zero growth. A deliberately unexciting floor.
* Graham's number, the defensive investor's ceiling on what earnings and book
  value together justify paying.
* A normalised multiple, using the filer's own long-run P/E capped at Graham's
  15x rather than whatever the market is paying this week.

Margin of safety is measured against the blend. Where the four disagree
violently, that is information, not noise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from ..config import ValuationConfig
from ..models import Company, FiscalYear
from ..sectors import fallback_pe, is_book_value_business
from .quality import QualityReport
from .stats import clamp, median, robust_growth, safe_div

# Owner earnings are averaged over this many recent years to damp one-off swings.
NORMALISATION_YEARS = 3

# The methods that genuinely try to estimate what the business is worth as a
# going concern. Confidence is measured across these only: Graham's number and
# book value are deliberately conservative floors, not competing central
# estimates, and mixing a floor into the dispersion calculation would peg every
# growing business at minimum confidence for structural rather than
# informational reasons.
CENTRAL_METHODS = ("dcf", "epv", "multiple")

# Altman zones in which the balance sheet, not earning power, is the relevant
# story. Only then does a liquidation-style floor belong in the bear case.
BALANCE_SHEET_RISK_ZONES = ("grey", "distress", "unknown")


@dataclass
class ValuationReport:
    price: float | None = None

    # Per-share estimates from each method.
    iv_dcf: float | None = None
    iv_epv: float | None = None
    iv_graham: float | None = None
    iv_multiple: float | None = None
    iv_book: float | None = None

    iv_base: float | None = None
    iv_bear: float | None = None
    iv_bull: float | None = None
    margin_of_safety: float | None = None
    upside: float | None = None
    confidence: float | None = None

    discount_rate: float | None = None
    growth_stage1: float | None = None
    terminal_growth: float | None = None
    owner_earnings_base: float | None = None
    owner_earnings_per_share: float | None = None
    owner_earnings_growth: float | None = None

    # Multiples, all trailing unless named otherwise.
    pe_trailing: float | None = None
    pe_normalized: float | None = None
    pe_hist_median: float | None = None
    pbv: float | None = None
    ptbv: float | None = None
    ps: float | None = None
    ev_ebit: float | None = None
    fcf_yield: float | None = None
    earnings_yield: float | None = None
    owner_earnings_yield: float | None = None
    dividend_yield: float | None = None

    methods_used: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add_note(self, note: str) -> None:
        if note not in self.notes:
            self.notes.append(note)


# ---- owner earnings ----------------------------------------------------


def maintenance_capex(
    year: FiscalYear, prev: FiscalYear | None, ppe_to_sales: float | None
) -> float | None:
    """Capex less the portion funding growth (Greenwald's decomposition).

    Growth capex is approximated as the PP&E intensity of the business applied
    to the revenue it added. What remains is what the business must spend to
    keep the lights on, which is the figure owner earnings should be charged.
    """
    if year.capex is None:
        return None
    if prev is None or ppe_to_sales is None or year.revenue is None or prev.revenue is None:
        return year.capex
    revenue_delta = year.revenue - prev.revenue
    if revenue_delta <= 0:
        # No growth to fund, so all of it is maintenance.
        return year.capex
    growth_capex = ppe_to_sales * revenue_delta
    return clamp(year.capex - growth_capex, 0.0, year.capex)


def owner_earnings_series(
    company: Company, years: list[FiscalYear], book_value_business: bool
) -> list[tuple[date, float]]:
    """Owner earnings per fiscal year, oldest first.

    For lenders and property owners, the capex-based construction is meaningless
    (their real reinvestment runs through the loan book, not PP&E), so reported
    net income stands in and the substitution is recorded as a note.
    """
    if book_value_business:
        return [
            (y.period_end, float(y.net_income))
            for y in years
            if y.net_income is not None
        ]

    intensities = [
        ratio
        for ratio in (safe_div(y.ppe_gross, y.revenue) for y in years)
        if ratio is not None
    ]
    ppe_to_sales = median(intensities)

    out: list[tuple[date, float]] = []
    for index, year in enumerate(years):
        prev = years[index - 1] if index > 0 else None
        if year.cfo is None:
            continue
        maint = maintenance_capex(year, prev, ppe_to_sales)
        if maint is None:
            continue
        out.append((year.period_end, year.cfo - maint))
    return out


# ---- discount rate -----------------------------------------------------


def discount_rate(
    cfg: ValuationConfig, volatility: float | None, quality: QualityReport
) -> float:
    """Risk-free plus an equity premium scaled by realised volatility.

    Buffett discounted at the long bond yield and demanded the margin of safety
    do the rest. This screener instead prices risk into the rate, because it
    must rank hundreds of names mechanically rather than underwrite one.
    """
    scalar = 1.0
    if volatility is not None and volatility > 0:
        # 20% annualised is treated as an unremarkable large-cap baseline.
        scalar = clamp(volatility / 0.20, 0.8, 1.6)

    penalty = 0.0
    if quality.piotroski_f is not None and quality.piotroski_f < 6:
        penalty += 0.01
    if quality.debt_to_equity is not None and quality.debt_to_equity > 1.0:
        penalty += 0.01
    if quality.altman_z is not None and quality.altman_z < 2.5:
        penalty += 0.01

    raw = cfg.risk_free_rate + cfg.equity_risk_premium * scalar + penalty
    return clamp(raw, cfg.discount_rate_floor, cfg.discount_rate_cap)


# ---- valuation methods -------------------------------------------------


def two_stage_dcf(
    base_owner_earnings: float,
    growth_stage1: float,
    terminal_growth: float,
    rate: float,
    years: int,
    net_cash: float | None,
    shares: float,
) -> float | None:
    """Present value of owner earnings with growth fading linearly to terminal.

    A flat high-growth stage followed by an abrupt drop to terminal produces a
    kink that flatters fast growers. Fading the rate year by year is both more
    realistic and more conservative.
    """
    if shares <= 0 or rate <= terminal_growth or base_owner_earnings <= 0:
        return None

    present_value = 0.0
    flow = base_owner_earnings
    for period in range(1, years + 1):
        # Linear fade from stage-one growth to terminal growth.
        fraction = (period - 1) / max(1, years - 1)
        growth = growth_stage1 + (terminal_growth - growth_stage1) * fraction
        flow *= 1.0 + growth
        present_value += flow / (1.0 + rate) ** period

    terminal_flow = flow * (1.0 + terminal_growth)
    terminal_value = terminal_flow / (rate - terminal_growth)
    present_value += terminal_value / (1.0 + rate) ** years

    equity_value = present_value + (net_cash or 0.0)
    if equity_value <= 0:
        return None
    return equity_value / shares


def earnings_power_value(
    years: list[FiscalYear],
    rate: float,
    net_cash: float | None,
    shares: float,
    fallback_tax_rate: float,
) -> float | None:
    """Normalised after-tax operating profit capitalised at the discount rate.

    Assumes zero growth on purpose: this is what the business is worth if it
    never expands again, which makes it a floor rather than a forecast.
    """
    if shares <= 0 or rate <= 0 or not years:
        return None
    latest = years[-1]
    margins = [
        m for m in (safe_div(y.operating_income, y.revenue) for y in years) if m is not None
    ]
    normalised_margin = median(margins)
    if normalised_margin is None or latest.revenue is None:
        return None
    normalised_ebit = normalised_margin * latest.revenue
    if normalised_ebit <= 0:
        return None

    tax_rates = [r for r in (y.effective_tax_rate for y in years) if r is not None]
    tax_rate = median(tax_rates)
    if tax_rate is None:
        tax_rate = fallback_tax_rate

    equity_value = normalised_ebit * (1 - tax_rate) / rate + (net_cash or 0.0)
    if equity_value <= 0:
        return None
    return equity_value / shares


def graham_number(eps: float | None, book_value_per_share: float | None) -> float | None:
    """sqrt(22.5 x EPS x BVPS): Graham's 15x earnings and 1.5x book, combined."""
    if eps is None or book_value_per_share is None:
        return None
    if eps <= 0 or book_value_per_share <= 0:
        return None
    return math.sqrt(22.5 * eps * book_value_per_share)


def historical_pe_median(
    years: list[FiscalYear], prices_at_year_end: dict[date, float]
) -> float | None:
    """The filer's own long-run multiple, which beats a sector average."""
    ratios: list[float] = []
    for year in years:
        price = prices_at_year_end.get(year.period_end)
        eps = year.eps_diluted
        if price is None or eps is None or eps <= 0:
            continue
        ratio = price / eps
        # Discard years where a collapsed earnings base produces a nonsense
        # multiple; those say nothing about normal valuation.
        if 3.0 <= ratio <= 60.0:
            ratios.append(ratio)
    return median(ratios)


def normalized_multiple_value(
    normalised_eps: float | None,
    hist_pe: float | None,
    sector: str,
    cap: float,
) -> tuple[float | None, str]:
    """Normalised EPS times a conservative multiple. Returns value and basis."""
    if normalised_eps is None or normalised_eps <= 0:
        return None, "unavailable"
    if hist_pe is not None:
        multiple = min(hist_pe, cap)
        basis = f"own 5y median P/E {hist_pe:.1f}x capped at {cap:.0f}x"
    else:
        multiple = min(fallback_pe(sector), cap)
        basis = f"{sector} long-run average multiple (no usable own history)"
    return normalised_eps * multiple, basis


# ---- assembly ----------------------------------------------------------


def value_company(
    company: Company,
    quality: QualityReport,
    cfg: ValuationConfig,
    lookback: int,
    volatility: float | None,
    prices_at_year_end: dict[date, float],
) -> ValuationReport:
    """Run every valuation method that the available data supports."""
    report = ValuationReport(price=company.price)
    years = company.recent(lookback)
    if not years or company.price is None or company.price <= 0:
        report.add_note("no price or no annual filings, cannot value")
        return report

    latest = years[-1]
    book_value_business = is_book_value_business(company.sector)
    shares = (
        company.shares_outstanding
        or latest.shares_outstanding
        or latest.diluted_shares
    )
    if not shares or shares <= 0:
        report.add_note("share count unavailable, cannot value per share")
        return report

    rate = discount_rate(cfg, volatility, quality)
    report.discount_rate = rate
    report.terminal_growth = cfg.terminal_growth

    # ---- owner earnings and the DCF
    oe_series = owner_earnings_series(company, years, book_value_business)
    if book_value_business:
        report.add_note(
            "lender or property owner: owner earnings proxied by net income, "
            "and book value carries more weight than the DCF"
        )
    oe_values = [value for _, value in oe_series]
    if oe_values:
        recent_oe = oe_values[-NORMALISATION_YEARS:]
        report.owner_earnings_base = median(recent_oe)
        report.owner_earnings_growth = robust_growth(oe_values)
        report.owner_earnings_per_share = safe_div(report.owner_earnings_base, shares)

    growth = report.owner_earnings_growth
    if growth is None:
        # Fall back to revenue growth, then to terminal growth, rather than
        # assuming an expansion rate the filings do not support.
        growth = quality.revenue_cagr
    if growth is None:
        growth = cfg.terminal_growth
        report.add_note("no usable growth history, DCF run at terminal growth")
    growth_stage1 = clamp(
        min(growth, cfg.growth_cap) * cfg.growth_haircut,
        cfg.growth_floor,
        cfg.growth_cap,
    )
    report.growth_stage1 = growth_stage1

    if report.owner_earnings_base and report.owner_earnings_base > 0:
        report.iv_dcf = two_stage_dcf(
            base_owner_earnings=report.owner_earnings_base,
            growth_stage1=growth_stage1,
            terminal_growth=cfg.terminal_growth,
            rate=rate,
            years=cfg.stage1_years,
            net_cash=latest.net_cash,
            shares=shares,
        )
    else:
        report.add_note("owner earnings not positive, DCF skipped")

    # ---- earnings power value
    report.iv_epv = earnings_power_value(
        years, rate, latest.net_cash, shares, cfg.fallback_tax_rate
    )

    # ---- Graham number and book value
    bvps = safe_div(latest.equity, shares)
    tbvps = safe_div(latest.tangible_equity, shares)
    eps_series = [y.eps_diluted for y in years if y.eps_diluted is not None]
    normalised_eps = median(eps_series[-NORMALISATION_YEARS:]) if eps_series else None
    report.iv_graham = graham_number(normalised_eps, bvps)
    report.iv_book = bvps

    # ---- normalised multiple
    report.pe_hist_median = historical_pe_median(years, prices_at_year_end)
    report.iv_multiple, multiple_basis = normalized_multiple_value(
        normalised_eps, report.pe_hist_median, company.sector, cfg.max_normalized_pe
    )
    if report.iv_multiple is not None:
        report.add_note(f"normalised multiple basis: {multiple_basis}")

    # ---- blend
    # A liquidation-style floor belongs in the bear case only when the balance
    # sheet is what the investment rests on. For an asset-light compounder,
    # tangible book is far below any price it will ever trade at, and treating
    # it as the downside would price in a permanent loss the business is not
    # actually exposed to.
    use_liquidation_floor = book_value_business or (
        quality.altman_zone in BALANCE_SHEET_RISK_ZONES
    )
    _blend(report, cfg, book_value_business, tbvps, use_liquidation_floor)

    # ---- observed multiples
    _fill_multiples(report, company, latest, shares, normalised_eps, bvps, tbvps, quality)

    return report


def _blend(
    report: ValuationReport,
    cfg: ValuationConfig,
    book_value_business: bool,
    tangible_bvps: float | None,
    use_liquidation_floor: bool,
) -> None:
    """Weighted blend of available estimates, renormalised over what exists."""
    weights = {
        "dcf": (report.iv_dcf, cfg.weight_dcf),
        "epv": (report.iv_epv, cfg.weight_epv),
        "multiple": (report.iv_multiple, cfg.weight_multiple),
        "graham": (report.iv_graham, cfg.weight_graham),
    }
    if book_value_business:
        # Shift weight out of the DCF, which does not describe a balance-sheet
        # business, and into the measures that do.
        weights["dcf"] = (report.iv_dcf, cfg.weight_dcf * 0.35)
        weights["graham"] = (report.iv_graham, cfg.weight_graham + cfg.weight_dcf * 0.40)
        weights["multiple"] = (
            report.iv_multiple,
            cfg.weight_multiple + cfg.weight_dcf * 0.25,
        )

    available = {
        name: (value, weight)
        for name, (value, weight) in weights.items()
        if value is not None and value > 0 and weight > 0
    }
    if not available:
        report.add_note("no valuation method produced a usable figure")
        return

    total_weight = sum(weight for _, weight in available.values())
    report.iv_base = sum(
        value * weight for value, weight in available.values()
    ) / total_weight
    report.methods_used = sorted(available)

    estimates = [value for value, _ in available.values()]
    report.iv_bull = max(estimates)

    # The bear case is the lowest defensible going-concern floor: the most
    # pessimistic method that still produced a number. Tangible book joins the
    # candidates only when the balance sheet is the relevant story, since an
    # asset-light business trades permanently and legitimately above it.
    floors = list(estimates)
    if use_liquidation_floor and tangible_bvps is not None and tangible_bvps > 0:
        floors.append(tangible_bvps)
        report.add_note(
            "tangible book value included in the bear case, because this is a "
            "balance-sheet business or its Altman score is not in the safe zone"
        )
    report.iv_bear = min(floors)

    central = [
        value
        for name, (value, _) in available.items()
        if name in CENTRAL_METHODS
    ]
    if len(central) >= 2:
        centre = median(central)
        spread = (max(central) - min(central)) / centre if centre else None
        if spread is not None:
            # Wide disagreement between the going-concern methods means the
            # valuation is a guess dressed as a number, and Kelly sizes it down.
            report.confidence = round(clamp(1.0 - spread / 1.5, 0.2, 1.0), 3)
    else:
        report.confidence = 0.4
        report.add_note(
            "fewer than two going-concern valuation methods available, "
            "confidence capped"
        )

    if report.price and report.iv_base and report.iv_base > 0:
        report.margin_of_safety = (report.iv_base - report.price) / report.iv_base
        report.upside = report.iv_base / report.price - 1.0


def _fill_multiples(
    report: ValuationReport,
    company: Company,
    latest: FiscalYear,
    shares: float,
    normalised_eps: float | None,
    bvps: float | None,
    tbvps: float | None,
    quality: QualityReport,
) -> None:
    price = report.price
    if price is None:
        return
    market_cap = company.market_cap

    if latest.eps_diluted and latest.eps_diluted > 0:
        report.pe_trailing = price / latest.eps_diluted
        report.earnings_yield = latest.eps_diluted / price
    if normalised_eps and normalised_eps > 0:
        report.pe_normalized = price / normalised_eps
    if bvps and bvps > 0:
        report.pbv = price / bvps
    if tbvps and tbvps > 0:
        report.ptbv = price / tbvps
    if market_cap and latest.revenue:
        report.ps = market_cap / latest.revenue

    if market_cap is not None:
        enterprise_value = market_cap + (latest.total_debt or 0.0) - (
            latest.liquid_assets or 0.0
        )
        if latest.ebit and latest.ebit > 0 and enterprise_value > 0:
            report.ev_ebit = enterprise_value / latest.ebit

    fcf = latest.free_cash_flow
    if fcf is not None and market_cap:
        report.fcf_yield = fcf / market_cap
    if report.owner_earnings_per_share is not None and price > 0:
        report.owner_earnings_yield = report.owner_earnings_per_share / price
    report.dividend_yield = quality.dividend.yield_pct
