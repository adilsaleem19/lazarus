"""Provider-agnostic LLM client over the OpenAI-compatible chat-completions API.

Both Groq (`/openai/v1`) and Gemini (`/v1beta/openai`) speak this dialect with
Bearer auth, so one client handles both. Providers are tried in order; each is
retried on 429/5xx with exponential backoff, then we fall through to the next.
Every call is charged against a shared per-job token budget and optionally logged.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import structlog

from app.llm.budget import BudgetExceeded, TokenBudget

log = structlog.get_logger()


class LLMError(Exception):
    pass


class AllProvidersFailed(LLMError):
    pass


@dataclass
class LLMMessage:
    role: str
    content: str


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str
    max_retries: int = 3
    temperature: float = 0.1


@dataclass
class LLMResult:
    content: str
    provider: str
    total_tokens: int
    prompt_tokens: int = 0
    completion_tokens: int = 0


CallLogger = Callable[[dict], None]


def _estimate_tokens(messages: list[LLMMessage]) -> int:
    return sum(len(m.content) for m in messages) // 4


class LLMClient:
    def __init__(
        self,
        providers: list[ProviderConfig],
        budget: TokenBudget,
        http: httpx.AsyncClient,
        *,
        backoff_base: float = 0.5,
        on_call: CallLogger | None = None,
    ):
        if not providers:
            raise ValueError("at least one provider is required")
        self._providers = providers
        self._budget = budget
        self._http = http
        self._backoff_base = backoff_base
        self._on_call = on_call

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        purpose: str = "",
        estimated_completion: int = 512,
        # Reasoning models (gpt-oss) spend part of this budget thinking before
        # answering; too tight a cap truncates the JSON answer mid-object.
        max_tokens: int = 2500,
    ) -> LLMResult:
        estimate = _estimate_tokens(messages) + estimated_completion
        if not self._budget.can_afford(estimate):
            raise BudgetExceeded(
                f"estimated {estimate} tokens would exceed remaining budget "
                f"{self._budget.remaining}"
            )

        errors: list[str] = []
        for provider in self._providers:
            try:
                return await self._try_provider(provider, messages, purpose, max_tokens)
            except _ProviderFailed as exc:
                errors.append(f"{provider.name}: {exc}")
                log.warning("llm_provider_failed", provider=provider.name, error=str(exc))
                continue
        raise AllProvidersFailed("; ".join(errors))

    async def _try_provider(
        self, provider: ProviderConfig, messages: list[LLMMessage], purpose: str, max_tokens: int
    ) -> LLMResult:
        payload = {
            "model": provider.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": provider.temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {provider.api_key}"}
        url = provider.base_url.rstrip("/") + "/chat/completions"

        last_error = "no attempts made"
        for attempt in range(provider.max_retries):
            try:
                response = await self._http.post(url, json=payload, headers=headers, timeout=45)
            except httpx.HTTPError as exc:
                last_error = f"transport error: {type(exc).__name__}"
                await self._sleep_backoff(attempt)
                continue

            if response.status_code == 200:
                return self._parse(provider, response, messages, purpose)

            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                await self._sleep_backoff(attempt)
                continue

            # 4xx other than 429: a bad request won't fix itself on retry
            raise _ProviderFailed(f"HTTP {response.status_code}: {response.text[:200]}")

        raise _ProviderFailed(last_error)

    def _parse(
        self,
        provider: ProviderConfig,
        response: httpx.Response,
        messages: list[LLMMessage],
        purpose: str,
    ) -> LLMResult:
        body = response.json()
        # Reasoning models may return null content when the token budget ran out
        # mid-thought; normalise so parsing fails cleanly instead of crashing.
        content = body["choices"][0]["message"]["content"] or ""
        usage = body.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", prompt_tokens + completion_tokens)

        self._budget.charge(total)

        if self._on_call is not None:
            self._on_call(
                {
                    "provider": provider.name,
                    "model": provider.model,
                    "purpose": purpose,
                    "prompt": "\n\n".join(f"[{m.role}] {m.content}" for m in messages),
                    "response": content,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total,
                }
            )

        return LLMResult(
            content=content,
            provider=provider.name,
            total_tokens=total,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def _sleep_backoff(self, attempt: int) -> None:
        if self._backoff_base <= 0:
            return
        await asyncio.sleep(self._backoff_base * (2**attempt))


class _ProviderFailed(Exception):
    pass


def build_providers(settings) -> list[ProviderConfig]:
    """Order providers by LAZARUS_LLM_PROVIDER, including only those with a key set."""
    catalog = {
        "groq": lambda: ProviderConfig(
            name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key=settings.groq_api_key,
            model=settings.groq_model,
        ),
        "gemini": lambda: ProviderConfig(
            name="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
        ),
    }
    preferred = settings.llm_provider
    order = [preferred] + [k for k in catalog if k != preferred]

    providers: list[ProviderConfig] = []
    for name in order:
        factory = catalog.get(name)
        if factory is None:
            continue
        config = factory()
        if config.api_key:
            providers.append(config)
    return providers
