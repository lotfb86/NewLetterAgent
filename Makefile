.PHONY: check test lint format typecheck

test:
	PYTHONPATH=. pytest

lint:
	ruff check .

format:
	ruff format --check .

typecheck:
	mypy .

check: lint format typecheck test
