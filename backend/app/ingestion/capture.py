"""Page capture with Playwright: final DOM plus any JSON XHR/fetch traffic.

Waiting strategy: we deliberately avoid Playwright's `networkidle` (it hangs on
sites with long-polling/analytics). Instead: DOMContentLoaded, then wait for the
network to stay quiet for a short window, all inside a hard time budget, and
proceed with whatever we have.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field

from app.config import Settings

JSONISH = re.compile(rb"^\s*[\[{]")
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}


@dataclass
class CaptureResult:
    final_url: str
    final_html: str
    xhr: list[dict]
    http_status: int | None = None


@dataclass
class XhrCollector:
    max_responses: int = 30
    max_body_bytes: int = 200_000
    records: list[dict] = field(default_factory=list)

    def consider(
        self, url: str, method: str, status: int, content_type: str | None, body: bytes
    ) -> None:
        if len(self.records) >= self.max_responses:
            return
        content_type = (content_type or "").lower()
        body = body or b""
        if "json" not in content_type:
            sniffable = content_type.startswith("text/plain") or content_type == ""
            if not (sniffable and JSONISH.match(body)):
                return
        truncated = len(body) > self.max_body_bytes
        text = body[: self.max_body_bytes].decode("utf-8", errors="replace")
        self.records.append(
            {
                "url": url,
                "method": method,
                "status": status,
                "content_type": content_type,
                "body": text,
                "truncated": truncated,
            }
        )


class _InflightTracker:
    def __init__(self):
        self.inflight = 0
        self.last_settled = time.monotonic()

    def started(self, _request) -> None:
        self.inflight += 1

    def finished(self, _request) -> None:
        self.inflight = max(0, self.inflight - 1)
        self.last_settled = time.monotonic()

    async def wait_quiet(self, quiet_ms: int, budget_ms: int) -> None:
        deadline = time.monotonic() + budget_ms / 1000
        quiet = quiet_ms / 1000
        while time.monotonic() < deadline:
            if self.inflight == 0 and (time.monotonic() - self.last_settled) >= quiet:
                return
            await asyncio.sleep(0.1)


async def capture_page(url: str, settings: Settings) -> CaptureResult:
    from playwright.async_api import async_playwright

    collector = XhrCollector(
        max_responses=settings.max_xhr_responses, max_body_bytes=settings.max_xhr_body_bytes
    )
    tracker = _InflightTracker()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        try:
            context = await browser.new_context(user_agent=settings.user_agent)
            page = await context.new_page()

            async def route_filter(route):
                if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", route_filter)

            async def on_response(response):
                try:
                    if response.request.resource_type not in {"xhr", "fetch"}:
                        return
                    body = await response.body()
                    collector.consider(
                        response.url,
                        response.request.method,
                        response.status,
                        response.headers.get("content-type"),
                        body,
                    )
                except Exception:  # noqa: BLE001 — page may navigate away mid-read
                    return

            page.on("request", tracker.started)
            page.on("requestfinished", tracker.finished)
            page.on("requestfailed", tracker.finished)
            page.on("response", on_response)

            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=settings.page_load_timeout_ms
            )
            await tracker.wait_quiet(
                quiet_ms=settings.network_quiet_ms, budget_ms=settings.page_load_timeout_ms
            )

            html = await page.content()
            return CaptureResult(
                final_url=page.url,
                final_html=html[: settings.max_html_bytes],
                xhr=collector.records,
                http_status=response.status if response else None,
            )
        finally:
            await browser.close()
