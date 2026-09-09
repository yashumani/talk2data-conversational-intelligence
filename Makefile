.PHONY: install run test lint format typecheck check

install:
	python scripts/dependencies.py install dev

run:
	uvicorn talk2data.main:app --reload

test:
	pytest --cov=talk2data --cov-report=term-missing --cov-report=json:coverage.json
	python scripts/check_coverage.py

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

typecheck:
	mypy src

check: lint typecheck test
	python scripts/dependencies.py check
	python scripts/validate_workflows.py
