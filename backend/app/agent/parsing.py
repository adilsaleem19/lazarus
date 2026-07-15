"""Robustly extract JSON objects from LLM responses.

Models wrap JSON in ```json fences, add prose, or emit it bare. We try, in order:
a fenced ```json block, any fenced block, then the first balanced {...} span.
"""

import json
import re

_FENCED_JSON = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


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
