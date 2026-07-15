"""Wire the agent loop to real collaborators: LLM client, budget, sandbox.

`run_agent` is the single entrypoint the worker and the CLI both call. It stays
thin and fully injectable (emitter, on_call logger, sandbox) so callers choose
where events/prompts go — Postgres+Redis in the worker, stdout in the CLI — and
so tests can drive it with fakes.
"""

import re
from urllib.parse import urlsplit

from app.agent.loop import AgentLoop, AgentOutcome
from app.llm.budget import TokenBudget
from app.llm.client import LLMClient, build_providers
from app.sandbox import SandboxResult, run_extractor


def build_context(url: str, capture_result, distilled) -> dict:
    """Assemble the page context the agent loop reasons over."""
    return {
        "url": url,
        "skeleton": distilled.skeleton,
        "html": capture_result.final_html,
        "xhr": capture_result.xhr,
        "structures": distilled.structures,
        "meta": distilled.meta,
    }


def make_slug(url: str) -> str:
    """A stable, human-readable id for the endpoint, e.g. books-toscrape-com-catalogue."""
    parts = urlsplit(url)
    host = (parts.hostname or "site").removeprefix("www.")
    first_seg = next((s for s in parts.path.split("/") if s), "")
    raw = f"{host}-{first_seg}" if first_seg else host
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug[:120] or "extractor"


def _threaded_sandbox(memory_mb: int):
    def _run(code: str, source: str, timeout: int) -> SandboxResult:
        return run_extractor(code, source, timeout=timeout, memory_mb=memory_mb)

    return _run


async def run_agent(
    *,
    context: dict,
    settings,
    http,
    emitter,
    on_call=None,
    sandbox=None,
) -> AgentOutcome:
    providers = build_providers(settings)
    if not providers:
        raise RuntimeError("no LLM provider configured (set GROQ_API_KEY or GEMINI_API_KEY)")

    client = LLMClient(
        providers,
        budget=TokenBudget(limit=settings.job_token_budget),
        http=http,
        on_call=on_call,
    )
    loop = AgentLoop(
        client,
        emitter,
        sandbox or _threaded_sandbox(settings.sandbox_memory_mb),
        max_repairs=settings.max_repairs,
        sandbox_timeout=settings.sandbox_timeout_s,
    )
    return await loop.run(context)
