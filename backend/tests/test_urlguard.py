"""Tests for target URL validation (SSRF first line of defence)."""

import pytest

from app.ingestion.urlguard import UnsafeURLError, validate_target_url

PUBLIC_IP = ["93.184.216.34"]


def public_resolver(host: str) -> list[str]:
    return PUBLIC_IP


class TestSchemes:
    @pytest.mark.parametrize(
        "url", ["file:///etc/passwd", "ftp://site.test/x", "javascript:alert(1)"]
    )
    def test_rejects_non_http_schemes(self, url):
        with pytest.raises(UnsafeURLError):
            validate_target_url(url)

    def test_accepts_https(self):
        assert validate_target_url("https://example.com/page", resolve=public_resolver)


class TestPrivateTargets:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/admin",
            "http://127.0.0.1:8000/",
            "http://[::1]/",
            "http://10.0.0.1/x",
            "http://192.168.1.10/x",
            "http://172.16.5.5/x",
            "http://169.254.169.254/latest/meta-data/",
        ],
    )
    def test_rejects_loopback_and_private_ips(self, url):
        with pytest.raises(UnsafeURLError):
            validate_target_url(url)

    def test_rejects_hostname_resolving_to_private_ip(self):
        with pytest.raises(UnsafeURLError):
            validate_target_url("https://evil.test/x", resolve=lambda host: ["10.1.2.3"])

    def test_accepts_hostname_resolving_to_public_ip(self):
        assert validate_target_url("https://good.test/x", resolve=public_resolver)


class TestMalformed:
    @pytest.mark.parametrize("url", ["", "not a url", "https://", "https:///path"])
    def test_rejects_garbage(self, url):
        with pytest.raises(UnsafeURLError):
            validate_target_url(url)

    def test_skips_dns_stage_when_no_resolver(self):
        # syntactic-only mode for the fast API-side check; DNS happens in the worker
        assert validate_target_url("https://example.com/page")

    def test_error_carries_human_readable_reason(self):
        with pytest.raises(UnsafeURLError) as exc:
            validate_target_url("http://127.0.0.1/")
        assert str(exc.value)
