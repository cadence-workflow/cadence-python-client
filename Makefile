.PHONY: pr install lint type-check test integration-test proto-check clean help

# Run all PR checks locally
pr: install proto-check lint type-check test integration-test
	@echo "All PR checks passed!"

# Install dependencies
install:
	@echo "Installing dependencies..."
	uv sync --extra dev

# Run linter
lint:
	@echo "Running Ruff linter and fixing lint issues..."
	uv tool run ruff check --fix

# Run type checker
type-check:
	@echo "Running mypy type checker..."
	uv tool run mypy cadence/

# Run unit tests
test:
	@echo "Running unit tests..."
	uv run pytest -v

# Run integration tests
integration-test:
	@echo "Running integration tests..."
	uv run pytest -v --integration-tests

# Clean generated files and caches
clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# Show help
help:
	@echo "Available targets:"
	@echo "  make pr              - Run all PR checks (recommended before submitting PR)"
	@echo "  make install         - Install dependencies"
	@echo "  make lint            - Run Ruff linter"
	@echo "  make type-check      - Run mypy type checker"
	@echo "  make test            - Run unit tests"
	@echo "  make integration-test - Run integration tests"
	@echo "  make clean           - Remove generated files and caches"
	@echo "  make help            - Show this help message"

