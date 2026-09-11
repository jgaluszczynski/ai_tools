.PHONY: lint format check-all lint/all install test

# Run all checks
check-all: lint format

lint/all: check-all

test:
	node har_recorder/test/parity_test.mjs
	poetry run pytest coding_model_preflight/tests

# Run linting tools
lint:
	poetry run flake8 .
	poetry run isort --check .
	poetry run black --check .

# Format code
format:
	poetry run isort .
	poetry run black .
