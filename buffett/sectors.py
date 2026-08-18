"""SIC code to sector mapping.

EDGAR tags every filer with a SIC code, which means sector classification comes
free with the fundamentals fetch and needs no commercial data vendor. The
buckets below are coarse on purpose: they exist for peer-multiple comparison and
sector concentration limits, not for index replication.
"""

from __future__ import annotations

# (inclusive low, inclusive high, sector)
_SIC_RANGES: list[tuple[int, int, str]] = [
    (100, 999, "Agriculture"),
    (1000, 1099, "Materials"),
    (1200, 1299, "Energy"),
    (1300, 1399, "Energy"),
    (1400, 1499, "Materials"),
    (1500, 1799, "Industrials"),
    (2000, 2199, "Consumer Staples"),
    (2200, 2299, "Consumer Discretionary"),
    (2300, 2399, "Consumer Discretionary"),
    (2400, 2599, "Industrials"),
    (2600, 2699, "Materials"),
    (2700, 2799, "Communication Services"),
    (2800, 2824, "Materials"),
    (2830, 2836, "Health Care"),
    (2840, 2899, "Materials"),
    (2900, 2999, "Energy"),
    (3000, 3099, "Consumer Discretionary"),
    (3100, 3199, "Consumer Discretionary"),
    (3200, 3299, "Materials"),
    (3300, 3399, "Materials"),
    (3400, 3499, "Industrials"),
    (3500, 3569, "Industrials"),
    (3570, 3579, "Information Technology"),
    (3580, 3599, "Industrials"),
    (3600, 3620, "Industrials"),
    (3621, 3629, "Industrials"),
    (3630, 3659, "Consumer Discretionary"),
    (3660, 3669, "Information Technology"),
    (3670, 3679, "Information Technology"),
    (3680, 3689, "Information Technology"),
    (3690, 3699, "Information Technology"),
    (3700, 3716, "Consumer Discretionary"),
    (3720, 3729, "Industrials"),
    (3730, 3799, "Industrials"),
    (3800, 3829, "Information Technology"),
    (3830, 3851, "Health Care"),
    (3860, 3899, "Consumer Discretionary"),
    (3900, 3999, "Consumer Discretionary"),
    (4000, 4099, "Industrials"),
    (4100, 4199, "Industrials"),
    (4200, 4299, "Industrials"),
    (4400, 4499, "Industrials"),
    (4500, 4599, "Industrials"),
    (4600, 4699, "Energy"),
    (4700, 4799, "Industrials"),
    (4800, 4899, "Communication Services"),
    (4900, 4999, "Utilities"),
    (5000, 5199, "Industrials"),
    (5200, 5299, "Consumer Discretionary"),
    (5300, 5399, "Consumer Discretionary"),
    (5400, 5499, "Consumer Staples"),
    (5500, 5599, "Consumer Discretionary"),
    (5600, 5699, "Consumer Discretionary"),
    (5700, 5799, "Consumer Discretionary"),
    (5800, 5899, "Consumer Discretionary"),
    (5900, 5912, "Consumer Staples"),
    (5920, 5999, "Consumer Discretionary"),
    (6000, 6199, "Financials"),
    (6200, 6299, "Financials"),
    (6300, 6411, "Financials"),
    (6500, 6599, "Real Estate"),
    (6700, 6770, "Financials"),
    (6790, 6799, "Financials"),
    (6798, 6798, "Real Estate"),
    (7000, 7099, "Consumer Discretionary"),
    (7200, 7299, "Consumer Discretionary"),
    (7300, 7349, "Industrials"),
    (7350, 7359, "Industrials"),
    (7360, 7379, "Information Technology"),
    (7380, 7389, "Industrials"),
    (7390, 7399, "Industrials"),
    (7500, 7599, "Consumer Discretionary"),
    (7600, 7699, "Consumer Discretionary"),
    (7800, 7899, "Communication Services"),
    (7900, 7999, "Communication Services"),
    (8000, 8099, "Health Care"),
    (8100, 8199, "Financials"),
    (8200, 8299, "Consumer Discretionary"),
    (8300, 8399, "Health Care"),
    (8600, 8699, "Industrials"),
    (8700, 8799, "Industrials"),
    (8800, 8899, "Industrials"),
    (9000, 9999, "Industrials"),
]

# Sectors whose accounting makes the standard toolkit misleading. Book value
# dominates for lenders, and capex-based owner earnings breaks down for them, so
# the engine flags rather than silently mis-values.
BOOK_VALUE_SECTORS = {"Financials", "Real Estate"}

# Peer multiples used only when a filer has too little history for its own
# 5-year median. Sourced from long-run market averages, not a live feed, and
# labelled as such wherever they reach the report.
_FALLBACK_PE: dict[str, float] = {
    "Information Technology": 20.0,
    "Health Care": 17.0,
    "Financials": 12.0,
    "Real Estate": 14.0,
    "Consumer Discretionary": 17.0,
    "Consumer Staples": 18.0,
    "Industrials": 17.0,
    "Energy": 12.0,
    "Materials": 14.0,
    "Utilities": 16.0,
    "Communication Services": 16.0,
    "Agriculture": 14.0,
}

DEFAULT_SECTOR = "Unknown"
DEFAULT_FALLBACK_PE = 15.0


def sector_for_sic(sic: int | str | None) -> str:
    """Map a SIC code to a coarse sector bucket."""
    if sic is None or sic == "":
        return DEFAULT_SECTOR
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return DEFAULT_SECTOR
    for low, high, sector in _SIC_RANGES:
        if low <= code <= high:
            return sector
    return DEFAULT_SECTOR


def is_book_value_business(sector: str) -> bool:
    """True for lenders and property owners, where P/B beats P/E and DCF."""
    return sector in BOOK_VALUE_SECTORS


def fallback_pe(sector: str) -> float:
    """Long-run average multiple for a sector, used only as a last resort."""
    return _FALLBACK_PE.get(sector, DEFAULT_FALLBACK_PE)
