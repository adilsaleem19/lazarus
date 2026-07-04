COMPOSE = docker compose -f deploy/docker-compose.yml
COMPOSE_PROD = docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml

.PHONY: dev down logs ps test test-integration lint migrate prod

dev:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

test:
	cd backend && python -m pytest

test-integration:
	cd backend && python -m pytest -m integration

lint:
	cd backend && python -m ruff check .

migrate:
	$(COMPOSE) run --rm api alembic upgrade head

prod:
	$(COMPOSE_PROD) up -d --build
