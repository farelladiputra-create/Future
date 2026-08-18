"""Valuation methods, checked against independently computed values."""

from __future__ import annotations

from datetime import date

import pytest

from buffett.analysis.quality import QualityReport, assess_quality
from buffett.analysis.valuation import (
    discount_rate,
    earnings_power_value,
    graham_number,
    historical_pe_median,
    maintenance_capex,
    normalized_multiple_value,
    owner_earnings_series,
    two_stage_dcf,
    value_company,
)
from buffett.config import ValuationConfig
from buffett.fixtures import make_company, steady_compounder, value_trap
from buffett.models import FiscalYear


def test_two_stage_dcf_matches_an_independent_recomputation():
    result = two_stage_dcf(
        base_owner_earnings=100.0,
        growth_stage1=0.05,
        terminal_growth=0.025,
        rate=0.10,
        years=3,
        net_cash=0.0,
        shares=10.0,
    )

    # Growth fades linearly from 5% to 2.5% across the three years.
    present_value, flow = 0.0, 100.0
    for period in range(1, 4):
        growth = 0.05 + (0.025 - 0.05) * ((period - 1) / 2)
        flow *= 1 + growth
        present_value += flow / 1.10**period
    present_value += (flow * 1.025 / (0.10 - 0.025)) / 1.10**3

    assert result == pytest.approx(present_value / 10.0)
    assert result == pytest.approx(141.5909, abs=1e-3)


def test_dcf_adds_net_cash_and_subtracts_net_debt():
    with_cash = two_stage_dcf(100.0, 0.03, 0.025, 0.10, 5, 500.0, 10.0)
    neutral = two_stage_dcf(100.0, 0.03, 0.025, 0.10, 5, 0.0, 10.0)
    with_debt = two_stage_dcf(100.0, 0.03, 0.025, 0.10, 5, -500.0, 10.0)

    assert with_cash == pytest.approx(neutral + 50.0)
    assert with_debt == pytest.approx(neutral - 50.0)


def test_dcf_refuses_impossible_inputs():
    # Terminal growth at or above the discount rate implies infinite value.
    assert two_stage_dcf(100.0, 0.03, 0.10, 0.10, 5, 0.0, 10.0) is None
    assert two_stage_dcf(100.0, 0.03, 0.025, 0.02, 5, 0.0, 10.0) is None
    # Negative owner earnings cannot be capitalised.
    assert two_stage_dcf(-50.0, 0.03, 0.025, 0.10, 5, 0.0, 10.0) is None
    assert two_stage_dcf(100.0, 0.03, 0.025, 0.10, 5, 0.0, 0.0) is None


def test_dcf_is_monotonic_in_rate_and_growth():
    cheap_money = two_stage_dcf(100.0, 0.05, 0.025, 0.08, 10, 0.0, 10.0)
    dear_money = two_stage_dcf(100.0, 0.05, 0.025, 0.12, 10, 0.0, 10.0)
    assert cheap_money > dear_money

    fast = two_stage_dcf(100.0, 0.08, 0.025, 0.10, 10, 0.0, 10.0)
    slow = two_stage_dcf(100.0, 0.02, 0.025, 0.10, 10, 0.0, 10.0)
    assert fast > slow


def test_graham_number():
    assert graham_number(5.0, 20.0) == pytest.approx(47.4341649)
    # Loss-making or negative-book companies get no Graham value.
    assert graham_number(-1.0, 20.0) is None
    assert graham_number(5.0, -20.0) is None
    assert graham_number(None, 20.0) is None


def test_maintenance_capex_strips_out_growth_spend():
    prev = FiscalYear(period_end=date(2023, 12, 31), label=2023, revenue=1000.0)
    curr = FiscalYear(
        period_end=date(2024, 12, 31), label=2024, revenue=1100.0, capex=120.0
    )
    # PP&E intensity 0.5 applied to 100 of new revenue is 50 of growth capex.
    assert maintenance_capex(curr, prev, 0.5) == pytest.approx(70.0)


def test_maintenance_capex_is_all_of_capex_when_revenue_shrinks():
    prev = FiscalYear(period_end=date(2023, 12, 31), label=2023, revenue=1000.0)
    curr = FiscalYear(
        period_end=date(2024, 12, 31), label=2024, revenue=900.0, capex=120.0
    )
    assert maintenance_capex(curr, prev, 0.5) == pytest.approx(120.0)


def test_owner_earnings_charge_only_maintenance_capex():
    years = [
        FiscalYear(
            period_end=date(2023, 12, 31), label=2023,
            revenue=1000.0, ppe_gross=500.0, cfo=200.0, capex=100.0,
        ),
        FiscalYear(
            period_end=date(2024, 12, 31), label=2024,
            revenue=1100.0, ppe_gross=550.0, cfo=220.0, capex=120.0,
        ),
    ]
    company = make_company(years=years)

    series = owner_earnings_series(company, years, book_value_business=False)
    values = [value for _, value in series]
    # Year one has no prior period, so all capex counts as maintenance.
    assert values[0] == pytest.approx(100.0)
    # Year two: 220 - (120 - 0.5 * 100)
    assert values[1] == pytest.approx(150.0)


def test_owner_earnings_use_net_income_for_lenders():
    years = [
        FiscalYear(
            period_end=date(2024, 12, 31), label=2024,
            net_income=500.0, cfo=200.0, capex=10.0, revenue=1000.0,
        )
    ]
    company = make_company(years=years, sector="Financials")
    series = owner_earnings_series(company, years, book_value_business=True)
    assert [v for _, v in series] == [500.0]


def test_earnings_power_value_matches_hand_calculation():
    years = [
        FiscalYear(
            period_end=date(2020 + offset, 12, 31), label=2020 + offset,
            revenue=1000.0, operating_income=200.0,
            pretax_income=190.0, tax_expense=38.0,   # 20% effective rate
            cash=100.0, long_term_debt=100.0,        # net cash zero
        )
        for offset in range(3)
    ]
    # 200 x (1 - 0.20) / 0.10 = 1600 of equity value over 10 shares.
    result = earnings_power_value(
        years, rate=0.10, net_cash=0.0, shares=10.0, fallback_tax_rate=0.21
    )
    assert result == pytest.approx(160.0)


def test_epv_needs_positive_operating_profit():
    years = [
        FiscalYear(
            period_end=date(2024, 12, 31), label=2024,
            revenue=1000.0, operating_income=-50.0,
        )
    ]
    assert earnings_power_value(years, 0.10, 0.0, 10.0, 0.21) is None


def test_historical_pe_discards_nonsense_multiples():
    years = [
        FiscalYear(period_end=date(2022, 12, 31), label=2022, eps_diluted=5.0),
        FiscalYear(period_end=date(2023, 12, 31), label=2023, eps_diluted=6.0),
        FiscalYear(period_end=date(2024, 12, 31), label=2024, eps_diluted=0.01),
    ]
    prices = {
        date(2022, 12, 31): 50.0,   # 10x
        date(2023, 12, 31): 72.0,   # 12x
        date(2024, 12, 31): 60.0,   # 6000x, an earnings collapse, discarded
    }
    assert historical_pe_median(years, prices) == pytest.approx(11.0)


def test_normalized_multiple_caps_at_grahams_ceiling():
    value, basis = normalized_multiple_value(
        normalised_eps=4.0, hist_pe=25.0, sector="Information Technology", cap=15.0
    )
    assert value == pytest.approx(60.0)
    assert "capped" in basis

    value, basis = normalized_multiple_value(
        normalised_eps=4.0, hist_pe=None, sector="Financials", cap=15.0
    )
    # Falls back to the sector average of 12x, below the cap.
    assert value == pytest.approx(48.0)
    assert "no usable own history" in basis


def test_discount_rate_penalises_weak_balance_sheets():
    cfg = ValuationConfig()
    clean = QualityReport(piotroski_f=8, debt_to_equity=0.4, altman_z=4.0)
    weak = QualityReport(piotroski_f=4, debt_to_equity=1.8, altman_z=1.5)

    baseline = discount_rate(cfg, volatility=0.20, quality=clean)
    penalised = discount_rate(cfg, volatility=0.20, quality=weak)

    assert baseline == pytest.approx(cfg.risk_free_rate + cfg.equity_risk_premium)
    # Three penalties of one point each.
    assert penalised == pytest.approx(baseline + 0.03)


def test_discount_rate_scales_with_volatility_and_stays_bounded():
    cfg = ValuationConfig()
    clean = QualityReport(piotroski_f=8, debt_to_equity=0.4, altman_z=4.0)

    calm = discount_rate(cfg, volatility=0.10, quality=clean)
    wild = discount_rate(cfg, volatility=0.90, quality=clean)

    assert calm < wild
    assert cfg.discount_rate_floor <= calm <= cfg.discount_rate_cap
    assert cfg.discount_rate_floor <= wild <= cfg.discount_rate_cap


def test_cheap_compounder_shows_a_margin_of_safety():
    years = steady_compounder()
    company = make_company("GOOD", years=years, last_close=12.0, shares_outstanding=930e6)
    quality = assess_quality(company, 6, 0.21)
    cfg = ValuationConfig()

    report = value_company(company, quality, cfg, 6, 0.0, {})

    assert report.iv_base is not None and report.iv_base > 0
    assert report.margin_of_safety is not None and report.margin_of_safety > 0
    assert report.upside is not None and report.upside > 0
    # Margin of safety and upside are two views of the same gap.
    assert report.upside == pytest.approx(
        report.margin_of_safety / (1 - report.margin_of_safety)
    )
    assert len(report.methods_used) >= 3
    assert report.confidence is not None


def test_the_same_business_at_a_high_price_shows_no_margin_of_safety():
    years = steady_compounder()
    cheap = make_company("GOOD", years=years, last_close=12.0, shares_outstanding=930e6)
    rich = make_company("GOOD", years=years, last_close=400.0, shares_outstanding=930e6)
    cfg = ValuationConfig()

    cheap_report = value_company(cheap, assess_quality(cheap, 6, 0.21), cfg, 6, 0.0, {})
    rich_report = value_company(rich, assess_quality(rich, 6, 0.21), cfg, 6, 0.0, {})

    assert cheap_report.margin_of_safety > 0
    assert rich_report.margin_of_safety < 0
    assert rich_report.pe_trailing > cheap_report.pe_trailing


def test_lender_valuation_leans_on_book_value_and_says_so():
    years = steady_compounder()
    company = make_company("BANK", sector="Financials", years=years, last_close=12.0)
    report = value_company(company, assess_quality(company, 6, 0.21), ValuationConfig(), 6, 0.0, {})

    assert any("book value" in note for note in report.notes)
    assert report.iv_book is not None


def test_confidence_measures_only_the_going_concern_methods():
    """Graham and book value are floors, not competing central estimates.

    Including a deliberately conservative floor in the dispersion calculation
    would peg every growing business at minimum confidence for structural
    rather than informational reasons.
    """
    company = make_company(
        years=steady_compounder(), last_close=12.0, shares_outstanding=930e6
    )
    report = value_company(
        company, assess_quality(company, 6, 0.21), ValuationConfig(), 6, 0.0, {}
    )

    central = [
        v for v in (report.iv_dcf, report.iv_epv, report.iv_multiple) if v is not None
    ]
    assert len(central) >= 2
    spread = (max(central) - min(central)) / sorted(central)[len(central) // 2]
    assert report.confidence == pytest.approx(
        max(0.2, min(1.0, 1.0 - spread / 1.5)), abs=1e-3
    )

    # Graham sits well below the central estimates for a grower, so including it
    # would have produced a materially lower number.
    assert report.iv_graham is not None and report.iv_graham < min(central)


def test_healthy_asset_light_business_is_not_floored_at_tangible_book():
    """A compounder in the Altman safe zone must not be priced for liquidation."""
    company = make_company(
        years=steady_compounder(), last_close=90.0, shares_outstanding=930e6
    )
    quality = assess_quality(company, 6, 0.21)
    assert quality.altman_zone == "safe", quality.altman_z

    report = value_company(company, quality, ValuationConfig(), 6, 0.0, {})
    latest = company.latest
    tangible_bvps = latest.tangible_equity / 930e6

    assert report.iv_bear is not None
    assert report.iv_bear > tangible_bvps
    assert not any("tangible book" in note for note in report.notes)


def test_balance_sheet_business_does_use_tangible_book_as_a_floor():
    years = steady_compounder()
    company = make_company(
        "BANK", sector="Financials", years=years, last_close=90.0,
        shares_outstanding=930e6,
    )
    report = value_company(
        company, assess_quality(company, 6, 0.21), ValuationConfig(), 6, 0.0, {}
    )

    tangible_bvps = company.latest.tangible_equity / 930e6
    assert report.iv_bear == pytest.approx(tangible_bvps)
    assert any("tangible book" in note for note in report.notes)


def test_distressed_filer_uses_the_liquidation_floor_when_it_is_positive():
    """When Altman leaves the safe zone, the balance sheet becomes the story."""
    years = steady_compounder()
    # Degrade the balance sheet until Altman drops out of the safe zone, while
    # leaving tangible equity positive.
    for year in years:
        year.retained_earnings = year.equity * 0.05
        year.long_term_debt = year.revenue * 1.4
        year.goodwill = year.revenue * 0.02
        year.intangibles = year.revenue * 0.01

    # Altman's X4 term is market value of equity over total liabilities, so a
    # depressed price is part of what pushes a levered filer out of the safe zone.
    company = make_company("WEAK", years=years, last_close=12.0, shares_outstanding=930e6)
    quality = assess_quality(company, 6, 0.21)
    assert quality.altman_zone != "safe", quality.altman_z
    assert company.latest.tangible_equity > 0

    report = value_company(company, quality, ValuationConfig(), 6, 0.0, {})
    assert any("tangible book" in note for note in report.notes)


def test_negative_tangible_book_is_never_used_as_a_floor():
    """Goodwill-heavy filers can show negative tangible equity; that is not a floor."""
    company = make_company(
        "BAD", years=value_trap(), last_close=3.0, shares_outstanding=620e6
    )
    quality = assess_quality(company, 6, 0.21)
    assert quality.altman_zone != "safe"
    assert company.latest.tangible_equity < 0

    report = value_company(company, quality, ValuationConfig(), 6, 0.0, {})
    assert not any("tangible book" in note for note in report.notes)
    if report.iv_bear is not None:
        assert report.iv_bear > 0


def test_multiples_are_computed_for_a_normal_filer():
    years = steady_compounder()
    company = make_company(years=years, last_close=12.0, shares_outstanding=930e6)
    report = value_company(company, assess_quality(company, 6, 0.21), ValuationConfig(), 6, 0.0, {})

    for attribute in ("pe_trailing", "pbv", "ps", "ev_ebit", "fcf_yield", "earnings_yield"):
        assert getattr(report, attribute) is not None, attribute
    assert report.pe_trailing > 0
    assert report.owner_earnings_per_share is not None


def test_no_price_means_no_valuation():
    company = make_company(years=steady_compounder(), last_close=12.0)
    company.prices.closes = []
    company.prices.dates = []
    report = value_company(company, QualityReport(), ValuationConfig(), 6, None, {})

    assert report.iv_base is None
    assert any("cannot value" in note for note in report.notes)


def test_loss_making_filer_still_produces_a_bounded_report():
    """A value trap must not raise, and must not fabricate an intrinsic value."""
    company = make_company("BAD", years=value_trap(), last_close=4.0, shares_outstanding=500e6)
    report = value_company(company, assess_quality(company, 6, 0.21), ValuationConfig(), 6, 0.0, {})

    if report.iv_base is not None:
        assert report.iv_base > 0
    assert report.price == pytest.approx(4.0)
