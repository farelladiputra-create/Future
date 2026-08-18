"""Numeric helpers, including the missing-data contract."""

from __future__ import annotations

import pytest

from buffett.analysis.stats import (
    cagr,
    clamp,
    coefficient_of_variation,
    count_positive,
    median,
    percentile,
    robust_growth,
    safe_div,
    stdev,
    trend_slope,
    yoy_growth,
)


def test_safe_div_returns_none_rather_than_raising():
    assert safe_div(10.0, 4.0) == pytest.approx(2.5)
    assert safe_div(10.0, 0.0) is None
    assert safe_div(None, 4.0) is None
    assert safe_div(10.0, None) is None


def test_median_handles_both_parities():
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([4.0, 1.0, 3.0, 2.0]) == 2.5
    assert median([]) is None


def test_cagr_refuses_sign_changes():
    # 100 to 121 over two periods is 10% a year.
    assert cagr([100.0, 110.0, 121.0]) == pytest.approx(0.10)
    assert cagr([-100.0, 121.0]) is None
    assert cagr([100.0, -121.0]) is None
    assert cagr([100.0]) is None


def test_yoy_growth_skips_non_positive_bases():
    assert yoy_growth([100.0, 110.0]) == pytest.approx([0.10])
    assert yoy_growth([0.0, 110.0]) == []
    assert yoy_growth([-5.0, 110.0]) == []


def test_robust_growth_takes_the_more_conservative_of_two_measures():
    """A final-year spike must not set the growth assumption on its own."""
    spiky = [100.0, 101.0, 102.0, 103.0, 200.0]
    endpoint_cagr = cagr(spiky)
    step_median = median(yoy_growth(spiky))

    assert robust_growth(spiky) == pytest.approx(min(endpoint_cagr, step_median))
    assert robust_growth(spiky) < endpoint_cagr


def test_robust_growth_on_a_smooth_series_matches_the_rate():
    smooth = [100.0 * 1.08**index for index in range(6)]
    assert robust_growth(smooth) == pytest.approx(0.08, abs=1e-9)


def test_coefficient_of_variation_measures_steadiness():
    steady = [0.20, 0.21, 0.20, 0.19, 0.20]
    erratic = [0.05, 0.40, -0.10, 0.35, 0.20]
    assert coefficient_of_variation(steady) < coefficient_of_variation(erratic)
    assert coefficient_of_variation([0.2]) is None


def test_stdev_and_clamp():
    assert stdev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) == pytest.approx(2.13809, abs=1e-4)
    assert stdev([1.0]) is None
    assert clamp(5.0, 0.0, 1.0) == 1.0
    assert clamp(-5.0, 0.0, 1.0) == 0.0
    assert clamp(0.5, 0.0, 1.0) == 0.5


def test_trend_slope_sign_follows_the_direction_of_travel():
    assert trend_slope([0.10, 0.12, 0.14, 0.16]) > 0
    assert trend_slope([0.16, 0.14, 0.12, 0.10]) < 0
    assert trend_slope([0.10, 0.10]) is None


def test_percentile_interpolates():
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0.0) == 1.0
    assert percentile(values, 1.0) == 4.0
    assert percentile(values, 0.5) == pytest.approx(2.5)
    assert percentile([], 0.5) is None


def test_count_positive():
    assert count_positive([1.0, -1.0, 0.0, 5.0]) == 2
