"""Prompt construction for the agent loop.

Kept as pure functions returning message lists so they are easy to unit-test and
cheap to reason about. A stable system prompt prefix matters: Groq doesn't count
cached tokens against the free tier, so reusing the exact preamble stretches it.
"""

import json

from app.llm.client import LLMMessage

_SYSTEM = (
    "You are Lazarus, an autonomous agent that writes Python data extractors for web pages. "
    "You are precise, you never invent data, and you output only what is asked for in the "
    "exact format requested."
)

_CODE_RULES = (
    "Rules for the code:\n"
    "- Define exactly one function: def extract(html_or_response) -> list[dict].\n"
    "- Pure function: no I/O, no network, no file access, no printing.\n"
    "- You may import only: selectolax.parser, re, json, datetime, urllib.parse, "
    "collections, itertools, math, string, html.\n"
    "- For HTML strategy the argument is the page HTML string; parse with "
    "selectolax.parser.HTMLParser.\n"
    "- selectolax API (it is NOT BeautifulSoup/Scrapy): tree = HTMLParser(html); "
    "tree.css('div.card') returns a list of nodes; node.css_first('a') returns one node "
    "or None; node.text(strip=True) gets text; node.attributes.get('href') gets an "
    "attribute (may be None). There is NO css_select method and NO ::text or ::attr() "
    "pseudo-selectors — plain CSS selectors only.\n"
    "- For JSON strategy the argument is the raw JSON text of the chosen XHR response; "
    "parse it with json.loads.\n"
    "- Return a list of flat dicts with consistent keys. Coerce numbers where sensible.\n"
)


def _xhr_digest(xhr: list[dict], limit: int = 6) -> str:
    lines = []
    for r in xhr[:limit]:
        body = (r.get("body") or "")[:300]
        lines.append(f"- {r.get('method', 'GET')} {r.get('url')} [{r.get('status')}]: {body}")
    return "\n".join(lines) if lines else "(no JSON XHR responses were captured)"


def strategy_messages(ctx: dict) -> list[LLMMessage]:
    xhr = ctx.get("xhr", [])
    structures = json.dumps(ctx.get("structures", []))[:800]
    user = (
        f"Target page: {ctx['url']}\n"
        f"Title: {ctx.get('meta', {}).get('title', '(none)')}\n\n"
        f"Captured JSON XHR/fetch responses (hidden APIs, preferred if usable):\n"
        f"{_xhr_digest(xhr)}\n\n"
        f"Detected page structures: {structures}\n\n"
        "Decide the extraction strategy. Prefer a hidden JSON API when one clearly returns the "
        "page's main list data; otherwise parse the HTML.\n"
        'Respond with ONLY a JSON object: {"strategy": "json_xhr" | "html", '
        '"reasoning": "<one sentence>", "target": "<the XHR url if json_xhr, else \'html\'>"}'
    )
    return [LLMMessage("system", _SYSTEM), LLMMessage("user", user)]


def codegen_messages(ctx: dict, strategy: str, target: str) -> list[LLMMessage]:
    if strategy == "json_xhr":
        chosen = next((r for r in ctx.get("xhr", []) if r.get("url") == target), None)
        sample = (chosen or {}).get("body", "")[:2500]
        source = (
            f"Strategy: parse the JSON from this hidden API response ({target}).\n"
            f"Sample of the JSON body your extract() will receive as its argument:\n{sample}\n"
        )
    else:
        source = (
            "Strategy: parse the page HTML.\n"
            f"Distilled DOM skeleton your extract() will receive as its argument:\n"
            f"{ctx.get('skeleton', '')[:4000]}\n"
        )

    user = (
        f"Target page: {ctx['url']}\n\n"
        f"{source}\n"
        f"{_CODE_RULES}\n"
        "Also define the record schema describing the fields you extract. Mark a field "
        '"required" only if every record will have a non-empty value for it; anything '
        "that can be absent or empty must be optional.\n"
        "Respond with ONLY a JSON object in this exact shape:\n"
        '{"code": "<python source for extract()>", '
        '"schema": {"fields": [{"name": "<field>", "type": '
        '"string|integer|number|boolean", "required": true|false}]}}'
    )
    return [LLMMessage("system", _SYSTEM), LLMMessage("user", user)]


def describe_messages(ctx: dict, schema: dict) -> list[LLMMessage]:
    fields = ", ".join(f["name"] for f in (schema or {}).get("fields", [])) or "records"
    user = (
        f"A REST API now serves data extracted from {ctx['url']} "
        f"(page title: {ctx.get('meta', {}).get('title', 'unknown')}). "
        f"Each record has the fields: {fields}.\n"
        "Write a one-to-two sentence plain-language description of what this API returns, "
        "for its documentation page. Respond with ONLY the description text, no quotes."
    )
    return [LLMMessage("system", _SYSTEM), LLMMessage("user", user)]


def repair_messages(
    ctx: dict, strategy: str, target: str, code: str, error: str
) -> list[LLMMessage]:
    base = codegen_messages(ctx, strategy, target)
    base.append(
        LLMMessage(
            "user",
            "Your previous extract() failed. Here is the code you wrote:\n"
            f"```python\n{code}\n```\n"
            f"Failure: {error}\n\n"
            "Fix it. Look carefully at the actual data sample above — your selectors or keys "
            "were probably wrong. If the failure says a required field is missing from some "
            "records, that field is not universal on this page: set \"required\": false for "
            "it in the schema (and use null, not '', when it is absent). Respond with ONLY "
            'the same JSON object shape as before ({"code", "schema"}).',
        )
    )
    return base
