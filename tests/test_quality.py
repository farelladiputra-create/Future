"""Forensic scores checked against values worked out by hand."""

from __future__ import annotations

from datetime import date

import pytest

from buffett.analysis.quality import (
    BENEISH_THRESHOLD,
    altman_z_score,
    altman_zone,
    assess_quality,
    beneish_m_score,
    invested_capital,
    piotroski_f_score,
    roic,
)
from buffett.fixtures import make_company, steady_compounder, value_trap
from buffett.models import FiscalYear


def test_piotroski_awards_all_nine_signals():
    prev = FiscalYear(
        period_end=date(2023, 12, 31), label=2023,
        revenue=800.0, gross_profit=200.0, net_income=50.0, cfo=60.0,
        assets=1000.0, long_term_debt=200.0,
        current_assets=300.0, current_liabilities=200.0,
        diluted_shares=100.0, shares_outstanding=100.0,
    )
    curr = FiscalYear(
        period_end=date(2024, 12, 31), label=2024,
        revenue=1000.0, gross_profit=300.0, net_income=80.0, cfo=120.0,
        assets=1100.0, long_term_debt=150.0,
        current_assets=400.0, current_liabilities=200.0,
        diluted_shares=99.0, shares_outstanding=99.0,
    )

    score, signals = piotroski_f_score(curr, prev, prior_assets=900.0)
    assert score == 9
    assert all(signals.values()), [k for k, v in signals.items() if not v]


def test_piotroski_marks_unavailable_signals_as_none():
    """A thinly tagged filer scores only the signals its data supports."""
    prev = FiscalYear(
        period_end=date(2023, 12, 31), label=2023, net_income=50.0, assets=1000.0
    )
    curr = FiscalYear(
        period_end=date(2024, 12, 31), label=2024, net_income=80.0, assets=1100.0
    )

    score, signals = piotroski_f_score(curr, prev)
    assert signals["cfo_positive"] is None
    assert signals["margin_improving"] is None
    assert signals["roa_positive"] is True
    assert signals["roa_improving"] is True
    # Only the two computable signals contribute; the rest neither add nor
    # subtract, which is why `piotroski_reliable` gates the score downstream.
    assert score == 2


def test_piotroski_returns_none_when_nothing_can_be_computed():
    prev = FiscalYear(period_end=date(2023, 12, 31), label=2023)
    curr = FiscalYear(period_end=date(2024, 12, 31), label=2024)
    score, _ = piotroski_f_score(curr, prev)
    assert score is None


def test_altman_z_matches_hand_calculation():
    year = FiscalYear(
        period_end=date(2024, 12, 31), label=2024,
        current_assets=500.0, current_liabilities=300.0,   # working capital 200
        assets=1000.0, retained_earnings=300.0,
        operating_income=150.0, liabilities=400.0, revenue=900.0,
    )
    # 1.2(0.2) + 1.4(0.3) + 3.3(0.15) + 0.6(3.0) + 1.0(0.9)
    assert altman_z_score(year, market_cap=1200.0) == pytest.approx(3.855)
    assert altman_zone(3.855) == "safe"
    assert altman_zone(2.0) == "grey"
    assert altman_zone(1.0) == "distress"
    assert altman_zone(None) == "unknown"


def test_altman_needs_a_market_cap():
    year = FiscalYear(
        period_end=date(2024, 12, 31), label=2024,
        current_assets=500.0, current_liabilities=300.0, assets=1000.0,
        retained_earnings=300.0, operating_income=150.0, liabilities=400.0,
        revenue=900.0,
    )
    assert altman_z_score(year, market_cap=None) is None


def _beneish_year(end: date, **overrides) -> FiscalYear:
    base = dict(
        revenue=1000.0, gross_profit=400.0, receivables=100.0, sga=200.0,
        assets=2000.0, current_assets=600.0, ppe_net=800.0,
        current_liabilities=300.0, long_term_debt=500.0,
        depreciation_amortization=100.0, net_income=120.0, cfo=120.0,
    )
    base.update(overrides)
    return FiscalYear(period_end=end, label=end.year, **base)


def test_beneish_is_clean_when_nothing_changes():
    """Identical years make every index 1.0 and the accrual term 0."""
    prev = _beneish_year(date(2023, 12, 31))
    curr = _beneish_year(date(2024, 12, 31))

    score, real_terms = beneish_m_score(curr, prev)
    # -4.84 + 0.920 + 0.528 + 0.404 + 0.892 + 0.115 - 0.172 + 0 - 0.327
    assert score == pytest.approx(-2.48)
    assert real_terms == 8
    assert score < BENEISH_THRESHOLD


def test_beneish_flags_large_accruals():
    """Net income far above operating cash flow drives the TATA term."""
    prev = _beneish_year(date(2023, 12, 31))
    curr = _beneish_year(date(2024, 12, 31), net_income=300.0, cfo=50.0)

    score, real_terms = beneish_m_score(curr, prev)
    # TATA = (300 - 50) / 2000 = 0.125, contributing 4.679 * 0.125
    assert score == pytest.approx(-2.48 + 4.679 * 0.125)
    assert real_terms == 8


def test_beneish_reports_how_many_terms_were_real():
    bare_prev = FiscalYear(period_end=date(2023, 12, 31), label=2023, revenue=1000.0)
    bare_curr = FiscalYear(period_end=date(2024, 12, 31), label=2024, revenue=1200.0)

    _, real_terms = beneish_m_score(bare_curr, bare_prev)
    # Only the sales growth index can be computed from revenue alone.
    assert real_terms == 1


def test_invested_capital_excludes_idle_cash():
    year = FiscalYear(
        period_end=date(2024, 12, 31), label=2024,
        equity=1000.0, long_term_debt=400.0, short_term_debt=100.0,
        cash=200.0, short_term_investments=50.0,
    )
    # 1000 + 500 - 250
    assert invested_capital(year) == pytest.approx(1250.0)


def test_roic_uses_the_effective_tax_rate_when_usable():
    year = FiscalYear(
        period_end=date(2024, 12, 31), label=2024,
        operating_income=200.0, pretax_income=200.0, tax_expense=50.0,
        equity=1000.0, long_term_debt=0.0, cash=0.0,
    )
    # Effective rate 25%, invested capital 1000.
    assert roic(year, fallback_tax_rate=0.21) == pytest.approx(0.15)


def test_roic_falls_back_when_the_effective_rate_is_implausible():
    year = FiscalYear(
        period_end=date(2024, 12, 31), label=2024,
        operating_income=200.0, pretax_income=200.0, tax_expense=180.0,  # 90%
        equity=1000.0, long_term_debt=0.0, cash=0.0,
    )
    assert roic(year, fallback_tax_rate=0.20) == pytest.approx(0.16)


def test_compounder_scores_well_and_trap_scores_badly():
    good = make_company("GOOD", years=steady_compounder(), last_close=12.0)
    bad = make_company("BAD", years=value_trap(), last_close=4.0, shares_outstanding=500e6)

    good_quality = assess_quality(good, lookback=6, fallback_tax_rate=0.21)
    bad_quality = assess_quality(bad, lookback=6, fallback_tax_rate=0.21)

    assert good_quality.piotroski_f is not None and good_quality.piotroski_f >= 7
    assert good_quality.score > 65
    assert good_quality.avg_roe is not None and good_quality.avg_roe > 0.20

    assert bad_quality.score < good_quality.score
    assert bad_quality.flags, "a deteriorating filer should raise flags"


def test_value_trap_accrual_and_dilution_flags_fire():
    bad = make_company("BAD", years=value_trap(), last_close=4.0, shares_outstanding=500e6)
    report = assess_quality(bad, lookback=6, fallback_tax_rate=0.21)

    joined = " | ".join(report.flags)
    assert "accruals" in joined or "cash flow" in joined
    assert report.share_count_cagr is not None and report.share_count_cagr > 0.03


def test_dividend_profile_counts_the_paying_record():
    company = make_company("GOOD", years=steady_compounder(count=6), last_close=12.0)
    report = assess_quality(company, lookback=6, fallback_tax_rate=0.21)

    assert report.dividend.paying_years == 6
    assert report.dividend.dps_latest is not None
    assert report.dividend.yield_pct is not None and report.dividend.yield_pct > 0
    # Payout is 30% of earnings by construction.
    assert report.dividend.payout_ratio == pytest.approx(0.30, abs=0.02)
    assert report.dividend.covered_by_fcf is True


def test_no_interest_expense_reads_as_unlimited_coverage():
    years = steady_compounder(count=5)
    for year in years:
        year.interest_expense = 0.0
    company = make_company("NODEBT", years=years, last_close=12.0)
    report = assess_quality(company, lookback=5, fallback_tax_rate=0.21)
    assert report.interest_coverage == float("inf")


def test_quality_score_stays_in_range():
    for years in (steady_compounder(), value_trap()):
        company = make_company(years=years, last_close=10.0)
        report = assess_quality(company, lookback=6, fallback_tax_rate=0.21)
        assert 0.0 <= report.score <= 100.0
