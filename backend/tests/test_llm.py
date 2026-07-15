"""Tests for the provider-agnostic LLM client: fallback, budget, backoff, logging."""

import httpx
import pytest

from app.llm.budget import BudgetExceeded, TokenBudget
from app.llm.client import AllProvidersFailed, LLMClient, LLMMessage, ProviderConfig


def ok_response(text: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
    )


def groq(**kw) -> ProviderConfig:
    return ProviderConfig(
        name="groq", base_url="https://groq.test/openai/v1", api_key="k", model="llama-x", **kw
    )


def gemini(**kw) -> ProviderConfig:
    return ProviderConfig(
        name="gemini", base_url="https://gemini.test/v1", api_key="k2", model="flash-x", **kw
    )


class TestBudget:
    def test_charges_and_reports_remaining(self):
        b = TokenBudget(limit=100)
        b.charge(30)
        assert b.spent == 30
        assert b.remaining == 70

    def test_raises_when_exceeded(self):
        b = TokenBudget(limit=50)
        with pytest.raises(BudgetExceeded):
            b.charge(60)

    def test_precheck_blocks_before_call(self):
        b = TokenBudget(limit=50)
        b.charge(45)
        assert b.can_afford(4) is True
        assert b.can_afford(10) is False


class TestClientHappyPath:
    async def test_returns_content_and_charges_budget(self):
        budget = TokenBudget(limit=1000)
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return ok_response("hello", prompt_tokens=12, completion_tokens=8)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = LLMClient([groq()], budget=budget, http=http)
            result = await client.complete([LLMMessage(role="user", content="hi")])

        assert result.content == "hello"
        assert result.provider == "groq"
        assert budget.spent == 20
        assert len(calls) == 1

    async def test_sends_bearer_auth_and_model(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization")
            import json as _json

            seen["body"] = _json.loads(request.content)
            return ok_response("x")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = LLMClient([groq()], budget=TokenBudget(limit=1000), http=http)
            await client.complete([LLMMessage(role="user", content="hi")])

        assert seen["auth"] == "Bearer k"
        assert seen["body"]["model"] == "llama-x"


class TestFallback:
    async def test_falls_back_to_second_provider_on_persistent_429(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "groq.test" in str(request.url):
                return httpx.Response(429, json={"error": "rate limited"})
            return ok_response("from gemini")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = LLMClient(
                [groq(max_retries=1), gemini()],
                budget=TokenBudget(limit=1000),
                http=http,
                backoff_base=0,
            )
            result = await client.complete([LLMMessage(role="user", content="hi")])

        assert result.content == "from gemini"
        assert result.provider == "gemini"

    async def test_retries_same_provider_then_succeeds(self):
        state = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(429, json={"error": "slow down"})
            return ok_response("recovered")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = LLMClient(
                [groq(max_retries=3)],
                budget=TokenBudget(limit=1000),
                http=http,
                backoff_base=0,
            )
            result = await client.complete([LLMMessage(role="user", content="hi")])

        assert result.content == "recovered"
        assert state["n"] == 2

    async def test_raises_when_all_providers_fail(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = LLMClient(
                [groq(max_retries=1), gemini(max_retries=1)],
                budget=TokenBudget(limit=1000),
                http=http,
                backoff_base=0,
            )
            with pytest.raises(AllProvidersFailed):
                await client.complete([LLMMessage(role="user", content="hi")])


class TestBudgetIntegration:
    async def test_refuses_call_when_budget_cannot_cover_estimate(self):
        budget = TokenBudget(limit=5)  # tiny

        def handler(request: httpx.Request) -> httpx.Response:
            return ok_response("should not happen")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = LLMClient([groq()], budget=budget, http=http)
            with pytest.raises(BudgetExceeded):
                await client.complete(
                    [LLMMessage(role="user", content="x" * 4000)], estimated_completion=100
                )


class TestLogging:
    async def test_invokes_call_logger_with_provider_and_usage(self):
        logged = []

        def handler(request: httpx.Request) -> httpx.Response:
            return ok_response("hi", prompt_tokens=7, completion_tokens=3)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = LLMClient(
                [groq()],
                budget=TokenBudget(limit=1000),
                http=http,
                on_call=lambda rec: logged.append(rec),
            )
            await client.complete([LLMMessage(role="user", content="hi")], purpose="strategy")

        assert len(logged) == 1
        assert logged[0]["provider"] == "groq"
        assert logged[0]["purpose"] == "strategy"
        assert logged[0]["total_tokens"] == 10
