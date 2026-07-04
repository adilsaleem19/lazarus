"""Tests for XHR response collection rules (pure logic, no browser)."""

from app.ingestion.capture import XhrCollector


def collector(**kw) -> XhrCollector:
    return XhrCollector(**kw)


class TestFiltering:
    def test_captures_json_content_type(self):
        c = collector()
        c.consider("https://s.test/api/items", "GET", 200, "application/json", b'{"a": 1}')
        assert len(c.records) == 1
        assert c.records[0]["url"] == "https://s.test/api/items"
        assert c.records[0]["body"] == '{"a": 1}'

    def test_ignores_html_responses(self):
        c = collector()
        c.consider("https://s.test/page", "GET", 200, "text/html", b"<html></html>")
        assert c.records == []

    def test_sniffs_json_in_text_plain(self):
        c = collector()
        c.consider("https://s.test/api", "GET", 200, "text/plain", b'[{"id": 1}]')
        assert len(c.records) == 1

    def test_ignores_non_json_text_plain(self):
        c = collector()
        c.consider("https://s.test/ping", "GET", 200, "text/plain", b"pong")
        assert c.records == []


class TestLimits:
    def test_truncates_oversized_bodies(self):
        c = collector(max_body_bytes=100)
        big = b'{"k": "' + b"x" * 500 + b'"}'
        c.consider("https://s.test/api", "GET", 200, "application/json", big)
        assert len(c.records) == 1
        assert c.records[0]["truncated"] is True
        assert len(c.records[0]["body"]) <= 100

    def test_stops_after_max_responses(self):
        c = collector(max_responses=3)
        for i in range(10):
            c.consider(f"https://s.test/api/{i}", "GET", 200, "application/json", b"{}")
        assert len(c.records) == 3

    def test_invalid_utf8_does_not_crash(self):
        c = collector()
        c.consider("https://s.test/api", "GET", 200, "application/json", b'{"a": "\xff\xfe"}')
        assert len(c.records) == 1
