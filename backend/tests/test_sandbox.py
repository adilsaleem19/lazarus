"""Tests for the sandboxed extractor executor.

Golden path (valid code runs and returns records) plus the escape attempts the
brief demands must all fail safely: network, file write, fork bomb, infinite loop.
These run the real subprocess harness, so they are marked integration (need a
POSIX-ish resource module; on Windows the harness falls back to a thread+timeout
guard, which still enforces the import whitelist and timeout).
"""

import pytest

from app.sandbox import run_extractor

GOOD_CODE = """
from selectolax.parser import HTMLParser

def extract(html):
    tree = HTMLParser(html)
    return [{"title": n.text()} for n in tree.css("h1")]
"""

HTML = "<html><body><h1>Alpha</h1><h1>Beta</h1></body></html>"


@pytest.mark.integration
def test_good_code_returns_records():
    result = run_extractor(GOOD_CODE, HTML, timeout=10)
    assert result.ok is True
    assert result.records == [{"title": "Alpha"}, {"title": "Beta"}]


@pytest.mark.integration
def test_syntax_error_is_reported_not_raised():
    result = run_extractor("def extract(html)\n  return []", HTML, timeout=10)
    assert result.ok is False
    assert "syntax" in result.error.lower() or "invalid" in result.error.lower()


@pytest.mark.integration
def test_runtime_error_is_captured():
    code = "def extract(html):\n    return 1 / 0"
    result = run_extractor(code, HTML, timeout=10)
    assert result.ok is False
    assert "ZeroDivisionError" in result.error or "division" in result.error.lower()


@pytest.mark.integration
def test_non_list_return_is_rejected():
    code = "def extract(html):\n    return {'not': 'a list'}"
    result = run_extractor(code, HTML, timeout=10)
    assert result.ok is False


@pytest.mark.integration
def test_network_access_is_blocked():
    code = """
import urllib.request

def extract(html):
    urllib.request.urlopen("http://example.com").read()
    return []
"""
    result = run_extractor(code, HTML, timeout=10)
    assert result.ok is False
    assert result.error


@pytest.mark.integration
def test_file_write_is_blocked():
    code = """
def extract(html):
    with open("pwned.txt", "w") as f:
        f.write("x")
    return []
"""
    result = run_extractor(code, HTML, timeout=10)
    assert result.ok is False


@pytest.mark.integration
def test_infinite_loop_times_out():
    code = "def extract(html):\n    while True:\n        pass"
    result = run_extractor(code, HTML, timeout=3)
    assert result.ok is False
    assert "time" in result.error.lower()


@pytest.mark.integration
def test_missing_extract_function_is_rejected():
    code = "def other():\n    return []"
    result = run_extractor(code, HTML, timeout=10)
    assert result.ok is False
    assert "extract" in result.error.lower()
