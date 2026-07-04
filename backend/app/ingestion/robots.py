"""robots.txt policy: fetch, parse (protego handles wildcards), and give a verdict.

Failure handling is deliberately conservative: if we cannot learn the site's
rules (5xx, 429, network failure), we refuse rather than assume permission.
A missing robots.txt (404) means public crawling is permitted by convention.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from protego import Protego


@dataclass(frozen=True)
class RobotsVerdict:
    allowed: bool
    status: str  # allowed | disallowed | no_robots | unavailable
    reason: str


async def check_robots(url: str, *, user_agent: str, client: httpx.AsyncClient) -> RobotsVerdict:
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"

    try:
        response = await client.get(
            robots_url, headers={"User-Agent": user_agent}, follow_redirects=True
        )
    except httpx.HTTPError as exc:
        return RobotsVerdict(
            allowed=False,
            status="unavailable",
            reason=(
                f"could not fetch {robots_url} ({type(exc).__name__}); "
                "refusing to scrape without knowing the site's rules"
            ),
        )

    if response.status_code >= 500 or response.status_code == 429:
        return RobotsVerdict(
            allowed=False,
            status="unavailable",
            reason=(
                f"{robots_url} returned HTTP {response.status_code}; "
                "conservatively refusing while the site looks unhealthy"
            ),
        )
    if response.status_code >= 400:
        return RobotsVerdict(
            allowed=True,
            status="no_robots",
            reason=(
                f"no robots.txt at {robots_url} (HTTP {response.status_code}); "
                "public crawling is permitted by default"
            ),
        )

    rules = Protego.parse(response.text)
    if rules.can_fetch(url, user_agent):
        return RobotsVerdict(
            allowed=True, status="allowed", reason="robots.txt permits this URL for our user agent"
        )
    return RobotsVerdict(
        allowed=False,
        status="disallowed",
        reason=(
            f"robots.txt at {robots_url} disallows fetching "
            f"{parts.path or '/'} for user agent {user_agent!r}"
        ),
    )
