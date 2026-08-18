"""Number, currency and date formatting in Indonesian conventions.

Thousands separated by dots, decimals by commas, short month names in Bahasa
Indonesia. Amounts stay in USD because that is what the filings report; an IDR
figure only appears when a conversion rate has been supplied, never estimated.
"""

from __future__ import annotations

from datetime import date

MONTHS_ID = (
    "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
)

# What a missing value renders as. Never a zero, never a dash that could read as
# a real figure.
MISSING = "tidak ada info"


def number(value: float | None, decimals: int = 2) -> str:
    """1234567.891 -> '1.234.567,89'"""
    if value is None:
        return MISSING
    if value != value or value in (float("inf"), float("-inf")):
        return MISSING
    formatted = f"{value:,.{decimals}f}"
    # en-US separators to Indonesian: swap via a placeholder so the two do not
    # collide mid-replacement.
    return formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def percent(value: float | None, decimals: int = 1) -> str:
    """0.1234 -> '12,3%'"""
    if value is None:
        return MISSING
    return f"{number(value * 100, decimals)}%"


def usd(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return MISSING
    return f"US$ {number(value, decimals)}"


def usd_compact(value: float | None) -> str:
    """Market-cap scale amounts: 'US$ 12,34 B'."""
    if value is None:
        return MISSING
    for cutoff, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= cutoff:
            return f"US$ {number(value / cutoff, 2)} {suffix}"
    return usd(value, 0)


def multiple(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return MISSING
    if value == float("inf"):
        return "tanpa beban bunga"
    return f"{number(value, decimals)}x"


def idr(value: float | None, rate: float | None) -> str | None:
    """USD converted at a rate the user supplied. None when no rate is set."""
    if value is None or rate is None:
        return None
    return f"Rp {number(value * rate, 0)}"


def day(value: date | None) -> str:
    """date(2026, 8, 17) -> '17 Agu 2026'"""
    if value is None:
        return MISSING
    return f"{value.day} {MONTHS_ID[value.month - 1]} {value.year}"


def signed_percent(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return MISSING
    sign = "+" if value > 0 else ""
    return f"{sign}{number(value * 100, decimals)}%"


def truncate(text: str, limit: int = 34) -> str:
    """Shorten in code rather than letting CSS decide where to cut."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def verdict_label(verdict: str) -> str:
    return {"buy": "BELI", "watch": "PANTAU", "pass": "LEWATI"}.get(
        verdict.lower(), verdict.upper()
    )


def conviction_label(conviction: str) -> str:
    return {"high": "tinggi", "medium": "sedang", "low": "rendah"}.get(
        conviction.lower(), conviction
    )


def zone_label(zone: str) -> str:
    return {
        "safe": "aman",
        "grey": "abu-abu",
        "distress": "tertekan",
        "unknown": MISSING,
    }.get(zone, zone)
