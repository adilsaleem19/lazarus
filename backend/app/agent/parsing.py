"""Robustly extract JSON objects (and extractor code) from LLM responses.

Models wrap JSON in ```json fences, add prose, or emit it bare. We try, in order:
a fenced ```json block, any fenced block, then the first balanced {...} span.

For codegen/repair responses specifically, small models (observed with
llama-4-scout) also produce two systematically broken shapes:
- the "code" value written as a Python triple-quoted string inside the JSON
- no JSON envelope at all, just prose and a ```python fence with the code
`parse_extractor_response` rescues both instead of burning a repair iteration.
"""

import json
import re

_FENCED_JSON = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_FENCED_CODE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)
_TRIPLE_QUOTED = re.compile(r'"""(.*?)"""', re.DOTALL)


class ParseError(ValueError):
    pass


def _balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json(text: str) -> dict:
    candidates: list[str] = []
    for match in _FENCED_JSON.finditer(text):
        candidates.append(match.group(1).strip())
    balanced = _balanced_object(text)
    if balanced:
        candidates.append(balanced)
    candidates.append(text.strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ParseError("no JSON object found in LLM response")


def _requote_triple_strings(text: str) -> str:
    """Turn Python triple-quoted values into legal JSON strings."""
    return _TRIPLE_QUOTED.sub(lambda m: json.dumps(m.group(1)), text)


def parse_extractor_response(text: str) -> tuple[str, dict | None]:
    """Extract (code, schema) from a codegen/repair response.

    Returns schema=None when the response carried usable code but no schema —
    the caller should fall back to the schema it already has.
    """
    for candidate in (text, _requote_triple_strings(text)):
        try:
            parsed = extract_json(candidate)
        except ParseError:
            continue
        if isinstance(parsed.get("code"), str):
            schema = parsed.get("schema")
            return parsed["code"], schema if isinstance(schema, dict) else None

    for match in _FENCED_CODE.finditer(text):
        code = match.group(1).strip()
        if "def extract" in code:
            return code, None

    raise ParseError("no extractor code found in LLM response")
