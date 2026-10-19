"""Thin client for the public JSON API behind www.cse.lk.

The API is undocumented. Every call here is read-only and needs no login.
We keep the request rate low and retry transient failures.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

BASE_URL = "https://www.cse.lk/api/"
USER_AGENT = "cse-lab/0.1 (personal research collector; low request rate)"

# Endpoints that only answer GET; everything else is POST with an empty body.
GET_ENDPOINTS = {"allSecurityCode", "cntSecurity", "notifications"}


class CSEError(RuntimeError):
    """Raised when the CSE API returns an unusable response."""


class CSEClient:
    def __init__(self, min_interval: float = 0.35, timeout: float = 45.0) -> None:
        self._min_interval = min_interval
        self._last_call = 0.0
        self._http = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "CSEClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError, CSEError)),
    )
    def fetch(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Call one endpoint and return its parsed JSON."""
        self._throttle()
        if endpoint in GET_ENDPOINTS:
            resp = self._http.get(endpoint, params=params)
        else:
            resp = self._http.post(endpoint, params=params)
        if resp.status_code >= 500 or resp.status_code == 429:
            resp.raise_for_status()
        if resp.status_code != 200:
            # Other 4xx errors (bad symbol, removed endpoint) will not improve on retry.
            raise NonRetryableError(f"{endpoint}: HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise CSEError(f"{endpoint}: response was not JSON") from exc


class NonRetryableError(RuntimeError):
    """A client error that retrying will not fix."""
