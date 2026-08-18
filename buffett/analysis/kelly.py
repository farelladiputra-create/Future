"""Position sizing by fractional Kelly, then a staged entry schedule.

The Kelly criterion maximises the expected logarithm of wealth. The textbook
form, f* = (p*b - q)/b, assumes a losing bet forfeits the entire stake. An
equity position does not: a thesis that fails usually leaves the shares worth
something, so the loss is a fraction l of the position rather than all of it.

Maximising p*ln(1 + f*g) + q*ln(1 - f*l) for gain fraction g and loss fraction l
gives the general form used here:

    f* = (p*g - q*l) / (g*l) = p/l - q/g

which collapses to the textbook version when l = 1. The distinction matters:
with a 100% upside and a 50% downside at p = 0.6, the textbook form says stake
40% while the correct figure is 80%. Partial-loss Kelly is far more aggressive
than most people expect, which is exactly why the caps below are not optional.

Two things matter about applying it to equities:

1. p and b are estimated, not known. Kelly is brutally sensitive to
   overestimating p, and the penalty for betting above f* is much worse than
   the penalty for betting below it. The engine therefore runs a fraction of
   Kelly (half, by default) and caps p at 0.80 no matter how good the screen
   looks.
2. The bet is not settled at a known date. Staging entry across price levels
   converts that open-endedness into an advantage: if the market offers a worse
   price later, the later tranches buy at a wider margin of safety.

Nothing here is a measured frequency. p is a model output derived from margin of
safety, business quality, and how far the four valuation methods disagree.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..config import KellyConfig, PortfolioConfig, TrancheConfig
from .quality import QualityReport
from .stats import clamp
from .valuation import ValuationReport

# Weights mapping the edge components onto win probability. Margin of safety
# leads because it is the only one that directly buys downside protection.
WEIGHT_MARGIN_OF_SAFETY = 0.45
WEIGHT_QUALITY = 0.35
WEIGHT_CONFIDENCE = 0.20
# Margin of safety at which the model stops crediting extra probability.
MOS_SATURATION = 0.50


@dataclass
class Tranche:
    index: int
    fraction: float  # share of the target position
    usd_amount: float
    trigger_price: float
    target_margin_of_safety: float
    shares: int
    fallback_date: date
    is_immediate: bool


@dataclass
class SizingReport:
    win_probability: float | None = None
    upside: float | None = None
    downside: float | None = None
    odds: float | None = None
    kelly_full: float | None = None
    kelly_fraction_used: float | None = None
    target_weight: float | None = None  # fraction of investable equity
    target_usd: float | None = None
    capped_by: str | None = None
    expected_log_growth: float | None = None
    tranches: list[Tranche] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    actionable: bool = False

    def add_note(self, note: str) -> None:
        if note not in self.notes:
            self.notes.append(note)


def win_probability(
    margin_of_safety: float | None,
    quality_score: float,
    confidence: float | None,
    cfg: KellyConfig,
) -> float | None:
    """Map the edge components onto a bounded win probability.

    Linear rather than logistic on purpose: every coefficient here is a
    judgement call, and a linear map makes the sensitivity obvious instead of
    burying it in a curve.
    """
    if margin_of_safety is None:
        return None
    mos_component = clamp(margin_of_safety / MOS_SATURATION, 0.0, 1.0)
    quality_component = clamp(quality_score / 100.0, 0.0, 1.0)
    confidence_component = clamp(confidence if confidence is not None else 0.4, 0.0, 1.0)

    edge = (
        WEIGHT_MARGIN_OF_SAFETY * mos_component
        + WEIGHT_QUALITY * quality_component
        + WEIGHT_CONFIDENCE * confidence_component
    )
    return cfg.p_floor + (cfg.p_ceiling - cfg.p_floor) * edge


def kelly_fraction(p: float, upside: float, downside: float) -> float | None:
    """Full Kelly stake for a two-outcome bet with partial loss.

    `upside` is the fractional gain if the thesis works, `downside` the
    fractional loss if it does not. Returns None when the bet has no positive
    expectancy, since f* > 0 holds exactly when p*upside > q*downside.
    """
    if downside <= 0 or upside <= 0 or not 0 < p < 1:
        return None
    f = p / downside - (1 - p) / upside
    return f if f > 0 else None


def expected_log_growth(p: float, upside: float, downside: float, f: float) -> float | None:
    """Expected log wealth growth per bet at stake f. Sanity check on sizing."""
    if f <= 0 or f >= 1 / downside:
        return None
    return p * math.log(1 + f * upside) + (1 - p) * math.log(1 - f * downside)


def size_position(
    valuation: ValuationReport,
    quality: QualityReport,
    kelly_cfg: KellyConfig,
    portfolio: PortfolioConfig,
    tranche_cfg: TrancheConfig,
    today: date,
) -> SizingReport:
    """Full Kelly sizing plus the tranche schedule for one name."""
    report = SizingReport()
    price, iv_base = valuation.price, valuation.iv_base
    mos = valuation.margin_of_safety

    if price is None or iv_base is None or mos is None:
        report.add_note("cannot size without a price and an intrinsic value")
        return report
    if mos <= 0:
        report.add_note("trading at or above intrinsic value, no position")
        return report

    # Upside is the gap to intrinsic value. Downside is the drop to the bear-case
    # floor, which is where a thesis that turns out wrong most plausibly lands.
    upside = iv_base / price - 1.0
    if valuation.iv_bear is not None and valuation.iv_bear < price:
        downside = 1.0 - valuation.iv_bear / price
    else:
        # Bear floor sits above the current price, so the floor-based loss is
        # zero. That is not a licence to assume no risk: fall back to the
        # configured minimum severity.
        downside = kelly_cfg.min_downside
        report.add_note(
            "bear-case floor is above the market price, so minimum downside applied"
        )
    downside = clamp(downside, kelly_cfg.min_downside, kelly_cfg.max_downside)

    p = win_probability(mos, quality.score, valuation.confidence, kelly_cfg)
    if p is None:
        report.add_note("win probability could not be modelled")
        return report

    report.win_probability = round(p, 4)
    report.upside = round(upside, 4)
    report.downside = round(downside, 4)
    report.odds = round(upside / downside, 3)

    full = kelly_fraction(p, upside, downside)
    if full is None:
        report.add_note("no positive Kelly edge at the modelled probability")
        return report
    report.kelly_full = round(full, 4)

    staked = full * kelly_cfg.fraction
    if staked > kelly_cfg.max_position:
        staked = kelly_cfg.max_position
        report.capped_by = "max_position"
    report.kelly_fraction_used = round(staked, 4)

    if staked < kelly_cfg.min_position:
        report.add_note(
            f"sized at {staked * 100:.1f}% of the sleeve, below the "
            f"{kelly_cfg.min_position * 100:.0f}% minimum: not worth a slot"
        )
        report.target_weight = round(staked, 4)
        return report

    investable = portfolio.equity_usd * (1.0 - portfolio.cash_reserve)
    report.target_weight = round(staked, 4)
    report.target_usd = round(staked * investable, 2)
    report.expected_log_growth = expected_log_growth(p, upside, downside, staked)
    report.tranches = build_tranches(
        target_usd=report.target_usd,
        price=price,
        iv_base=iv_base,
        current_mos=mos,
        cfg=tranche_cfg,
        today=today,
    )
    report.actionable = True
    return report


def build_tranches(
    target_usd: float,
    price: float,
    iv_base: float,
    current_mos: float,
    cfg: TrancheConfig,
    today: date,
) -> list[Tranche]:
    """Split the target into tranches triggered by widening margin of safety.

    Tranche one buys at today's price. Each later tranche waits for a price that
    offers an additional `mos_steps[i]` of margin of safety, expressed as a limit
    price against the same intrinsic value estimate. If the market never obliges,
    the tranche deploys anyway on its fallback date so capital is not held
    hostage to a dip that never comes.
    """
    tranches: list[Tranche] = []
    for index, (fraction, step) in enumerate(zip(cfg.splits, cfg.mos_steps)):
        target_mos = current_mos + step
        if target_mos >= 1.0:
            # Would require a price at or below zero.
            continue
        trigger_price = iv_base * (1.0 - target_mos)
        if trigger_price <= 0:
            continue
        usd = target_usd * fraction
        tranches.append(
            Tranche(
                index=index + 1,
                fraction=fraction,
                usd_amount=round(usd, 2),
                trigger_price=round(trigger_price, 2),
                target_margin_of_safety=round(target_mos, 4),
                shares=int(usd // trigger_price),
                fallback_date=today + timedelta(days=cfg.time_spacing_days * index),
                is_immediate=index == 0,
            )
        )
    return tranches


def apply_portfolio_limits(
    sized: list[tuple[str, str, SizingReport]],
    kelly_cfg: KellyConfig,
    portfolio: PortfolioConfig,
) -> list[str]:
    """Enforce sector and total-exposure caps across the whole recommended book.

    Kelly sizes each bet as though it were the only one. A book of ten
    positions each sized independently can add up to more than the sleeve, and
    correlated names inside one sector are closer to a single bet than to ten.
    Takes (ticker, sector, report) triples and scales reports down in place.
    """
    messages: list[str] = []
    actionable = [(t, s, r) for t, s, r in sized if r.actionable and r.target_weight]

    # Sector caps first, since they bind on a subset.
    by_sector: dict[str, list[tuple[str, SizingReport]]] = {}
    for ticker, sector, report in actionable:
        by_sector.setdefault(sector, []).append((ticker, report))

    for sector, holdings in by_sector.items():
        exposure = sum(r.target_weight or 0.0 for _, r in holdings)
        if exposure > kelly_cfg.max_sector_exposure:
            scale = kelly_cfg.max_sector_exposure / exposure
            for ticker, report in holdings:
                _scale(report, scale, portfolio)
                report.capped_by = "max_sector_exposure"
            messages.append(
                f"{sector} exposure trimmed from {exposure * 100:.1f}% to "
                f"{kelly_cfg.max_sector_exposure * 100:.0f}% of the sleeve"
            )

    # Then the total book against fully invested capital.
    total = sum(r.target_weight or 0.0 for _, _, r in actionable)
    if total > 1.0:
        scale = 1.0 / total
        for _, _, report in actionable:
            _scale(report, scale, portfolio)
            report.capped_by = "total_exposure"
        messages.append(
            f"combined Kelly stakes came to {total * 100:.0f}% of the sleeve "
            "and were scaled back to 100%"
        )
    return messages


def _scale(report: SizingReport, scale: float, portfolio: PortfolioConfig) -> None:
    if report.target_weight is None:
        return
    report.target_weight = round(report.target_weight * scale, 4)
    investable = portfolio.equity_usd * (1.0 - portfolio.cash_reserve)
    report.target_usd = round(report.target_weight * investable, 2)
    for tranche in report.tranches:
        tranche.usd_amount = round(report.target_usd * tranche.fraction, 2)
        tranche.shares = (
            int(tranche.usd_amount // tranche.trigger_price)
            if tranche.trigger_price > 0
            else 0
        )
