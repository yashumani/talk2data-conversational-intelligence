.PHONY: install run test lint format typecheck check

install:
	python -m pip install -e '.[dev]'

run:
	uvicorn talk2data.main:app --reload

test:
	pytest --cov=talk2data --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

typecheck:
	mypy src

check: lint typecheck test
