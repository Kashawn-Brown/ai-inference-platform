.PHONY: install hooks test lint fmt

install:
	uv sync

hooks:
	uv run pre-commit install

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run black --check .

fmt:
	uv run black .
	uv run ruff check --fix .
