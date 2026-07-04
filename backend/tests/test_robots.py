"""Tests for robots.txt policy: allow/disallow verdicts and conservative failure handling."""

import httpx
import pytest
import respx

from app.ingestion.robots import check_robots

UA = "LazarusBot/0.1 (+https://example.dev/about)"


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=5)


@pytest.fixture
def mocked():
    with respx.mock(assert_all_called=False) as router:
        yield router


async def test_disallowed_path_is_rejected_with_reason(mocked):
    mocked.get("https://site.test/robots.txt").respond(
        200, text="User-agent: *\nDisallow: /private/\n"
    )
    async with client() as http:
        verdict = await check_robots("https://site.test/private/page", user_agent=UA, client=http)
    assert verdict.allowed is False
    assert verdict.status == "disallowed"
    assert "robots.txt" in verdict.reason


async def test_allowed_path_passes(mocked):
    mocked.get("https://site.test/robots.txt").respond(
        200, text="User-agent: *\nDisallow: /private/\n"
    )
    async with client() as http:
        verdict = await check_robots("https://site.test/public/page", user_agent=UA, client=http)
    assert verdict.allowed is True
    assert verdict.status == "allowed"


async def test_wildcard_rules_are_honoured(mocked):
    mocked.get("https://site.test/robots.txt").respond(
        200, text="User-agent: *\nDisallow: /search*\n"
    )
    async with client() as http:
        verdict = await check_robots(
            "https://site.test/search-results?q=x", user_agent=UA, client=http
        )
    assert verdict.allowed is False


async def test_missing_robots_means_allowed(mocked):
    mocked.get("https://site.test/robots.txt").respond(404)
    async with client() as http:
        verdict = await check_robots("https://site.test/page", user_agent=UA, client=http)
    assert verdict.allowed is True
    assert verdict.status == "no_robots"


async def test_server_error_is_conservatively_rejected(mocked):
    mocked.get("https://site.test/robots.txt").respond(503)
    async with client() as http:
        verdict = await check_robots("https://site.test/page", user_agent=UA, client=http)
    assert verdict.allowed is False
    assert verdict.status == "unavailable"


async def test_network_failure_is_conservatively_rejected(mocked):
    mocked.get("https://site.test/robots.txt").mock(side_effect=httpx.ConnectTimeout("boom"))
    async with client() as http:
        verdict = await check_robots("https://site.test/page", user_agent=UA, client=http)
    assert verdict.allowed is False
    assert verdict.status == "unavailable"
    assert verdict.reason
