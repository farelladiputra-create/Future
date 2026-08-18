"""Small numeric helpers.

Everything returns None rather than raising or substituting zero when the inputs
cannot support an answer. A missing metric propagates as missing all the way to
the report, where it prints as "no data" instead of a misleading figure.
"""

from __future__ import annotations

import math
from typing import Sequence


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def stdev(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    return math.sqrt(sum((v - avg) ** 2 for v in values) / (len(values) - 1))


def coefficient_of_variation(values: Sequence[float]) -> float | None:
    """Dispersion relative to level. Lower means steadier earning power."""
    avg = mean(values)
    dispersion = stdev(values)
    if avg is None or dispersion is None or avg == 0:
        return None
    return dispersion / abs(avg)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def cagr(values: Sequence[float], periods: int | None = None) -> float | None:
    """Compound growth from first to last value.

    Returns None when either endpoint is non-positive, because a compound rate
    across a sign change is arithmetically meaningless.
    """
    if len(values) < 2:
        return None
    start, end = values[0], values[-1]
    span = periods if periods is not None else len(values) - 1
    if span <= 0 or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1.0 / span) - 1.0


def yoy_growth(values: Sequence[float]) -> list[float]:
    """Year-over-year growth rates, skipping pairs with a non-positive base."""
    out: list[float] = []
    for prev, curr in zip(values, values[1:]):
        if prev > 0:
            out.append(curr / prev - 1.0)
    return out


def robust_growth(values: Sequence[float]) -> float | None:
    """A conservative growth estimate: the lower of endpoint CAGR and median YoY.

    Endpoint CAGR is hostage to whichever year happens to sit at each end, and
    median YoY ignores compounding. Taking the smaller of the two avoids
    extrapolating a cyclical peak.
    """
    compound = cagr(values)
    steps = median(yoy_growth(values))
    candidates = [c for c in (compound, steps) if c is not None]
    if not candidates:
        return None
    return min(candidates)


def trend_slope(values: Sequence[float]) -> float | None:
    """Ordinary least squares slope against period index, normalised by level."""
    n = len(values)
    if n < 3:
        return None
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return None
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values)) / denominator
    if y_mean == 0:
        return None
    return slope / abs(y_mean)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile, q in [0, 1]."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = clamp(q, 0.0, 1.0) * (len(ordered) - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def count_positive(values: Sequence[float]) -> int:
    return sum(1 for v in values if v > 0)


def is_finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)
