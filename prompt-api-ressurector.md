# Claude Code Opening Prompt — "APIfy" (Autonomous Website-to-API Agent)
---

## PROJECT BRIEF

You are building **APIfy** — an autonomous agent that takes any public website URL and, within ~60 seconds, produces a working, documented, deployed REST API for that site's data. The agent loads the page, analyzes the DOM and network traffic, infers data structures, generates scraper code, tests it against the live site, self-fixes failures, registers it as a live endpoint, and generates OpenAPI docs — all autonomously, with its reasoning streamed live to a terminal-style web UI.

This is a **portfolio project**. Two things matter above all:
1. **Demo quality.** The 60-second "paste URL → working API" flow must feel like magic and be screen-recordable.
2. **Zero cost.** The ONLY money I will spend is one small VPS (~4GB RAM, Ubuntu 24.04, Docker installed). Every other component must be free-tier or self-hosted. Never suggest a paid service. If a design decision trades money for convenience, choose the free path and tell me the tradeoff.

## HARD CONSTRAINTS (never violate these)

- **Runtime LLM must be free.** The agent needs an LLM at runtime for DOM analysis and code generation. Use a provider-agnostic client (OpenAI-compatible interface) defaulting to **Groq free tier** (fast, generous limits) with **Google Gemini free tier** as fallback, both behind a single `LLM_PROVIDER` env var. Build in aggressive prompt-size reduction (strip scripts/styles/SVGs, truncate DOM to structural skeleton) so we stay inside free-tier token and rate limits. Implement retry with exponential backoff on 429s.
- **Everything self-hosted on the one VPS via Docker Compose:** FastAPI backend, PostgreSQL, Redis, Playwright worker, Caddy (automatic free Let's Encrypt TLS), and the Next.js frontend (static export or node server — whichever is lighter). No managed databases, no serverless, no paid queues.
- **Free everything else:** GitHub for repo + GitHub Actions free tier for CI, Playwright (free) for browsing, `nip.io` or a free DuckDNS subdomain if I don't buy a domain yet.
- **Memory budget:** total stack must run comfortably in 4GB RAM. Playwright browser instances are the memory hog — run max 2 concurrent, headless, with `--disable-dev-shm-usage`, and recycle browser contexts.
- **Legal/safety guardrails are a feature, not an afterthought:** respect robots.txt (hard block if disallowed, show the user why), per-domain rate limiting (max 1 req/sec to any target site), identify with an honest User-Agent, only public non-authenticated pages, denylist for login pages/paywalls/PII-heavy patterns, and a visible "Responsible scraping" note in the UI. This makes the demo look senior, not reckless.

## TECH STACK (fixed — don't relitigate)

- Backend: **Python 3.12 + FastAPI**, SQLAlchemy 2 + Alembic, Pydantic v2
- Job queue: **Redis + arq** (lighter than Celery)
- Browser: **Playwright (Python, Chromium only)**
- Generated-scraper sandbox: subprocess with resource limits (see Phase 2)
- DB: **PostgreSQL 16**
- Frontend: **Next.js 14 + Tailwind**, streaming via **Server-Sent Events** (simpler than websockets, fine for one-directional reasoning stream)
- Reverse proxy + TLS: **Caddy**
- Orchestration: **Docker Compose** (single VPS), GitHub Actions for lint/test/build

## WORKING AGREEMENT

- Work phase by phase. At the end of each phase, stop, summarize what was built, list how I can manually verify it, and wait for my go-ahead.
- Write tests for the core agent loop and the sandbox (pytest). CI must pass before a phase is "done."
- Keep a running `ARCHITECTURE.md` updated each phase — this doubles as portfolio documentation.
- Prefer boring, debuggable code over clever abstractions. I will be demoing and explaining this in interviews.

---

## PHASE 1 — Foundation & Ingestion Engine (repo, infra, page analysis)

Goal: a working skeleton where I can POST a URL and get back a structured analysis of the page — no LLM yet.

1. Scaffold monorepo: `/backend`, `/frontend`, `/deploy` (compose files, Caddyfile), `/docs`. Set up Docker Compose with Postgres, Redis, backend, frontend, Caddy. One `make dev` command brings everything up locally; same compose file (with prod overrides) runs on the VPS.
2. FastAPI app with health checks, structured JSON logging, and an `arq` worker container.
3. **Ingestion pipeline** (`POST /jobs` with a URL):
   - robots.txt fetch + parse → hard reject with reason if disallowed.
   - Playwright loads the page (networkidle, 15s timeout), captures: final HTML, all XHR/fetch responses with JSON bodies (this is gold — many sites have hidden JSON APIs we can use instead of scraping HTML), meta tags, and detected `<table>`, repeated-card, and list structures via heuristics.
   - DOM distillation: strip scripts/styles/svg/base64, collapse repeated siblings to "N× pattern" samples, output a compact structural skeleton (target <8K tokens).
4. Persist jobs + artifacts in Postgres. Job state machine: `queued → analyzing → done/failed`.
5. GitHub Actions: ruff, pytest, docker build.
6. Verification for me: `curl` a job for a news site and a table-heavy site, inspect the stored skeleton and captured XHR JSON.

## PHASE 2 — The Agent Loop (LLM analysis, codegen, self-testing, self-repair)

Goal: the autonomous core. URL in → validated, working scraper function out.

1. **LLM client layer:** provider-agnostic (Groq default, Gemini fallback), token counting, request budget per job (cap total tokens per job so a runaway loop can't burn the free tier), 429 backoff, and full logging of every prompt/response to Postgres (these logs feed the UI's "watch it think" stream later).
2. **Strategy selection step:** the LLM first decides — "does this site expose usable JSON XHR endpoints, or must we parse HTML?" Preferring hidden JSON APIs is faster, more stable, and a great talking point.
3. **Scraper codegen:** LLM generates a single pure-Python function `extract(html_or_response) -> list[dict]` plus a Pydantic schema describing the records. Constrain output format strictly (JSON-wrapped code block, no I/O, no network, stdlib + selectolax only).
4. **Sandboxed execution:** run generated code in a subprocess with `resource` limits (CPU seconds, memory cap, no network via env + firewall rules in the worker container), 10s timeout. Never `exec` in the main process.
5. **Self-repair loop:** run scraper on the captured page → validate output against the schema (non-empty, field coverage, type checks) → on failure, feed the error + a data sample back to the LLM → retry, max 4 iterations. Emit a structured event for every step (`strategy_chosen`, `code_generated`, `test_failed`, `repair_attempt`, `validated`) into Redis pub/sub — this is the live reasoning stream.
6. Store the final scraper (code, schema, target URL, strategy) as a versioned `Extractor` row.
7. Tests: golden-path fixtures (saved HTML from 3 site types), a deliberately broken generation to prove the repair loop works, sandbox escape attempts (network call, file write, fork bomb) must all fail safely.
8. Verification for me: run 5 real sites end-to-end from the CLI, watch events stream in `redis-cli`, confirm ≥4/5 succeed within 4 repair iterations.

## PHASE 3 — Live API Fabric (dynamic endpoints, docs, refresh, protection)

Goal: every successful extraction becomes a real, documented, rate-limited public API endpoint.

1. **Dynamic endpoint registry:** `GET /api/{slug}` serves the latest extracted data for that extractor. Slugs are readable (`/api/hn-front-page`). Response includes data, `last_refreshed`, source URL attribution, and record count.
2. **Refresh strategy (cost- and RAM-aware):** data is served from Postgres cache; a scheduled arq job re-scrapes each active extractor at most every N minutes (default 30, configurable per extractor), honoring the 1 req/sec per-domain limit. Stale-while-revalidate semantics. Auto-pause extractors that fail 3 consecutive refreshes, with the failure reason stored.
3. **Auto-generated OpenAPI:** generate a per-extractor OpenAPI 3.1 spec from the Pydantic schema (field types, example record, endpoint description written by the LLM in one cheap call). Serve Swagger UI at `/api/{slug}/docs` — this is a major demo moment.
4. **Abuse protection (I'm publishing this publicly):** global + per-IP rate limits on job creation (e.g., 3 jobs/hour per IP via Redis), CAPTCHA-free friction (require the user to check a "responsible use" box that posts a token), max 20 active public extractors with LRU eviction, and target-domain denylist (localhost, RFC1918 ranges, my own VPS — prevent SSRF).
5. **Deployment:** bring the full stack up on the VPS with the prod compose file, Caddy TLS on the (sub)domain, `.env` documented, one-command deploy script (`git pull && docker compose up -d --build`), and a nightly `pg_dump` to local disk.
6. Verification for me: create an extractor from my phone's browser, hit its endpoint and Swagger docs from a different network, confirm rate limits and SSRF denylist work.

## PHASE 4 — The Spectacle (frontend, live reasoning stream, demo mode, portfolio polish)

Goal: the part people screen-record and share.

1. **Landing page:** single input — "Paste any public URL." Dark, terminal-aesthetic, fast. (Design it to look striking in a vertical phone screen recording too.)
2. **Live agent theater:** on job submit, an SSE-driven terminal panel streams the agent's real reasoning events in human language with timestamps and phase badges: analyzing DOM → "found hidden JSON API at /v2/posts, switching strategy" → generating code → test failed (show the actual error, styled) → repairing → validated ✓ → "Your API is live." Include a live elapsed-time counter racing toward the 60-second promise. This panel IS the product demo — invest disproportionate effort here.
3. **Result screen:** the endpoint URL (copy button), a live JSON preview, a link to Swagger docs, an auto-generated `curl` example, and the responsible-scraping disclosure (robots.txt status shown as a green check).
4. **Public gallery:** grid of recently created APIs (respecting the 20-extractor cap) so visitors see it's real and alive.
5. **Demo mode:** a `?demo=1` flag that runs against 3 pre-approved showcase sites with slightly slowed event pacing, so my screen recordings are reliable even if a target site changes. Never fake events — just curated targets.
6. **Portfolio polish:** README with an animated GIF of the flow, an architecture diagram (Mermaid in `ARCHITECTURE.md`), a "How the self-repair loop works" section, and honest limitations. Add OG meta tags so the link unfurls nicely on LinkedIn.
7. Verification for me: full cold demo on a site we've never tested, recorded in one take; Lighthouse pass on the landing page; a friend can create an API without any instructions from me.

---

## START

Begin with Phase 1. Before writing any code, restate the architecture back to me in a short diagram, confirm the free-tier LLM choice and its current rate limits (check the providers' docs), and flag anything in this brief that you think is a mistake or will blow the 4GB RAM budget. Then scaffold the repo.