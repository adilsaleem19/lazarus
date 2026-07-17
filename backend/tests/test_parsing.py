"""Tests for robust extraction of {"code", "schema"} from LLM responses.

The awkward cases come verbatim from real llama-4-scout behavior observed against
books.toscrape.com: Python triple-quoted strings inside the "JSON", and repair
responses that drop the JSON envelope entirely and return a bare ```python fence.
"""

import pytest

from app.agent.parsing import ParseError, extract_json, parse_extractor_response

GOOD_SCHEMA = {"fields": [{"name": "title", "type": "string", "required": True}]}


class TestExtractJson:
    def test_bare_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_with_prose_around_it(self):
        assert extract_json('Sure! Here it is:\n{"a": 1}\nHope that helps.') == {"a": 1}

    def test_no_json_raises(self):
        with pytest.raises(ParseError):
            extract_json("I could not produce the code, sorry.")


class TestParseExtractorResponse:
    def test_wellformed_json_passthrough(self):
        text = '{"code": "def extract(html):\\n    return []", "schema": {"fields": []}}'
        code, schema = parse_extractor_response(text)
        assert code.startswith("def extract")
        assert schema == {"fields": []}

    def test_python_triple_quoted_code_value(self):
        # Real scout output: the code value uses Python triple quotes — invalid JSON.
        text = (
            '```json\n{\n  "code": """\ndef extract(html):\n    return [{"title": "x"}]\n""",\n'
            '  "schema": {"fields": [{"name": "title", "type": "string", "required": true}]}\n'
            "}\n```"
        )
        code, schema = parse_extractor_response(text)
        assert "def extract(html):" in code
        assert schema["fields"][0]["name"] == "title"

    def test_bare_python_fence_without_json_envelope(self):
        # Real scout output on later repairs: prose + a ```python fence, no JSON at all.
        text = (
            "# Fixed solution:\n```python\n"
            "def extract(html):\n    return [{'title': 'x'}]\n```\n"
        )
        code, schema = parse_extractor_response(text)
        assert "def extract(html):" in code
        assert schema is None  # caller falls back to the previous schema

    def test_generic_fence_containing_extract_function(self):
        text = "```\ndef extract(html):\n    return []\n```"
        code, schema = parse_extractor_response(text)
        assert code.startswith("def extract")
        assert schema is None

    def test_json_without_code_key_raises(self):
        with pytest.raises(ParseError):
            parse_extractor_response('{"strategy": "html"}')

    def test_nothing_usable_raises(self):
        with pytest.raises(ParseError):
            parse_extractor_response("I am unable to help with that.")
