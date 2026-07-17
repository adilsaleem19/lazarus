"""End-to-end tests for agent.service.run_agent with a mocked LLM transport:
the full path providers -> client -> loop -> sandbox -> describe call."""

import json

import httpx
import pytest

from app.agent.service import make_slug, run_agent
from app.config import Settings
from app.sandbox import SandboxResult

STRATEGY = {"strategy": "html", "reasoning": "no xhr", "target": "html"}
CODEGEN = {
    "code": "def extract(html):\n    return [{'title': 'A'}]",
    "schema": {"fields": [{"name": "title", "type": "string", "required": True}]},
}
DESCRIPTION = "Latest article titles extracted from site.test, refreshed periodically."


def scripted_transport(bodies: list[str]) -> httpx.MockTransport:
    responses = iter(bodies)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": next(responses)}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            },
        )

    return httpx.MockTransport(handler)


class NullEmitter:
    async def emit(self, kind, message, data=None):
        pass


def ok_sandbox(code, source, timeout=10):
    return SandboxResult(ok=True, records=[{"title": "A"}], error=None)


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url="sqlite+aiosqlite://", groq_api_key="test-key")


CTX = {
    "url": "https://site.test/page",
    "skeleton": "<div><h1>A</h1></div>",
    "html": "<div><h1>A</h1></div>",
    "xhr": [],
    "structures": [],
    "meta": {"title": "Site"},
}


async def test_successful_run_gets_an_llm_description(settings):
    transport = scripted_transport(
        [json.dumps(STRATEGY), json.dumps(CODEGEN), DESCRIPTION]
    )
    async with httpx.AsyncClient(transport=transport) as http:
        outcome = await run_agent(
            context=dict(CTX), settings=settings, http=http,
            emitter=NullEmitter(), sandbox=ok_sandbox,
        )
    assert outcome.ok is True
    assert outcome.records == [{"title": "A"}]
    assert outcome.description == DESCRIPTION


async def test_description_failure_does_not_fail_the_run(settings):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            content = json.dumps(STRATEGY if calls["n"] == 1 else CODEGEN)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": content}}],
                    "usage": {"total_tokens": 70},
                },
            )
        return httpx.Response(400, json={"error": "nope"})  # describe call blows up

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        outcome = await run_agent(
            context=dict(CTX), settings=settings, http=http,
            emitter=NullEmitter(), sandbox=ok_sandbox,
        )
    assert outcome.ok is True
    assert outcome.description == ""


async def test_failed_run_skips_the_description_call(settings):
    seen_purposes: list[str] = []
    bad_codegen = json.dumps({"code": "def extract(h):\n    return []", "schema": {"fields": []}})
    transport = scripted_transport([json.dumps(STRATEGY)] + [bad_codegen] * 10)

    def empty_sandbox(code, source, timeout=10):
        return SandboxResult(ok=True, records=[], error=None)

    async with httpx.AsyncClient(transport=transport) as http:
        outcome = await run_agent(
            context=dict(CTX), settings=settings, http=http,
            emitter=NullEmitter(), sandbox=empty_sandbox,
            on_call=lambda c: seen_purposes.append(c["purpose"]),
        )
    assert outcome.ok is False
    assert "describe" not in seen_purposes


class TestMakeSlug:
    def test_host_and_first_segment(self):
        assert make_slug("https://books.toscrape.com/catalogue/page-1.html") == (
            "books-toscrape-com-catalogue"
        )

    def test_bare_host(self):
        assert make_slug("https://news.ycombinator.com/") == "news-ycombinator-com"

    def test_www_stripped(self):
        assert make_slug("https://www.example.com/things") == "example-com-things"
