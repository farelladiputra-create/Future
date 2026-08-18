"""Business quality: the part Buffett cares about before he looks at price.

Three published forensic scores do most of the work here:

* Piotroski F-Score (2000) grades nine fundamental signals of improving
  financial strength, 0 to 9.
* Altman Z-Score (1968) estimates distance from bankruptcy.
* Beneish M-Score (1999) flags the accounting profile typical of earnings
  manipulation. A high M is a walk-away, not a discount.

On top of those sit the durability measures: return on invested capital, how
steady that return has been, and whether the share count is quietly rising.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Company, FiscalYear
from .stats import (
    clamp,
    coefficient_of_variation,
    count_positive,
    mean,
    robust_growth,
    safe_div,
    trend_slope,
)

# Altman zones for a listed company.
ALTMAN_DISTRESS = 1.81
ALTMAN_SAFE = 2.99
# Above this, Beneish's model classes a filer with the manipulator profile.
BENEISH_THRESHOLD = -1.78
# Piotroski signals needed before the score is treated as decision-grade.
MIN_PIOTROSKI_SIGNALS = 7
# Beneish terms needed from real data before the M-score is trusted.
MIN_BENEISH_TERMS = 6


@dataclass
class DividendProfile:
    yield_pct: float | None = None
    payout_ratio: float | None = None
    dps_latest: float | None = None
    paying_years: int = 0
    growth_years: int = 0
    dps_cagr: float | None = None
    covered_by_fcf: bool | None = None


@dataclass
class QualityReport:
    piotroski_f: int | None = None
    piotroski_signals: dict[str, bool | None] = field(default_factory=dict)
    piotroski_reliable: bool = False
    altman_z: float | None = None
    altman_zone: str = "unknown"
    beneish_m: float | None = None
    beneish_reliable: bool = False
    beneish_flag: bool | None = None

    avg_roe: float | None = None
    avg_roic: float | None = None
    roic_latest: float | None = None
    roe_stability: float | None = None
    gross_margin_latest: float | None = None
    gross_margin_trend: float | None = None
    operating_margin_latest: float | None = None

    debt_to_equity: float | None = None
    net_debt_to_ebit: float | None = None
    interest_coverage: float | None = None
    current_ratio: float | None = None

    positive_earnings_years: int = 0
    positive_fcf_years: int = 0
    years_available: int = 0
    revenue_cagr: float | None = None
    eps_cagr: float | None = None
    share_count_cagr: float | None = None

    dividend: DividendProfile = field(default_factory=DividendProfile)
    score: float = 0.0
    flags: list[str] = field(default_factory=list)

    def add_flag(self, message: str) -> None:
        if message not in self.flags:
            self.flags.append(message)


# ---- forensic scores ---------------------------------------------------


def piotroski_f_score(
    curr: FiscalYear, prev: FiscalYear, prior_assets: float | None = None
) -> tuple[int | None, dict[str, bool | None]]:
    """Nine-point F-Score. Signals that cannot be computed come back as None."""
    signals: dict[str, bool | None] = {}

    avg_assets_curr = _average_assets(curr.assets, prev.assets)
    avg_assets_prev = _average_assets(prev.assets, prior_assets)
    roa_curr = safe_div(curr.net_income, avg_assets_curr)
    roa_prev = safe_div(prev.net_income, avg_assets_prev)

    signals["roa_positive"] = None if roa_curr is None else roa_curr > 0
    signals["cfo_positive"] = None if curr.cfo is None else curr.cfo > 0
    signals["roa_improving"] = (
        None if roa_curr is None or roa_prev is None else roa_curr > roa_prev
    )
    signals["cfo_exceeds_income"] = (
        None
        if curr.cfo is None or curr.net_income is None
        else curr.cfo > curr.net_income
    )

    lev_curr = safe_div(curr.long_term_debt, curr.assets)
    lev_prev = safe_div(prev.long_term_debt, prev.assets)
    signals["leverage_falling"] = (
        None if lev_curr is None or lev_prev is None else lev_curr <= lev_prev
    )

    cr_curr = safe_div(curr.current_assets, curr.current_liabilities)
    cr_prev = safe_div(prev.current_assets, prev.current_liabilities)
    signals["liquidity_improving"] = (
        None if cr_curr is None or cr_prev is None else cr_curr > cr_prev
    )

    shares_curr = curr.shares_outstanding or curr.diluted_shares
    shares_prev = prev.shares_outstanding or prev.diluted_shares
    signals["no_dilution"] = (
        None
        if shares_curr is None or shares_prev is None
        else shares_curr <= shares_prev * 1.001
    )

    gm_curr = safe_div(curr.gross_profit, curr.revenue)
    gm_prev = safe_div(prev.gross_profit, prev.revenue)
    signals["margin_improving"] = (
        None if gm_curr is None or gm_prev is None else gm_curr > gm_prev
    )

    turnover_curr = safe_div(curr.revenue, avg_assets_curr)
    turnover_prev = safe_div(prev.revenue, avg_assets_prev)
    signals["turnover_improving"] = (
        None
        if turnover_curr is None or turnover_prev is None
        else turnover_curr > turnover_prev
    )

    available = [v for v in signals.values() if v is not None]
    if not available:
        return None, signals
    return sum(1 for v in available if v), signals


def _average_assets(current: float | None, prior: float | None) -> float | None:
    if current is None:
        return None
    if prior is None:
        return current
    return (current + prior) / 2


def altman_z_score(year: FiscalYear, market_cap: float | None) -> float | None:
    """Classic five-factor Z for a listed company."""
    assets = year.assets
    if not assets or assets <= 0:
        return None
    x1 = safe_div(year.working_capital, assets)
    x2 = safe_div(year.retained_earnings, assets)
    x3 = safe_div(year.ebit, assets)
    x4 = safe_div(market_cap, year.liabilities)
    x5 = safe_div(year.revenue, assets)
    if None in (x1, x2, x3, x4, x5):
        return None
    return 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5


def altman_zone(z: float | None) -> str:
    if z is None:
        return "unknown"
    if z >= ALTMAN_SAFE:
        return "safe"
    if z >= ALTMAN_DISTRESS:
        return "grey"
    return "distress"


def beneish_m_score(
    curr: FiscalYear, prev: FiscalYear
) -> tuple[float | None, int]:
    """Eight-variable M-Score. Returns the score and how many terms were real.

    Index terms default to 1.0 (neutral) and the accrual term to 0.0 when the
    underlying tags are missing, which is the conventional treatment. The count
    of real terms is returned so a score built mostly on defaults can be
    discarded rather than acted on.
    """
    real = 0

    def index(curr_ratio: float | None, prev_ratio: float | None, invert: bool = False) -> float:
        nonlocal real
        if curr_ratio is None or prev_ratio is None:
            return 1.0
        numerator, denominator = (prev_ratio, curr_ratio) if invert else (curr_ratio, prev_ratio)
        if denominator == 0:
            return 1.0
        real += 1
        # Extreme index values usually mean a restated or tiny denominator
        # rather than fraud at that magnitude; cap so one term cannot dominate.
        return clamp(numerator / denominator, 0.1, 10.0)

    dsri = index(
        safe_div(curr.receivables, curr.revenue), safe_div(prev.receivables, prev.revenue)
    )
    gmi = index(
        safe_div(curr.gross_profit, curr.revenue),
        safe_div(prev.gross_profit, prev.revenue),
        invert=True,
    )
    aqi = index(_asset_quality(curr), _asset_quality(prev))
    sgi = index(curr.revenue, prev.revenue)
    depi = index(_depreciation_rate(curr), _depreciation_rate(prev), invert=True)
    sgai = index(safe_div(curr.sga, curr.revenue), safe_div(prev.sga, prev.revenue))
    lvgi = index(_leverage_ratio(curr), _leverage_ratio(prev))

    tata = 0.0
    if curr.net_income is not None and curr.cfo is not None and curr.assets:
        tata = clamp((curr.net_income - curr.cfo) / curr.assets, -1.0, 1.0)
        real += 1

    score = (
        -4.84
        + 0.920 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        + 4.679 * tata
        - 0.327 * lvgi
    )
    return score, real


def _asset_quality(year: FiscalYear) -> float | None:
    """Share of assets that are neither current nor hard property."""
    if not year.assets or year.current_assets is None or year.ppe_net is None:
        return None
    return 1.0 - (year.current_assets + year.ppe_net) / year.assets


def _depreciation_rate(year: FiscalYear) -> float | None:
    dep, ppe = year.depreciation_amortization, year.ppe_net
    if dep is None or ppe is None:
        return None
    denominator = dep + ppe
    if denominator == 0:
        return None
    return dep / denominator


def _leverage_ratio(year: FiscalYear) -> float | None:
    if not year.assets:
        return None
    parts = [year.long_term_debt, year.current_liabilities]
    present = [p for p in parts if p is not None]
    if not present:
        return None
    return sum(present) / year.assets


# ---- returns on capital ------------------------------------------------


def invested_capital(year: FiscalYear) -> float | None:
    """Debt plus equity less idle cash: the capital the business actually uses."""
    if year.equity is None:
        return None
    gross = year.equity + (year.total_debt or 0.0)
    excluding_cash = gross - (year.liquid_assets or 0.0)
    if excluding_cash > 0:
        return excluding_cash
    return gross if gross > 0 else None


def roic(year: FiscalYear, fallback_tax_rate: float) -> float | None:
    """After-tax return on invested capital."""
    ebit = year.ebit
    capital = invested_capital(year)
    if ebit is None or capital is None or capital <= 0:
        return None
    tax_rate = year.effective_tax_rate
    if tax_rate is None:
        tax_rate = fallback_tax_rate
    return ebit * (1 - tax_rate) / capital


def roe(year: FiscalYear) -> float | None:
    if year.equity is None or year.equity <= 0:
        return None
    return safe_div(year.net_income, year.equity)


# ---- assembly ----------------------------------------------------------


def dividend_profile(company: Company, years: list[FiscalYear]) -> DividendProfile:
    profile = DividendProfile()
    latest = years[-1]
    price = company.price

    dps_series = [y.dividends_per_share for y in years if y.dividends_per_share is not None]
    profile.dps_latest = latest.dividends_per_share

    if profile.dps_latest is not None and price:
        profile.yield_pct = profile.dps_latest / price
    elif latest.dividends_paid and company.market_cap:
        # Fall back to total cash paid over market cap when per-share is untagged.
        profile.yield_pct = latest.dividends_paid / company.market_cap

    if profile.dps_latest is not None and latest.eps_diluted and latest.eps_diluted > 0:
        profile.payout_ratio = profile.dps_latest / latest.eps_diluted
    elif latest.dividends_paid and latest.net_income and latest.net_income > 0:
        profile.payout_ratio = latest.dividends_paid / latest.net_income

    # Consecutive paying years, counted backwards from the most recent.
    for year in reversed(years):
        paid = year.dividends_per_share or year.dividends_paid
        if paid and paid > 0:
            profile.paying_years += 1
        else:
            break

    # Consecutive years of increases, again counted backwards from the latest.
    for later, earlier in zip(reversed(dps_series[1:]), reversed(dps_series[:-1])):
        if later > earlier:
            profile.growth_years += 1
        else:
            break

    if len(dps_series) >= 3:
        profile.dps_cagr = robust_growth(dps_series)

    fcf = latest.free_cash_flow
    if latest.dividends_paid is not None and fcf is not None:
        profile.covered_by_fcf = fcf >= latest.dividends_paid

    return profile


def assess_quality(
    company: Company, lookback: int, fallback_tax_rate: float
) -> QualityReport:
    """Build the full quality picture from the audited history."""
    report = QualityReport()
    years = company.recent(lookback)
    report.years_available = len(years)
    if not years:
        report.add_flag("no annual filings parsed")
        return report

    latest = years[-1]

    roe_series = [v for v in (roe(y) for y in years) if v is not None]
    roic_series = [v for v in (roic(y, fallback_tax_rate) for y in years) if v is not None]
    report.avg_roe = mean(roe_series)
    report.avg_roic = mean(roic_series)
    report.roic_latest = roic(latest, fallback_tax_rate)
    report.roe_stability = coefficient_of_variation(roe_series)

    gm_series = [
        v for v in (safe_div(y.gross_profit, y.revenue) for y in years) if v is not None
    ]
    report.gross_margin_latest = gm_series[-1] if gm_series else None
    report.gross_margin_trend = trend_slope(gm_series)
    report.operating_margin_latest = safe_div(latest.operating_income, latest.revenue)

    report.debt_to_equity = safe_div(latest.total_debt, latest.equity)
    report.current_ratio = safe_div(latest.current_assets, latest.current_liabilities)
    if latest.interest_expense and latest.interest_expense > 0:
        report.interest_coverage = safe_div(latest.ebit, latest.interest_expense)
    elif latest.ebit is not None:
        # No interest expense tagged means no meaningful debt service burden.
        report.interest_coverage = float("inf")
    net_debt = -(latest.net_cash) if latest.net_cash is not None else None
    if net_debt is not None and net_debt > 0:
        report.net_debt_to_ebit = safe_div(net_debt, latest.ebit)
    elif net_debt is not None:
        report.net_debt_to_ebit = 0.0

    report.positive_earnings_years = count_positive(
        [y.net_income for y in years if y.net_income is not None]
    )
    report.positive_fcf_years = count_positive(
        [y.free_cash_flow for y in years if y.free_cash_flow is not None]
    )

    revenue_series = [y.revenue for y in years if y.revenue is not None]
    eps_series = [y.eps_diluted for y in years if y.eps_diluted is not None]
    share_series = [
        y.diluted_shares for y in years if y.diluted_shares is not None
    ]
    report.revenue_cagr = robust_growth(revenue_series)
    report.eps_cagr = robust_growth(eps_series)
    report.share_count_cagr = robust_growth(share_series)

    if len(years) >= 2:
        prior_assets = years[-3].assets if len(years) >= 3 else None
        score, signals = piotroski_f_score(latest, years[-2], prior_assets)
        report.piotroski_f = score
        report.piotroski_signals = signals
        report.piotroski_reliable = (
            len([v for v in signals.values() if v is not None]) >= MIN_PIOTROSKI_SIGNALS
        )
        m_score, real_terms = beneish_m_score(latest, years[-2])
        report.beneish_reliable = real_terms >= MIN_BENEISH_TERMS
        report.beneish_m = m_score
        if report.beneish_reliable:
            report.beneish_flag = m_score > BENEISH_THRESHOLD
    else:
        report.add_flag("only one annual period parsed, trend signals unavailable")

    report.altman_z = altman_z_score(latest, company.market_cap)
    report.altman_zone = altman_zone(report.altman_z)
    report.dividend = dividend_profile(company, years)

    _raise_flags(report, latest)
    report.score = quality_score(report)
    return report


def _raise_flags(report: QualityReport, latest: FiscalYear) -> None:
    if report.beneish_flag:
        report.add_flag(
            f"Beneish M {report.beneish_m:.2f} above {BENEISH_THRESHOLD}: "
            "accrual profile resembles earnings manipulation"
        )
    if report.altman_zone == "distress":
        report.add_flag(f"Altman Z {report.altman_z:.2f} in the distress zone")
    if report.share_count_cagr is not None and report.share_count_cagr > 0.02:
        report.add_flag(
            f"diluted share count compounding {report.share_count_cagr * 100:.1f}% a year"
        )
    if report.debt_to_equity is not None and report.debt_to_equity > 2.0:
        report.add_flag(f"debt to equity {report.debt_to_equity:.2f}")
    if (
        report.dividend.payout_ratio is not None
        and report.dividend.payout_ratio > 0.9
    ):
        report.add_flag(
            f"payout ratio {report.dividend.payout_ratio * 100:.0f}% leaves no retained earnings"
        )
    if report.dividend.covered_by_fcf is False:
        report.add_flag("dividend exceeded free cash flow in the latest year")
    if latest.cfo is not None and latest.net_income is not None and latest.net_income > 0:
        if latest.cfo < latest.net_income * 0.7:
            report.add_flag(
                "operating cash flow well below reported net income: check accruals"
            )
    if report.roe_stability is not None and report.roe_stability > 0.6:
        report.add_flag("return on equity has been erratic across the cycle")


def quality_score(report: QualityReport) -> float:
    """Composite 0 to 100. Weights follow what actually protects capital.

    Balance sheet strength and accounting integrity together outweigh raw
    profitability, because the failure mode being avoided is permanent loss
    rather than a mediocre return.
    """
    total = 0.0

    # Piotroski, 25 points.
    if report.piotroski_f is not None:
        total += (report.piotroski_f / 9.0) * 25.0

    # Return on invested capital, 20 points, saturating at 25%.
    if report.avg_roic is not None:
        total += clamp(report.avg_roic / 0.25, 0.0, 1.0) * 20.0

    # Consistency of return on equity, 15 points. Lower variation scores higher.
    if report.roe_stability is not None:
        total += clamp(1.0 - report.roe_stability / 0.8, 0.0, 1.0) * 15.0
    elif report.avg_roe is not None:
        total += 7.5

    # Balance sheet, 20 points, split across leverage, coverage and Altman.
    balance = 0.0
    if report.debt_to_equity is not None:
        balance += clamp(1.0 - report.debt_to_equity / 2.0, 0.0, 1.0) * 8.0
    if report.interest_coverage is not None:
        coverage = 1.0 if report.interest_coverage == float("inf") else clamp(
            report.interest_coverage / 15.0, 0.0, 1.0
        )
        balance += coverage * 6.0
    if report.altman_z is not None:
        balance += clamp((report.altman_z - 1.0) / 3.0, 0.0, 1.0) * 6.0
    total += balance

    # Earning power consistency, 12 points.
    if report.years_available:
        earnings_ratio = report.positive_earnings_years / report.years_available
        fcf_ratio = report.positive_fcf_years / report.years_available
        total += (earnings_ratio * 0.6 + fcf_ratio * 0.4) * 12.0

    # Accounting integrity and shareholder treatment, 8 points.
    integrity = 8.0
    if report.beneish_flag:
        integrity -= 5.0
    if report.share_count_cagr is not None and report.share_count_cagr > 0.01:
        integrity -= 3.0
    elif report.share_count_cagr is not None and report.share_count_cagr < -0.005:
        # Steady buybacks at sensible prices are a genuine return of capital.
        integrity = 8.0
    total += max(0.0, integrity)

    return round(clamp(total, 0.0, 100.0), 1)
