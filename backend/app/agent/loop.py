"""The autonomous core: strategy -> codegen -> sandbox -> validate -> self-repair.

Every step emits a structured event (the live reasoning stream). The loop is
provider/sandbox-agnostic: it takes an LLM with `.complete()`, an emitter with
`.emit()`, and a sandbox callable, so tests drive it with fakes and no real
browser, network, or subprocess.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.parsing import extract_json, parse_extractor_response
from app.agent.prompts import codegen_messages, repair_messages, strategy_messages
from app.agent.validation import validate_records
from app.sandbox import SandboxResult

SandboxRunner = Callable[..., SandboxResult]


@dataclass
class AgentOutcome:
    ok: bool
    strategy: str
    records: list[dict] | None = None
    code: str | None = None
    record_schema: dict | None = None
    repair_count: int = 0
    reason: str = ""
    events_data: dict[str, Any] = field(default_factory=dict)


class AgentLoop:
    def __init__(self, llm, emitter, sandbox: SandboxRunner, *, max_repairs: int = 4,
                 sandbox_timeout: int = 10):
        self._llm = llm
        self._emitter = emitter
        self._sandbox = sandbox
        self._max_repairs = max_repairs
        self._sandbox_timeout = sandbox_timeout

    async def run(self, ctx: dict) -> AgentOutcome:
        strategy, target = await self._choose_strategy(ctx)

        code, schema = None, None
        error: str | None = None
        source_arg = self._source_arg(ctx, strategy, target)

        for attempt in range(self._max_repairs + 1):
            if attempt == 0:
                messages = codegen_messages(ctx, strategy, target)
            else:
                await self._emitter.emit(
                    "repair_attempt",
                    f"Repair attempt {attempt}/{self._max_repairs}: {error}",
                    data={"iteration": attempt, "error": error},
                )
                messages = repair_messages(ctx, strategy, target, code or "", error or "")

            try:
                result = await self._llm.complete(
                    messages, purpose="repair" if attempt else "codegen"
                )
                code, parsed_schema = parse_extractor_response(result.content)
                # A fence-only rescue carries no schema; keep the one we already have.
                if parsed_schema is not None:
                    schema = parsed_schema
                elif schema is None:
                    schema = {"fields": []}
            except Exception as exc:  # noqa: BLE001
                error = f"could not parse LLM code output: {exc}"
                if attempt == 0:
                    await self._emitter.emit("code_generated", "Model returned unusable output")
                continue

            if attempt == 0:
                await self._emitter.emit(
                    "code_generated",
                    "Generated extract() and record schema",
                    data={"schema": schema},
                )

            # The sandbox is a blocking subprocess; offload it so the event loop
            # stays free for the other concurrent job and the live event stream.
            sandbox_result = await asyncio.to_thread(
                self._sandbox, code, source_arg, timeout=self._sandbox_timeout
            )
            if not sandbox_result.ok:
                error = sandbox_result.error or "sandbox execution failed"
                await self._emitter.emit(
                    "test_failed", f"Extractor errored: {error}", data={"error": error}
                )
                continue

            report = validate_records(sandbox_result.records, schema)
            if not report.ok:
                error = report.reason
                await self._emitter.emit(
                    "test_failed",
                    f"Extraction invalid: {error}",
                    data={"reason": error, "count": report.record_count},
                )
                continue

            await self._emitter.emit(
                "validated",
                f"Extracted {report.record_count} valid records",
                data={"count": report.record_count, "coverage": report.coverage},
            )
            return AgentOutcome(
                ok=True,
                strategy=strategy,
                records=sandbox_result.records,
                code=code,
                record_schema=schema,
                repair_count=attempt,
                reason="validated",
            )

        await self._emitter.emit(
            "failed",
            f"Gave up after {self._max_repairs} repair attempts: {error}",
            data={"error": error},
        )
        return AgentOutcome(
            ok=False,
            strategy=strategy,
            code=code,
            record_schema=schema,
            repair_count=self._max_repairs,
            reason=error or "exhausted repair attempts",
        )

    async def _choose_strategy(self, ctx: dict) -> tuple[str, str]:
        try:
            result = await self._llm.complete(strategy_messages(ctx), purpose="strategy")
            parsed = extract_json(result.content)
            strategy = parsed.get("strategy", "html")
            target = parsed.get("target", "html")
            reasoning = parsed.get("reasoning", "")
        except Exception:  # noqa: BLE001 — a strategy misfire shouldn't kill the run
            strategy, target, reasoning = "html", "html", "defaulted to HTML parsing"

        if strategy not in {"json_xhr", "html"}:
            strategy = "html"
        if strategy == "json_xhr" and not any(
            r.get("url") == target for r in ctx.get("xhr", [])
        ):
            strategy, target = "html", "html"  # hallucinated a URL we never captured

        await self._emitter.emit(
            "strategy_chosen",
            f"Strategy: {strategy}. {reasoning}",
            data={"strategy": strategy, "target": target},
        )
        return strategy, target

    def _source_arg(self, ctx: dict, strategy: str, target: str) -> str:
        if strategy == "json_xhr":
            chosen = next((r for r in ctx.get("xhr", []) if r.get("url") == target), None)
            if chosen:
                return chosen.get("body", "")
        # Prompt from the skeleton (cheap), but EXECUTE against the full HTML:
        # the skeleton collapses repeated siblings, which would silently drop
        # most of the records the extractor exists to return.
        return ctx.get("html", "") or ctx.get("skeleton", "")
