"""HTTP fetching with on-disk caching, polite rate limiting and backoff.

The nightly job hits SEC EDGAR a few hundred times. EDGAR publishes a 10
requests/second ceiling and blocks clients without a contact User-Agent, so
this module throttles, identifies itself, and caches aggressively: fundamentals
change quarterly, there is no reason to re-download them every evening.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

# EDGAR allows 10 req/s. Half that leaves headroom and still screens the S&P
# 500 in a couple of minutes.
_SEC_MIN_INTERVAL = 0.21


class RateLimiter:
    """Process-wide minimum spacing between requests to one host."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()


class FetchError(RuntimeError):
    """Raised when a URL cannot be retrieved after exhausting retries."""


class HttpClient:
    def __init__(
        self,
        cache_dir: str | Path,
        cache_ttl_hours: float,
        user_agent: str,
        timeout: float = 30.0,
        max_retries: int = 4,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = cache_ttl_hours * 3600.0
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        self._session = requests.Session()
        self._limiters: dict[str, RateLimiter] = {
            "data.sec.gov": RateLimiter(_SEC_MIN_INTERVAL),
            "www.sec.gov": RateLimiter(_SEC_MIN_INTERVAL),
        }
        self._default_limiter = RateLimiter(0.05)
        self._lock = threading.Lock()

    # ---- cache ---------------------------------------------------------

    def _cache_path(self, url: str, namespace: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        bucket = self.cache_dir / namespace
        bucket.mkdir(parents=True, exist_ok=True)
        return bucket / f"{digest}.json"

    def _read_cache(self, path: Path, ttl: float | None) -> Any | None:
        if not path.exists():
            return None
        effective_ttl = self.cache_ttl if ttl is None else ttl
        if effective_ttl >= 0 and time.time() - path.stat().st_mtime > effective_ttl:
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, OSError):
            # A truncated cache entry is not worth a crash; refetch instead.
            return None

    def _write_cache(self, path: Path, payload: Any) -> None:
        tmp = path.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            tmp.replace(path)
        except OSError as exc:
            log.debug("cache write failed for %s: %s", path, exc)

    # ---- fetching ------------------------------------------------------

    def _limiter_for(self, url: str) -> RateLimiter:
        host = url.split("/")[2] if "://" in url else ""
        with self._lock:
            return self._limiters.get(host, self._default_limiter)

    def get_text(
        self,
        url: str,
        *,
        namespace: str = "raw",
        headers: dict[str, str] | None = None,
        ttl: float | None = None,
        cache: bool = True,
    ) -> str:
        """GET a URL as text, serving from cache when fresh."""
        path = self._cache_path(url, namespace)
        if cache:
            cached = self._read_cache(path, ttl)
            if cached is not None:
                return cached["body"]

        request_headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
        if headers:
            request_headers.update(headers)

        limiter = self._limiter_for(url)
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            limiter.wait()
            try:
                response = self._session.get(
                    url, headers=request_headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code == 200:
                    if cache:
                        self._write_cache(path, {"body": response.text, "url": url})
                    return response.text
                if response.status_code == 404:
                    # A missing filer or delisted ticker is expected, not an error
                    # worth retrying three more times.
                    raise FetchError(f"404 for {url}")
                if response.status_code in (403, 407):
                    # Egress policy denial. Retrying will not change the answer.
                    raise FetchError(
                        f"{response.status_code} for {url} (blocked by network policy)"
                    )
                last_error = FetchError(f"HTTP {response.status_code} for {url}")
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise last_error

            # Exponential backoff with jitter so parallel workers desynchronise.
            sleep_for = (2**attempt) + random.uniform(0, 0.5)
            log.debug("retry %d for %s in %.1fs", attempt + 1, url, sleep_for)
            time.sleep(sleep_for)

        raise FetchError(f"failed after {self.max_retries} attempts: {url}") from last_error

    def get_json(
        self,
        url: str,
        *,
        namespace: str = "json",
        headers: dict[str, str] | None = None,
        ttl: float | None = None,
        cache: bool = True,
    ) -> Any:
        body = self.get_text(
            url, namespace=namespace, headers=headers, ttl=ttl, cache=cache
        )
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise FetchError(f"invalid JSON from {url}: {exc}") from exc
