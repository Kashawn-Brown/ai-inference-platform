.PHONY: install hooks up down logs rebuild test lint fmt

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

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run black --check .

fmt:
	uv run black .
	uv run ruff check --fix .
