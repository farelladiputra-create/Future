"""The screen: fetch, gate, value, size, rank.

Gates come before valuation in importance even though they run alongside it. A
name that fails a gate is never recommended at any price, because the whole
point of the exercise is avoiding permanent loss rather than finding the largest
discount. A cheap business with deteriorating accounts is not an opportunity.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date

from ..config import Config
from ..data import edgar, prices as price_data
from ..models import Company
from ..net import FetchError, HttpClient
from ..sectors import is_book_value_business
from .kelly import SizingReport, apply_portfolio_limits, size_position
from .quality import QualityReport, assess_quality
from .stats import clamp
from .valuation import ValuationReport, value_company

log = logging.getLogger(__name__)


@dataclass
class GateResult:
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    waived: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.passed = False
        if reason not in self.failures:
            self.failures.append(reason)

    def waive(self, reason: str) -> None:
        if reason not in self.waived:
            self.waived.append(reason)


@dataclass
class PriceStats:
    volatility: float | None = None
    drawdown_from_high: float | None = None
    week52_low: float | None = None
    week52_high: float | None = None
    return_1y: float | None = None
    as_of: date | None = None
    source: str = ""


@dataclass
class Candidate:
    company: Company
    quality: QualityReport
    valuation: ValuationReport
    sizing: SizingReport
    gate: GateResult
    price_stats: PriceStats
    rank_score: float = 0.0

    @property
    def ticker(self) -> str:
        return self.company.ticker

    @property
    def sector(self) -> str:
        return self.company.sector


@dataclass
class ScreenResult:
    run_date: date
    universe_size: int
    analysed: int
    candidates: list[Candidate] = field(default_factory=list)  # passed gates, ranked
    rejected: list[Candidate] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    portfolio_messages: list[str] = field(default_factory=list)
    price_as_of: date | None = None


# ---- gates -------------------------------------------------------------


def apply_gates(
    company: Company,
    quality: QualityReport,
    valuation: ValuationReport,
    cfg: Config,
) -> GateResult:
    """Hard quality and valuation filters. Missing data fails, it does not pass."""
    gate = GateResult()
    gates_cfg, val_cfg, uni_cfg = cfg.gates, cfg.valuation, cfg.universe
    book_business = is_book_value_business(company.sector)

    if company.sector in set(uni_cfg.exclude_sectors):
        gate.fail(f"{company.sector} is outside the configured circle of competence")

    market_cap = company.market_cap
    if market_cap is None:
        gate.fail("market capitalisation could not be determined")
    elif market_cap < uni_cfg.min_market_cap_usd:
        gate.fail(
            f"market cap ${market_cap / 1e9:.2f}B below the "
            f"${uni_cfg.min_market_cap_usd / 1e9:.1f}B floor"
        )

    completeness = company.completeness()
    if completeness < gates_cfg.min_data_completeness:
        gate.fail(
            f"only {completeness * 100:.0f}% of key line items parsed from filings"
        )

    if quality.years_available < gates_cfg.min_years_history:
        gate.fail(
            f"{quality.years_available} annual periods on file, "
            f"{gates_cfg.min_years_history} required"
        )

    if quality.positive_earnings_years < gates_cfg.min_positive_earnings_years:
        gate.fail(
            f"profitable in {quality.positive_earnings_years} of "
            f"{quality.years_available} years"
        )
    if quality.positive_fcf_years < gates_cfg.min_positive_fcf_years:
        gate.fail(
            f"positive free cash flow in {quality.positive_fcf_years} of "
            f"{quality.years_available} years"
        )

    _gate_min(gate, "average return on equity", quality.avg_roe, gates_cfg.min_avg_roe, pct=True)
    _gate_min(
        gate, "average return on invested capital", quality.avg_roic, gates_cfg.min_avg_roic, pct=True
    )

    if book_business:
        # Altman Z, interest coverage and debt to equity were calibrated on
        # operating companies. For a bank, borrowing is the product.
        gate.waive("leverage and Altman gates waived for a balance-sheet business")
    else:
        _gate_max(
            gate, "debt to equity", quality.debt_to_equity, gates_cfg.max_debt_to_equity
        )
        _gate_min(
            gate,
            "interest coverage",
            quality.interest_coverage,
            gates_cfg.min_interest_coverage,
        )
        _gate_min(gate, "Altman Z", quality.altman_z, gates_cfg.min_altman_z)

    if quality.piotroski_f is None:
        gate.fail("Piotroski F-Score could not be computed")
    elif quality.piotroski_f < gates_cfg.min_piotroski_f:
        gate.fail(f"Piotroski F {quality.piotroski_f} of 9")

    if quality.beneish_reliable and quality.beneish_m is not None:
        if quality.beneish_m > gates_cfg.max_beneish_m:
            gate.fail(
                f"Beneish M {quality.beneish_m:.2f} above {gates_cfg.max_beneish_m}"
            )
    else:
        gate.waive("Beneish M-Score not decision-grade, too many terms untagged")

    if quality.share_count_cagr is not None:
        if quality.share_count_cagr > gates_cfg.max_share_growth:
            gate.fail(
                f"share count compounding {quality.share_count_cagr * 100:.1f}% a year"
            )

    if valuation.margin_of_safety is None:
        gate.fail("no intrinsic value estimate, margin of safety unknown")
    elif valuation.margin_of_safety < val_cfg.min_margin_of_safety:
        gate.fail(
            f"margin of safety {valuation.margin_of_safety * 100:.1f}% below the "
            f"{val_cfg.min_margin_of_safety * 100:.0f}% threshold"
        )

    return gate


def _gate_min(
    gate: GateResult, label: str, value: float | None, floor: float, pct: bool = False
) -> None:
    if value is None:
        gate.fail(f"{label} unavailable")
        return
    if value < floor:
        shown = f"{value * 100:.1f}%" if pct else f"{value:.2f}"
        limit = f"{floor * 100:.1f}%" if pct else f"{floor:.2f}"
        gate.fail(f"{label} {shown} below {limit}")


def _gate_max(gate: GateResult, label: str, value: float | None, ceiling: float) -> None:
    if value is None:
        gate.fail(f"{label} unavailable")
        return
    if value > ceiling:
        gate.fail(f"{label} {value:.2f} above {ceiling:.2f}")


# ---- ranking -----------------------------------------------------------


def rank_score(candidate: Candidate, cfg: Config) -> float:
    """Composite 0 to 100 combining cheapness, quality, certainty and income."""
    rank_cfg = cfg.rank
    valuation, quality = candidate.valuation, candidate.quality
    total = 0.0

    if valuation.margin_of_safety is not None:
        component = clamp(valuation.margin_of_safety / rank_cfg.mos_saturation, 0.0, 1.0)
        total += component * rank_cfg.weight_margin_of_safety

    total += clamp(quality.score / 100.0, 0.0, 1.0) * rank_cfg.weight_quality

    confidence = valuation.confidence if valuation.confidence is not None else 0.4
    total += clamp(confidence, 0.0, 1.0) * rank_cfg.weight_confidence

    # Dividend credit blends current yield with the length of the paying record,
    # so a fresh 4% yield does not outrank two decades of increases.
    dividend = quality.dividend
    income = 0.0
    if dividend.yield_pct is not None:
        income += clamp(dividend.yield_pct / rank_cfg.dividend_saturation, 0.0, 1.0) * 0.7
    if dividend.paying_years:
        income += clamp(dividend.paying_years / 15.0, 0.0, 1.0) * 0.3
    total += clamp(income, 0.0, 1.0) * rank_cfg.weight_dividend

    return round(total, 2)


# ---- pipeline ----------------------------------------------------------


def compute_price_stats(company: Company) -> PriceStats:
    stats = PriceStats(source=company.prices.source, as_of=company.prices.last_date)
    closes = company.prices.closes
    if not closes:
        return stats
    stats.volatility = price_data.annualized_volatility(closes)
    stats.drawdown_from_high = price_data.drawdown_from_high(
        company.prices.window(price_data.TRADING_DAYS_PER_YEAR)
    )
    window = price_data.fifty_two_week_range(company.prices)
    if window:
        stats.week52_low, stats.week52_high = window
    stats.return_1y = price_data.total_return(
        company.prices.window(price_data.TRADING_DAYS_PER_YEAR)
    )
    return stats


def analyse_one(
    client: HttpClient, ticker: str, cik: str, cfg: Config, today: date
) -> Candidate:
    """Fetch and fully analyse one filer."""
    company = edgar.fetch_company(client, ticker, cik)
    try:
        company.prices = price_data.fetch_prices(
            client, ticker, cfg.data.price_history_days
        )
    except FetchError as exc:
        company.add_note(f"price history unavailable: {exc}")

    lookback = max(cfg.gates.min_years_history, 5)
    quality = assess_quality(company, lookback, cfg.valuation.fallback_tax_rate)
    stats = compute_price_stats(company)

    year_ends = [year.period_end for year in company.recent(lookback)]
    year_end_prices = price_data.price_at_fiscal_year_ends(company.prices, year_ends)

    valuation = value_company(
        company, quality, cfg.valuation, lookback, stats.volatility, year_end_prices
    )
    gate = apply_gates(company, quality, valuation, cfg)
    sizing = size_position(
        valuation, quality, cfg.kelly, cfg.portfolio, cfg.tranches, today
    )

    candidate = Candidate(
        company=company,
        quality=quality,
        valuation=valuation,
        sizing=sizing,
        gate=gate,
        price_stats=stats,
    )
    candidate.rank_score = rank_score(candidate, cfg)
    return candidate


def run_screen(
    client: HttpClient, cfg: Config, tickers: list[str], today: date | None = None
) -> ScreenResult:
    """Screen the universe concurrently and rank what survives."""
    today = today or date.today()
    ticker_map = edgar.load_ticker_map(client)
    result = ScreenResult(run_date=today, universe_size=len(tickers), analysed=0)

    resolved: list[tuple[str, str]] = []
    for ticker in tickers:
        cik = ticker_map.get(ticker) or ticker_map.get(ticker.replace("-", "."))
        if cik is None:
            result.errors[ticker] = "no CIK on file at SEC for this symbol"
            continue
        resolved.append((ticker, cik))

    with ThreadPoolExecutor(max_workers=cfg.data.max_workers) as pool:
        futures = {
            pool.submit(analyse_one, client, ticker, cik, cfg, today): ticker
            for ticker, cik in resolved
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                candidate = future.result()
            except FetchError as exc:
                result.errors[ticker] = str(exc)
                continue
            except Exception as exc:  # one bad filer must not kill the run
                log.exception("unexpected failure analysing %s", ticker)
                result.errors[ticker] = f"{type(exc).__name__}: {exc}"
                continue

            result.analysed += 1
            if candidate.gate.passed:
                result.candidates.append(candidate)
            else:
                result.rejected.append(candidate)

    result.candidates.sort(key=lambda c: c.rank_score, reverse=True)
    result.rejected.sort(key=lambda c: c.rank_score, reverse=True)

    result.portfolio_messages = apply_portfolio_limits(
        [(c.ticker, c.sector, c.sizing) for c in result.candidates],
        cfg.kelly,
        cfg.portfolio,
    )

    price_dates = [
        c.price_stats.as_of for c in result.candidates + result.rejected
        if c.price_stats.as_of is not None
    ]
    result.price_as_of = max(price_dates) if price_dates else None
    return result
