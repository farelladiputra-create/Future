"""Daily price history.

Yahoo's chart endpoint is the primary source and needs no key. Stooq serves as
a fallback because Yahoo periodically tightens access, and a briefing that
silently reports a stale price is worse than one that reports none.
"""

from __future__ import annotations

import csv
import io
import logging
import math
from datetime import date, datetime, timezone

from ..models import PriceHistory
from ..net import FetchError, HttpClient

log = logging.getLogger(__name__)

YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    "?range={range}&interval=1d&includeAdjustedClose=true"
)
STOOQ_CSV_URL = "https://stooq.com/q/d/l/?s={ticker}.us&i=d"

# Yahoo rejects clients that look automated.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

TRADING_DAYS_PER_YEAR = 252


def _range_for(days: int) -> str:
    for threshold, label in ((370, "1y"), (740, "2y"), (1850, "5y")):
        if days <= threshold:
            return label
    return "10y"


def fetch_prices_yahoo(client: HttpClient, ticker: str, days: int) -> PriceHistory:
    url = YAHOO_CHART_URL.format(ticker=ticker, range=_range_for(days))
    payload = client.get_json(
        url, namespace="prices-yahoo", headers={"User-Agent": _BROWSER_UA}
    )
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise FetchError(f"yahoo error for {ticker}: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise FetchError(f"yahoo returned no result for {ticker}")

    result = results[0]
    stamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose")
    raw = (indicators.get("quote") or [{}])[0].get("close")
    closes = adjusted if adjusted else raw
    if not stamps or not closes:
        raise FetchError(f"yahoo returned no closes for {ticker}")

    history = PriceHistory(source="yahoo")
    for stamp, close in zip(stamps, closes):
        if stamp is None or close is None or not math.isfinite(float(close)):
            continue
        history.dates.append(
            datetime.fromtimestamp(int(stamp), tz=timezone.utc).date()
        )
        history.closes.append(float(close))
    if not history.closes:
        raise FetchError(f"yahoo closes all null for {ticker}")
    return history


def fetch_prices_stooq(client: HttpClient, ticker: str, days: int) -> PriceHistory:
    body = client.get_text(
        STOOQ_CSV_URL.format(ticker=ticker.lower().replace(".", "-")),
        namespace="prices-stooq",
    )
    reader = csv.DictReader(io.StringIO(body))
    history = PriceHistory(source="stooq")
    for row in reader:
        raw_date, raw_close = row.get("Date"), row.get("Close")
        if not raw_date or not raw_close:
            continue
        try:
            when = datetime.strptime(raw_date, "%Y-%m-%d").date()
            close = float(raw_close)
        except ValueError:
            continue
        history.dates.append(when)
        history.closes.append(close)
    if not history.closes:
        raise FetchError(f"stooq returned no rows for {ticker}")
    # Stooq serves full history; trim to the requested window.
    history.dates = history.dates[-days:]
    history.closes = history.closes[-days:]
    return history


def fetch_prices(client: HttpClient, ticker: str, days: int) -> PriceHistory:
    """Price history from Yahoo, falling back to Stooq."""
    try:
        return fetch_prices_yahoo(client, ticker, days)
    except FetchError as exc:
        log.debug("yahoo failed for %s (%s), trying stooq", ticker, exc)
        return fetch_prices_stooq(client, ticker, days)


# ---- derived price statistics ------------------------------------------


def annualized_volatility(closes: list[float]) -> float | None:
    """Realised annualised volatility of daily log returns."""
    if len(closes) < 30:
        return None
    returns = []
    for prev, curr in zip(closes, closes[1:]):
        if prev > 0 and curr > 0:
            returns.append(math.log(curr / prev))
    if len(returns) < 20:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR)


def drawdown_from_high(closes: list[float]) -> float | None:
    """Current decline from the highest close in the window, as a fraction."""
    if not closes:
        return None
    peak = max(closes)
    if peak <= 0:
        return None
    return (peak - closes[-1]) / peak


def fifty_two_week_range(history: PriceHistory) -> tuple[float, float] | None:
    window = history.window(TRADING_DAYS_PER_YEAR)
    if not window:
        return None
    return min(window), max(window)


def total_return(closes: list[float]) -> float | None:
    if len(closes) < 2 or closes[0] <= 0:
        return None
    return closes[-1] / closes[0] - 1.0


def price_at_fiscal_year_ends(
    history: PriceHistory, period_ends: list[date]
) -> dict[date, float]:
    """Closing price at each fiscal year end, for historical multiple series."""
    out: dict[date, float] = {}
    for when in period_ends:
        close = history.close_on_or_before(when)
        if close is not None:
            out[when] = close
    return out
