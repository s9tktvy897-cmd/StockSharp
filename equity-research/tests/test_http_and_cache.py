from datetime import datetime, timedelta, timezone

import pytest

from equity_research.data.cache import DiskCache
from equity_research.data.http import HttpClient, HttpError, user_agent_from_env

from fakes import USER_AGENT, FakeClock, FakeTransport

URL = "https://example.test/x"


def _client(transport, clock=None, **kwargs):
    clock = clock or FakeClock()
    return HttpClient(USER_AGENT, transport=transport, clock=clock.clock, sleep=clock.sleep, **kwargs)


def test_user_agent_must_contain_contact():
    with pytest.raises(ValueError):
        HttpClient("no-contact")


def test_user_agent_from_env_is_required(monkeypatch):
    monkeypatch.delenv("EQUITY_RESEARCH_USER_AGENT", raising=False)
    with pytest.raises(RuntimeError):
        user_agent_from_env()


def test_sends_user_agent_header():
    transport = FakeTransport({URL: (200, b"ok")})
    assert _client(transport).get(URL) == b"ok"
    assert transport.calls[0][1]["User-Agent"] == USER_AGENT


def test_rate_limit_spaces_requests():
    clock = FakeClock()
    client = _client(FakeTransport({URL: (200, b"ok")}), clock=clock, max_per_second=10)
    client.get(URL)
    client.get(URL)
    assert clock.sleeps == [pytest.approx(0.1)]


def test_retries_on_429_then_succeeds():
    transport = FakeTransport({URL: [(429, b""), (200, b"ok")]})
    assert _client(transport).get(URL) == b"ok"
    assert len(transport.calls) == 2


def test_does_not_retry_404():
    transport = FakeTransport({})
    with pytest.raises(HttpError) as error:
        _client(transport).get(URL)
    assert error.value.status == 404
    assert len(transport.calls) == 1


def test_gives_up_after_retries():
    transport = FakeTransport({URL: (503, b"")})
    with pytest.raises(HttpError):
        _client(transport, retries=2).get(URL)
    assert len(transport.calls) == 3


def test_cache_hit_skips_download(tmp_path):
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    cache = DiskCache(tmp_path, now=lambda: now)
    downloads = []
    download = lambda url: downloads.append(url) or b"body"
    assert cache.fetch(URL, download, timedelta(days=1)) == (b"body", now)
    assert cache.fetch(URL, download, timedelta(days=1)) == (b"body", now)
    assert downloads == [URL]


def test_cache_expires(tmp_path):
    moments = [datetime(2026, 10, 1, tzinfo=timezone.utc)]
    cache = DiskCache(tmp_path, now=lambda: moments[0])
    cache.put(URL, b"old")
    moments[0] = datetime(2026, 10, 9, tzinfo=timezone.utc)
    assert cache.get(URL, timedelta(days=1)) is None
    assert cache.get(URL, None) is not None
