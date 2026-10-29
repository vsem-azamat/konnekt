# Makefile for supervisor-telegram

.PHONY: help install hooks setup-dev lint lint-fix format format-check type-check quality test test-unit test-integration test-e2e test-fast test-cov db-upgrade db-downgrade db-migrate clean run-bot quick-check full-test

# Default target
help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Development setup
install: ## Install dependencies
	uv sync --dev

# The value is relative, so every worktree runs its own branch's hooks, and it
# lives in the shared .git/config, so one run covers every worktree.
hooks: ## Run .githooks/ on commit and push
	git config core.hooksPath .githooks

setup-dev: install hooks ## Setup development environment
	@echo "Development environment setup complete!"

# Code quality
lint: ## Run linting with ruff
	uv run ruff check app tests

lint-fix: ## Run linting with automatic fixes
	uv run ruff check --fix app tests

format: ## Format code with ruff
	uv run ruff format app tests

format-check: ## Check code formatting
	uv run ruff format --check app tests

type-check: ## Run type checking with ty
	uv run ty check app tests

quality: lint format-check type-check ## Run all code quality checks

# Testing
test: ## Run all tests
	uv run pytest

test-unit: ## Run unit tests only
	uv run pytest tests/unit -v

test-integration: ## Run integration tests only
	uv run pytest tests/integration -v

test-e2e: ## Run end-to-end tests only
	uv run pytest tests/e2e -v

test-fast: ## Run fast tests only (exclude slow tests)
	uv run pytest -m "not slow" -v

test-cov: ## Run tests with coverage report
	uv run pytest --cov=app --cov-report=html --cov-report=term

# Database
db-upgrade: ## Apply database migrations
	uv run alembic upgrade head

db-downgrade: ## Downgrade database by one migration
	uv run alembic downgrade -1

db-migrate: ## Create new migration
	@read -p "Enter migration message: " msg; \
	uv run alembic revision --autogenerate -m "$$msg"

# Cleanup
clean: ## Clean up build artifacts and cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache/ coverage.xml
	@echo "Cleanup completed!"

# Development helpers
run-bot: ## Run the bot locally
	uv run -m app.presentation.telegram

# Combined workflows
quick-check: lint format-check type-check test-fast ## Quick development checks

full-test: quality test-cov ## Full test suite with quality checks
