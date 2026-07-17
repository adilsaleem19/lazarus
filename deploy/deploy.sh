#!/usr/bin/env bash
# One-command deploy for the Lazarus VPS.
# Usage: ./deploy.sh            (run from the deploy/ directory)
# Requires: deploy/.env filled in (copy from ../.env.example).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "deploy/.env is missing — copy ../.env.example here and fill it in." >&2
    exit 1
fi

echo "==> Pulling latest code"
git -C .. pull --ff-only

echo "==> Building and starting the stack"
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Migrations run automatically in the api container's start command
# (alembic upgrade head), so a healthy api means the schema is current.
echo "==> Waiting for the API to come up"
for i in $(seq 1 30); do
    if docker compose -f docker-compose.yml -f docker-compose.prod.yml \
        exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2)" 2>/dev/null; then
        echo "==> Deploy complete: API is healthy."
        exit 0
    fi
    sleep 2
done

echo "==> API did not become healthy in 60s — check: docker compose logs api" >&2
exit 1
