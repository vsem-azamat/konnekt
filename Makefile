# Makefile for moderator-bot project

.PHONY: help install test test-unit test-integration test-e2e test-performance test-cov clean lint format type-check hooks setup-dev

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

test-performance: ## Run performance tests (quick)
	uv run pytest tests/performance -m "performance and not slow" -v

test-performance-full: ## Run all performance tests (slow)
	uv run pytest tests/performance -m "performance" -v

test-fast: ## Run fast tests only (exclude slow tests)
	uv run pytest -m "not slow" -v

test-cov: ## Run tests with coverage report
	uv run pytest --cov=app --cov-report=html --cov-report=term

test-cov-xml: ## Run tests with XML coverage report (for CI)
	uv run pytest --cov=app --cov-report=xml

test-watch: ## Run tests in watch mode (requires pytest-watch)
	uv run ptw

# Database
db-upgrade: ## Apply database migrations
	uv run alembic upgrade head

db-downgrade: ## Downgrade database by one migration
	uv run alembic downgrade -1

db-migrate: ## Create new migration
	@read -p "Enter migration message: " msg; \
	uv run alembic revision --autogenerate -m "$$msg"

# Docker
docker-dev: ## Start development environment with Docker
	docker-compose -f docker-compose.dev.yaml up --build

docker-prod: ## Start production environment with Docker
	docker-compose up --build

docker-down: ## Stop Docker containers
	docker-compose down

docker-logs: ## Show Docker logs
	docker-compose logs -f

# CI/CD
ci-test: quality test-cov-xml ## Run CI test suite
	@echo "CI tests completed successfully!"

# Cleanup
clean: ## Clean up build artifacts and cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache/ coverage.xml
	@echo "Cleanup completed!"

clean-all: clean ## Clean everything including virtual environment
	rm -rf .venv/
	rm -rf uv.lock
	@echo "Full cleanup completed!"

# Development helpers
run-bot: ## Run the bot locally
	uv run -m app.presentation.telegram

shell: ## Open Python shell with project context
	uv run python

# Debugging
debug-test: ## Run tests with debugging output
	uv run pytest -v -s --tb=long

debug-test-pdb: ## Run tests with PDB debugger on failures
	uv run pytest --pdb

# Documentation
docs-coverage: ## Generate documentation coverage report
	@echo "Documentation coverage not implemented yet"

# Security
security-check: ## Run security checks
	uv run bandit -r app/ -f json -o bandit-report.json || true
	@echo "Security check completed - see bandit-report.json"

# Performance profiling
profile-tests: ## Profile test performance
	uv run pytest tests/performance --profile --profile-svg -m "not slow"

# Release helpers
version-check: ## Check current version
	@echo "Current version: $(shell grep version pyproject.toml | head -1 | cut -d'"' -f2)"

# Environment info
env-info: ## Show environment information
	@echo "Python version: $(shell python --version)"
	@echo "UV version: $(shell uv --version)"
	@echo "Project info:"
	@uv run python -c "import sys; print(f'Python: {sys.version}'); import app; print('App module loaded successfully')"

# Combined workflows
dev-setup: setup-dev ## Complete development setup
	@echo "Running initial tests..."
	$(MAKE) test-unit
	@echo "Development setup complete! Run 'make help' to see available commands."

quick-check: lint format-check type-check test-fast ## Quick development checks

full-test: quality test-cov ## Full test suite with quality checks

# Continuous development
watch: ## Watch for changes and run tests
	@echo "Watching for changes... (Press Ctrl+C to stop)"
	uv run ptw --runner "pytest tests/unit tests/integration -x -q"
