"""HTTP client with a mandatory contact User-Agent, a rate limit and retries (stdlib only)."""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable

Transport = Callable[[str, dict[str, str]], tuple[int, bytes]]

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class HttpError(RuntimeError):
    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.url = url
        self.status = status


def urllib_transport(url: str, headers: dict[str, str], timeout: float = 30.0) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def user_agent_from_env() -> str:
    agent = os.environ.get("EQUITY_RESEARCH_USER_AGENT", "").strip()
    if not agent:
        raise RuntimeError(
            "EQUITY_RESEARCH_USER_AGENT is not set; SEC requires a User-Agent with a contact e-mail, "
            "e.g. 'equity-research name@example.com'"
        )
    return agent


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        transport: Transport = urllib_transport,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_per_second: float = 10.0,
        retries: int = 3,
        backoff: float = 1.0,
    ) -> None:
        if "@" not in user_agent:
            raise ValueError("User-Agent must contain a contact e-mail address (SEC fair-access policy)")
        self._user_agent = user_agent
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self._interval = 1.0 / max_per_second
        self._retries = retries
        self._backoff = backoff
        self._last: float | None = None

    def _throttle(self) -> None:
        if self._last is not None:
            wait = self._last + self._interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def get(self, url: str) -> bytes:
        headers = {"User-Agent": self._user_agent, "Accept-Encoding": "identity"}
        for attempt in range(self._retries + 1):
            self._throttle()
            status, body = self._transport(url, headers)
            if 200 <= status < 300:
                return body
            if status not in RETRY_STATUSES or attempt == self._retries:
                raise HttpError(url, status)
            self._sleep(self._backoff * 2**attempt)
        raise AssertionError("unreachable")
