.PHONY: install hooks up down logs rebuild migrate test lint fmt

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
