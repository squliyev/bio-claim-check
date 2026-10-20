# One set of command names, identical locally and in CI. `make help` lists them.
.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help sync lint format typecheck arch test cov verify hooks secrets up down clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

sync:  ## Install the locked environment (dev included)
	$(UV) sync --frozen

lint:  ## Ruff lint + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format:  ## Apply ruff fixes and formatting
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck:  ## Pyright strict
	$(UV) run pyright

arch:  ## Import contracts (import-linter); rule-fire proofs run in `test` (marker arch)
	$(UV) run lint-imports --no-logo --no-cache

test:  ## Offline tests (everything except `live`)
	$(UV) run pytest -m "not live"

cov:  ## Offline tests with branch coverage
	$(UV) run pytest -m "not live" --cov --cov-report=term-missing

verify: lint typecheck arch test  ## The single gate: lint, types, import contracts, offline tests

hooks:  ## Install git pre-commit hooks
	$(UV) run pre-commit install

secrets:  ## Scan the working tree and git history for secrets
	$(UV) run pre-commit run gitleaks --all-files

up:  ## Build and start with docker compose
	docker compose up --build

down:  ## Stop docker compose services
	docker compose down

clean:  ## Remove build and tool caches (never touches var/)
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build
