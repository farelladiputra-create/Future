"""Screening universe.

Defaults to the S&P 500, which is a defensible starting pool: large, liquid,
audited under US GAAP, and deep enough that a strict value screen still finds
something most evenings. The list is fetched rather than bundled so it does not
silently drift out of date, and cached with a long TTL so one bad night does
not break the run.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path

from ..config import UniverseConfig
from ..net import FetchError, HttpClient

log = logging.getLogger(__name__)

SP500_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "main/data/constituents.csv"
)
SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Constituent lists change a handful of times a year.
_UNIVERSE_TTL = 7 * 24 * 3600


def _normalise(ticker: str) -> str:
    """EDGAR and Yahoo both use dashes where the index uses dots (BRK.B)."""
    return ticker.strip().upper().replace(".", "-")


def _from_csv(body: str) -> list[str]:
    reader = csv.DictReader(io.StringIO(body))
    out: list[str] = []
    for row in reader:
        symbol = row.get("Symbol") or row.get("symbol") or ""
        if symbol:
            out.append(_normalise(symbol))
    return out


def _from_wikipedia(body: str) -> list[str]:
    """Pull symbols from the constituents table as a fallback."""
    # The first sortable wikitable on the page is the constituent list; symbols
    # sit in the first cell of each row, linked to their exchange listing.
    table_match = re.search(
        r'<table[^>]*id="constituents".*?</table>', body, re.DOTALL
    )
    section = table_match.group(0) if table_match else body
    symbols = re.findall(
        r'<td[^>]*>\s*<a[^>]*rel="nofollow"[^>]*>([A-Z][A-Z.\-]{0,8})</a>', section
    )
    if not symbols:
        symbols = re.findall(r'<td[^>]*><a[^>]*>([A-Z][A-Z.\-]{0,8})</a>\s*</td>', section)
    seen: set[str] = set()
    out: list[str] = []
    for symbol in symbols:
        norm = _normalise(symbol)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def load_sp500(client: HttpClient) -> list[str]:
    try:
        body = client.get_text(SP500_CSV_URL, namespace="universe", ttl=_UNIVERSE_TTL)
        tickers = _from_csv(body)
        if len(tickers) >= 400:
            return tickers
        log.warning("S&P 500 CSV returned only %d symbols, trying Wikipedia", len(tickers))
    except FetchError as exc:
        log.warning("S&P 500 CSV unavailable (%s), trying Wikipedia", exc)

    body = client.get_text(SP500_WIKI_URL, namespace="universe", ttl=_UNIVERSE_TTL)
    tickers = _from_wikipedia(body)
    if len(tickers) < 400:
        raise FetchError(
            f"could not assemble a plausible S&P 500 list (got {len(tickers)} symbols)"
        )
    return tickers


def load_from_file(path: str | Path) -> list[str]:
    """One ticker per line, or a CSV with a Symbol column. `#` comments allowed."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and "," in lines[0]:
        parsed = _from_csv(text)
        if parsed:
            return parsed
    out: list[str] = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if line:
            out.append(_normalise(line))
    return out


def build_universe(client: HttpClient, cfg: UniverseConfig) -> list[str]:
    """Resolve the configured universe to a de-duplicated ticker list."""
    if cfg.source == "inline":
        tickers = [_normalise(t) for t in cfg.tickers]
    elif cfg.source == "sp500":
        tickers = load_sp500(client)
    elif cfg.source.startswith("file:"):
        tickers = load_from_file(cfg.source.removeprefix("file:"))
    else:
        raise ValueError(
            f"unknown universe source: {cfg.source!r} (use sp500, inline, or file:PATH)"
        )

    excluded = {_normalise(t) for t in cfg.exclude_tickers}
    seen: set[str] = set()
    out: list[str] = []
    for ticker in tickers:
        if ticker in excluded or ticker in seen:
            continue
        seen.add(ticker)
        out.append(ticker)
    return out[: cfg.max_tickers]
