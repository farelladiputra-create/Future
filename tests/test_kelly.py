"""Kelly sizing, tranche scheduling, and portfolio-level caps."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from buffett.analysis.kelly import (
    SizingReport,
    apply_portfolio_limits,
    build_tranches,
    expected_log_growth,
    kelly_fraction,
    size_position,
    win_probability,
)
from buffett.analysis.quality import QualityReport
from buffett.analysis.valuation import ValuationReport
from buffett.config import KellyConfig, PortfolioConfig, TrancheConfig

TODAY = date(2026, 8, 17)


def test_kelly_fraction_uses_the_partial_loss_form():
    # p/l - q/g with a 100% upside and a 50% downside: 0.6/0.5 - 0.4/1.0
    assert kelly_fraction(0.6, 1.0, 0.5) == pytest.approx(0.8)


def test_kelly_reduces_to_the_textbook_form_when_the_whole_stake_is_lost():
    """With l = 1 the general formula must equal (p*b - q)/b."""
    for p, b in ((0.6, 1.0), (0.55, 2.0), (0.7, 0.5), (0.65, 3.0)):
        textbook = (p * b - (1 - p)) / b
        general = kelly_fraction(p, b, 1.0)
        if textbook > 0:
            assert general == pytest.approx(textbook), (p, b)
        else:
            assert general is None, (p, b)


def test_kelly_declines_to_bet_without_an_edge():
    # A fair coin at even money has no edge.
    assert kelly_fraction(0.5, 1.0, 1.0) is None
    # Negative expectancy.
    assert kelly_fraction(0.4, 1.0, 1.0) is None
    assert kelly_fraction(0.6, 0.0, 0.5) is None
    assert kelly_fraction(0.6, 1.0, 0.0) is None


def test_full_kelly_maximises_expected_log_growth():
    """The defining property: no other stake beats f* on log-wealth growth."""
    p, upside, downside = 0.6, 1.0, 0.5
    optimal = kelly_fraction(p, upside, downside)
    best = expected_log_growth(p, upside, downside, optimal)

    for candidate in (0.1, 0.2, 0.3, 0.35, 0.45, 0.5, 0.6, 0.8):
        rival = expected_log_growth(p, upside, downside, candidate)
        if rival is not None:
            assert rival <= best + 1e-12, candidate


def test_half_kelly_keeps_most_of_the_growth_for_less_risk():
    """Why the default is fractional: the growth curve is flat near its peak."""
    p, upside, downside = 0.6, 1.0, 0.5
    optimal = kelly_fraction(p, upside, downside)
    full = expected_log_growth(p, upside, downside, optimal)
    half = expected_log_growth(p, upside, downside, optimal * 0.5)

    assert half > full * 0.70
    # And overbetting by the same margin costs more than underbetting saves.
    over = expected_log_growth(p, upside, downside, optimal * 1.5)
    assert full - over > full - half


def test_win_probability_stays_inside_its_bounds():
    cfg = KellyConfig()

    floor_case = win_probability(0.0, 0.0, 0.0, cfg)
    ceiling_case = win_probability(1.0, 100.0, 1.0, cfg)

    assert floor_case == pytest.approx(cfg.p_floor)
    assert ceiling_case == pytest.approx(cfg.p_ceiling)
    for mos in (0.1, 0.25, 0.4, 0.75):
        p = win_probability(mos, 70.0, 0.8, cfg)
        assert cfg.p_floor <= p <= cfg.p_ceiling


def test_win_probability_rises_with_margin_of_safety_and_quality():
    cfg = KellyConfig()
    base = win_probability(0.25, 60.0, 0.6, cfg)
    cheaper = win_probability(0.45, 60.0, 0.6, cfg)
    better = win_probability(0.25, 90.0, 0.6, cfg)
    surer = win_probability(0.25, 60.0, 1.0, cfg)

    assert cheaper > base
    assert better > base
    assert surer > base


def test_win_probability_needs_a_margin_of_safety():
    assert win_probability(None, 80.0, 0.9, KellyConfig()) is None


def _valuation(price: float, iv_base: float, iv_bear: float) -> ValuationReport:
    report = ValuationReport(price=price, iv_base=iv_base, iv_bear=iv_bear)
    report.margin_of_safety = (iv_base - price) / iv_base
    report.upside = iv_base / price - 1
    report.confidence = 0.8
    return report


def test_size_position_produces_a_bounded_stake_and_tranches():
    sizing = size_position(
        _valuation(price=60.0, iv_base=100.0, iv_bear=45.0),
        QualityReport(score=75.0),
        KellyConfig(),
        PortfolioConfig(equity_usd=100_000.0, cash_reserve=0.20),
        TrancheConfig(),
        TODAY,
    )

    assert sizing.actionable
    assert 0 < sizing.target_weight <= KellyConfig().max_position
    # Target USD is measured against the invested sleeve, not gross equity.
    assert sizing.target_usd == pytest.approx(sizing.target_weight * 80_000.0)
    # Half Kelly, then the per-position cap, whichever binds first.
    assert sizing.kelly_fraction_used == pytest.approx(
        min(sizing.kelly_full * KellyConfig().fraction, KellyConfig().max_position),
        rel=1e-3,
    )
    assert len(sizing.tranches) == 3
    assert sum(t.usd_amount for t in sizing.tranches) == pytest.approx(
        sizing.target_usd, abs=0.05
    )


def test_size_position_refuses_a_stock_above_intrinsic_value():
    sizing = size_position(
        _valuation(price=120.0, iv_base=100.0, iv_bear=60.0),
        QualityReport(score=80.0),
        KellyConfig(),
        PortfolioConfig(),
        TrancheConfig(),
        TODAY,
    )
    assert not sizing.actionable
    assert any("above intrinsic value" in note for note in sizing.notes)


def test_position_below_the_minimum_is_skipped():
    """A stake too small to matter should not earn a portfolio slot."""
    valuation = _valuation(price=70.0, iv_base=100.0, iv_bear=50.0)
    valuation.confidence = 0.25

    sizing = size_position(
        valuation,
        QualityReport(score=30.0),
        # A minimum this high forces the branch: no realistic half-Kelly clears it.
        KellyConfig(min_position=0.30),
        PortfolioConfig(),
        TrancheConfig(),
        TODAY,
    )
    assert not sizing.actionable
    assert any("not worth a slot" in note for note in sizing.notes)
    assert sizing.tranches == []


def test_negative_expectancy_is_reported_as_no_edge():
    """A tiny discount against a large downside is a bet not worth making."""
    valuation = _valuation(price=97.0, iv_base=100.0, iv_bear=50.0)
    valuation.confidence = 0.25

    sizing = size_position(
        valuation,
        QualityReport(score=30.0),
        KellyConfig(),
        PortfolioConfig(),
        TrancheConfig(),
        TODAY,
    )
    assert not sizing.actionable
    assert any("no positive Kelly edge" in note for note in sizing.notes)


def test_max_position_cap_binds_on_an_extreme_edge():
    sizing = size_position(
        _valuation(price=20.0, iv_base=100.0, iv_bear=18.0),
        QualityReport(score=95.0),
        KellyConfig(max_position=0.15),
        PortfolioConfig(),
        TrancheConfig(),
        TODAY,
    )
    assert sizing.target_weight == pytest.approx(0.15)
    assert sizing.capped_by == "max_position"


def test_minimum_downside_applies_when_the_floor_sits_above_the_price():
    cfg = KellyConfig(min_downside=0.10)
    sizing = size_position(
        _valuation(price=60.0, iv_base=100.0, iv_bear=80.0),
        QualityReport(score=75.0),
        cfg,
        PortfolioConfig(),
        TrancheConfig(),
        TODAY,
    )
    assert sizing.downside == pytest.approx(0.10)
    assert any("minimum downside" in note for note in sizing.notes)


def test_tranche_triggers_step_down_in_price_as_margin_widens():
    tranches = build_tranches(
        target_usd=10_000.0,
        price=80.0,
        iv_base=100.0,
        current_mos=0.20,
        cfg=TrancheConfig(
            splits=[0.5, 0.3, 0.2], mos_steps=[0.0, 0.10, 0.20], time_spacing_days=30
        ),
        today=TODAY,
    )

    assert [t.trigger_price for t in tranches] == [80.0, 70.0, 60.0]
    assert [t.usd_amount for t in tranches] == [5000.0, 3000.0, 2000.0]
    assert [t.target_margin_of_safety for t in tranches] == [0.20, 0.30, 0.40]
    assert [t.shares for t in tranches] == [62, 42, 33]
    assert tranches[0].is_immediate
    assert not tranches[1].is_immediate
    assert [t.fallback_date for t in tranches] == [
        TODAY,
        TODAY + timedelta(days=30),
        TODAY + timedelta(days=60),
    ]


def test_first_tranche_always_buys_at_todays_price():
    tranches = build_tranches(10_000.0, 55.5, 90.0, 0.3833, TrancheConfig(), TODAY)
    assert tranches[0].trigger_price == pytest.approx(55.5, abs=0.05)


def test_tranches_requiring_a_negative_price_are_dropped():
    tranches = build_tranches(
        target_usd=10_000.0,
        price=5.0,
        iv_base=100.0,
        current_mos=0.95,
        cfg=TrancheConfig(splits=[0.5, 0.3, 0.2], mos_steps=[0.0, 0.10, 0.20]),
        today=TODAY,
    )
    # 0.95 + 0.10 and 0.95 + 0.20 both imply a price at or below zero.
    assert len(tranches) == 1


def _actionable(weight: float) -> SizingReport:
    report = SizingReport(actionable=True, target_weight=weight)
    report.target_usd = weight * 80_000.0
    report.tranches = build_tranches(
        report.target_usd, 80.0, 100.0, 0.20, TrancheConfig(), TODAY
    )
    return report


def test_sector_cap_scales_back_a_crowded_sector():
    portfolio = PortfolioConfig(equity_usd=100_000.0, cash_reserve=0.20)
    sized = [
        ("AAA", "Financials", _actionable(0.20)),
        ("BBB", "Financials", _actionable(0.20)),
        ("CCC", "Utilities", _actionable(0.10)),
    ]

    messages = apply_portfolio_limits(sized, KellyConfig(max_sector_exposure=0.30), portfolio)

    financials = sum(r.target_weight for _, s, r in sized if s == "Financials")
    assert financials == pytest.approx(0.30)
    # The untouched sector keeps its original weight.
    assert sized[2][2].target_weight == pytest.approx(0.10)
    assert any("Financials" in m for m in messages)


def test_total_exposure_cap_scales_the_whole_book():
    portfolio = PortfolioConfig(equity_usd=100_000.0, cash_reserve=0.20)
    sized = [(f"T{i}", f"Sector{i}", _actionable(0.20)) for i in range(8)]

    messages = apply_portfolio_limits(sized, KellyConfig(max_sector_exposure=0.35), portfolio)

    total = sum(r.target_weight for _, _, r in sized)
    assert total == pytest.approx(1.0)
    assert any("scaled back" in m for m in messages)


def test_scaling_keeps_tranche_amounts_consistent_with_the_new_target():
    portfolio = PortfolioConfig(equity_usd=100_000.0, cash_reserve=0.20)
    sized = [
        ("AAA", "Energy", _actionable(0.25)),
        ("BBB", "Energy", _actionable(0.25)),
    ]
    apply_portfolio_limits(sized, KellyConfig(max_sector_exposure=0.30), portfolio)

    for _, _, report in sized:
        assert sum(t.usd_amount for t in report.tranches) == pytest.approx(
            report.target_usd, abs=0.05
        )
        assert report.target_usd == pytest.approx(report.target_weight * 80_000.0)


def test_expected_log_growth_is_undefined_for_a_ruinous_stake():
    # Staking more than 1/downside implies losing more than the whole account.
    assert expected_log_growth(0.6, 1.0, 0.5, 2.5) is None
    assert expected_log_growth(0.6, 1.0, 0.5, 0.0) is None


def test_expected_log_growth_is_positive_at_the_recommended_stake():
    p, upside, downside = 0.65, 0.8, 0.4
    optimal = kelly_fraction(p, upside, downside)
    growth = expected_log_growth(p, upside, downside, optimal * 0.5)
    assert growth > 0
    assert math.isfinite(growth)
