"""Real-browser capture test against a local HTTP server (no external network).

Proves: JS executes, the hidden JSON XHR is captured, and the final DOM reflects
client-side rendering. Requires `playwright install chromium`.
"""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.config import Settings
from app.ingestion.capture import capture_page

FIXTURES = Path(__file__).parent / "fixtures"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def local_site():
    handler = partial(QuietHandler, directory=str(FIXTURES))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.mark.integration
async def test_capture_executes_js_and_records_xhr(local_site):
    settings = Settings(page_load_timeout_ms=15_000, network_quiet_ms=500)
    result = await capture_page(f"{local_site}/page.html", settings)

    # JS ran: the grid was rendered client-side from fetched JSON
    assert "Product Alpha" in result.final_html
    # the hidden JSON API call was captured
    json_calls = [r for r in result.xhr if r["url"].endswith("/data.json")]
    assert len(json_calls) == 1
    assert json_calls[0]["status"] == 200
    assert "Product Alpha" in json_calls[0]["body"]
    assert result.http_status == 200
