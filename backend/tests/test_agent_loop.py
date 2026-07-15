"""Tests for the agent orchestration loop with a scripted fake LLM.

The loop: choose strategy -> generate code+schema -> run in sandbox -> validate
-> repair on failure (<=4). We inject a fake LLM that returns scripted responses
and a fake sandbox runner, so no real browser/network/subprocess is needed.
"""

from app.agent.loop import AgentLoop
from app.sandbox import SandboxResult

STRATEGY_JSON = '{"strategy": "html", "reasoning": "no usable JSON XHR found", "target": "html"}'

_SCHEMA = (
    '"schema": {"fields": ['
    '{"name": "title", "type": "string", "required": true}, '
    '{"name": "url", "type": "string", "required": true}]}'
)

CODEGEN_GOOD = (
    '```json\n{"code": "def extract(html):\\n    return [{\'title\': \'A\', \'url\': \'/a\'}]", '
    + _SCHEMA
    + "}\n```"
)

CODEGEN_BAD = (
    '```json\n{"code": "def extract(html):\\n    return []", ' + _SCHEMA + "}\n```"
)


class FakeLLM:
    def __init__(self, scripted: list[str]):
        self.scripted = list(scripted)
        self.purposes: list[str] = []

    async def complete(self, messages, purpose="", **kw):
        self.purposes.append(purpose)
        from app.llm.client import LLMResult

        return LLMResult(content=self.scripted.pop(0), provider="fake", total_tokens=10)


class RecordingEmitter:
    def __init__(self):
        self.events: list[tuple[str, str]] = []

    async def emit(self, kind, message, data=None):
        self.events.append((kind, message))


def kinds(emitter) -> list[str]:
    return [k for k, _ in emitter.events]


def page_context():
    return {
        "url": "https://site.test/",
        "skeleton": "<div><h1>A</h1></div>",
        "xhr": [],
        "structures": [{"type": "repeated_pattern", "selector": "div.item", "count": 5}],
        "meta": {"title": "Site"},
    }


async def test_happy_path_validates_first_try():
    llm = FakeLLM([STRATEGY_JSON, CODEGEN_GOOD])
    emitter = RecordingEmitter()

    def fake_sandbox(code, html, timeout):
        return SandboxResult(ok=True, records=[{"title": "A", "url": "/a"}], error=None)

    loop = AgentLoop(llm=llm, emitter=emitter, sandbox=fake_sandbox, max_repairs=4)
    outcome = await loop.run(page_context())

    assert outcome.ok is True
    assert outcome.records == [{"title": "A", "url": "/a"}]
    assert outcome.strategy == "html"
    assert "strategy_chosen" in kinds(emitter)
    assert "code_generated" in kinds(emitter)
    assert "validated" in kinds(emitter)
    assert "repair_attempt" not in kinds(emitter)


async def test_repairs_after_empty_extraction_then_succeeds():
    llm = FakeLLM([STRATEGY_JSON, CODEGEN_BAD, CODEGEN_GOOD])
    emitter = RecordingEmitter()
    calls = {"n": 0}

    def fake_sandbox(code, html, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return SandboxResult(ok=True, records=[], error=None)  # empty -> validation fails
        return SandboxResult(ok=True, records=[{"title": "A", "url": "/a"}], error=None)

    loop = AgentLoop(llm=llm, emitter=emitter, sandbox=fake_sandbox, max_repairs=4)
    outcome = await loop.run(page_context())

    assert outcome.ok is True
    assert outcome.repair_count == 1
    assert kinds(emitter).count("repair_attempt") == 1
    assert "test_failed" in kinds(emitter)
    assert "validated" in kinds(emitter)


async def test_gives_up_after_max_repairs():
    # strategy + 5 codegen attempts (initial + 4 repairs), all produce empty
    llm = FakeLLM([STRATEGY_JSON] + [CODEGEN_BAD] * 5)
    emitter = RecordingEmitter()

    def fake_sandbox(code, html, timeout):
        return SandboxResult(ok=True, records=[], error=None)

    loop = AgentLoop(llm=llm, emitter=emitter, sandbox=fake_sandbox, max_repairs=4)
    outcome = await loop.run(page_context())

    assert outcome.ok is False
    assert outcome.repair_count == 4
    assert kinds(emitter).count("repair_attempt") == 4
    assert kinds(emitter)[-1] == "failed"


async def test_repairs_on_sandbox_error():
    llm = FakeLLM([STRATEGY_JSON, CODEGEN_BAD, CODEGEN_GOOD])
    emitter = RecordingEmitter()
    calls = {"n": 0}

    def fake_sandbox(code, html, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return SandboxResult(
                ok=False, records=None, error="ZeroDivisionError: division by zero"
            )
        return SandboxResult(ok=True, records=[{"title": "A", "url": "/a"}], error=None)

    loop = AgentLoop(llm=llm, emitter=emitter, sandbox=fake_sandbox, max_repairs=4)
    outcome = await loop.run(page_context())

    assert outcome.ok is True
    assert outcome.repair_count == 1


async def test_malformed_llm_json_triggers_repair():
    llm = FakeLLM([STRATEGY_JSON, "not json at all", CODEGEN_GOOD])
    emitter = RecordingEmitter()

    def fake_sandbox(code, html, timeout):
        return SandboxResult(ok=True, records=[{"title": "A", "url": "/a"}], error=None)

    loop = AgentLoop(llm=llm, emitter=emitter, sandbox=fake_sandbox, max_repairs=4)
    outcome = await loop.run(page_context())

    assert outcome.ok is True
    assert outcome.repair_count == 1
