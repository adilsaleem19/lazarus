# Lazarus

Give it any website — it raises a living API from the dead. Paste a public URL → get a working, documented REST API for that site's data in ~60 seconds. An autonomous agent analyzes the page, finds hidden JSON APIs or generates scraper code, tests it against the live site, repairs its own failures, and publishes a documented endpoint — streaming its reasoning live.

**Status: Phase 1** — foundation & ingestion engine (no LLM yet). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Stack

FastAPI · PostgreSQL 16 · Redis + arq · Playwright (Chromium) · Next.js 14 · Caddy · Docker Compose — designed to fit one 4GB VPS, free tier everything else.

## Run it

```bash
cp .env.example deploy/.env   # then edit (at minimum set a real LAZARUS_USER_AGENT)
make dev                      # docker compose up --build
```

- App (via Caddy): http://localhost:8080
- API direct: http://localhost:8000 (Swagger at /docs)
- Frontend direct: http://localhost:3000

No `make` on Windows? Run the underlying command: `docker compose -f deploy/docker-compose.yml up --build`.

## Try the ingestion engine

```bash
# submit a job
curl -s -X POST localhost:8000/jobs \
  -H "content-type: application/json" \
  -d '{"url": "https://news.ycombinator.com/"}'

# poll it (replace <id>)
curl -s localhost:8000/jobs/<id>

# full artifacts: DOM skeleton, captured XHR JSON, detected structures
curl -s localhost:8000/jobs/<id>/snapshot
```

## Tests

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest              # unit (fast, no browser)
.venv/Scripts/python -m playwright install chromium
.venv/Scripts/python -m pytest -m integration   # real-browser capture test
.venv/Scripts/python -m ruff check .
```

## Responsible scraping

This project only targets public, non-authenticated pages. It respects `robots.txt` (and refuses when the rules can't be read), rate-limits itself to 1 request/second per target domain, sends an honest identifying User-Agent, and refuses private/internal network targets. Every generated API attributes its source URL.
