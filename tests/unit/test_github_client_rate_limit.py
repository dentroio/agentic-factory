"""Unit tests for status-site GitHub client rate-limit behaviour."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SITE = Path(__file__).resolve().parents[2] / "services" / "status-site"
sys.path.insert(0, str(SITE))

import github_client as gh  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_gh():
    gh.clear_rate_limit_for_tests()
    yield
    gh.clear_rate_limit_for_tests()


@pytest.mark.asyncio
async def test_rate_limit_403_returns_stale_and_trips_breaker():
    key_path = "/repos/dentroio/clarion/contents/docs/x"
    gh._cache[gh._cache_key(key_path, None)] = (0.0, {"ok": True})  # expired TTL, still stale

    resp = MagicMock()
    resp.status_code = 403
    resp.text = "API rate limit exceeded for user ID 1"
    resp.headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"}

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=resp)

    with patch("github_client.httpx.AsyncClient", return_value=mock_client):
        val = await gh._get(key_path, ttl=1)

    assert val == {"ok": True}
    assert gh.rate_limit_active()


@pytest.mark.asyncio
async def test_circuit_open_skips_network_when_stale_exists():
    key_path = "/repos/dentroio/clarion/pulls"
    params = {"state": "open", "per_page": 100}
    gh._cache[gh._cache_key(key_path, params)] = (0.0, [{"number": 1}])
    gh._trip_rate_limit(None)

    with patch("github_client.httpx.AsyncClient") as client_cls:
        val = await gh._get(key_path, params, ttl=1)
        client_cls.assert_not_called()

    assert val == [{"number": 1}]


@pytest.mark.asyncio
async def test_circuit_open_raises_without_stale():
    gh._trip_rate_limit(None)
    with pytest.raises(gh.GitHubRateLimited):
        await gh._get("/repos/x/y", ttl=1)
