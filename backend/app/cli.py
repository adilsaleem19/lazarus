"""python -m app.cli <url> — run the full agent pipeline from the terminal.

Self-contained on purpose: it needs an LLM key and a Chromium install, but no
Postgres or Redis. Events print to stdout so you can watch the agent think while
developing, without standing up the whole stack.
"""

import asyncio
import json
import sys

import httpx

from app.agent.service import build_context, run_agent
from app.config import Settings
from app.ingestion.capture import capture_page
from app.ingestion.distill import distill
from app.ingestion.robots import check_robots
from app.ingestion.urlguard import validate_target_url


class ConsoleEmitter:
    """A print-only Emitter — the CLI's stand-in for the DB+Redis event stream."""

    def __init__(self) -> None:
        self._seq = 0

    async def emit(self, kind: str, message: str, data: dict | None = None) -> None:
        self._seq += 1
        print(f"    [{self._seq:02d}] {kind:16} {message}")


async def _run(url: str) -> int:
    settings = Settings()
    if not settings.llm_configured:
        print("No LLM key set (GROQ_API_KEY or GEMINI_API_KEY). Aborting.")
        return 2

    print(f"→ Target: {url}")
    try:
        safe_url = validate_target_url(url)
    except Exception as exc:  # noqa: BLE001 — surface the guard's reason plainly
        print(f"✗ Rejected by URL guard: {exc}")
        return 1

    headers = {"User-Agent": settings.user_agent}
    async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=headers) as http:
        verdict = await check_robots(safe_url, user_agent=settings.user_agent, client=http)
        if not verdict.allowed:
            print(f"✗ Blocked by robots.txt: {verdict.reason}")
            return 1
        print("✓ robots.txt allows — capturing page…")

        result = await capture_page(safe_url, settings)
        distilled = distill(result.final_html, max_tokens=settings.max_skeleton_tokens)
        print(
            f"✓ Captured: {distilled.token_estimate} skeleton tokens, "
            f"{len(result.xhr)} XHR response(s), {len(distilled.structures)} structure(s)"
        )

        print("→ Agent reasoning:")
        context = build_context(safe_url, result, distilled)
        calls: list[dict] = []
        outcome = await run_agent(
            context=context,
            settings=settings,
            http=http,
            emitter=ConsoleEmitter(),
            on_call=calls.append,
        )

    tokens = sum(c["total_tokens"] for c in calls)
    print()
    if outcome.ok:
        records = outcome.records or []
        print(
            f"✓ SUCCESS via {outcome.strategy} strategy after {outcome.repair_count} "
            f"repair(s) — {len(records)} records, {tokens} tokens used."
        )
        print("\n--- extractor code ---")
        print(outcome.code)
        print("\n--- sample records ---")
        for record in records[:3]:
            print("  " + json.dumps(record, ensure_ascii=False))
        return 0

    print(f"✗ FAILED: {outcome.reason} ({tokens} tokens used).")
    return 1


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m app.cli <url>")
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_run(sys.argv[1])))


if __name__ == "__main__":
    main()
