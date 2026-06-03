.PHONY: install hooks up down logs rebuild migrate test lint fmt bench-smoke bench-load bench-stress

install:
	uv sync

hooks:
	uv run pre-commit install

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

rebuild:
	docker compose build --no-cache && docker compose up -d

migrate:
	docker compose exec gateway alembic upgrade head

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run black --check .

fmt:
	uv run black .
	uv run ruff check --fix .

# Benchmarks — run the stack first (`make up`); needs a live gateway + vLLM.
# Results land in benchmarks/results/ as JSON + a markdown summary per run.
bench-smoke:
	docker compose --profile bench run --rm k6 run /benchmarks/scripts/smoke.js

bench-load:
	docker compose --profile bench run --rm k6 run /benchmarks/scripts/load.js

bench-stress:
	docker compose --profile bench run --rm k6 run /benchmarks/scripts/stress.js
