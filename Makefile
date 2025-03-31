.PHONY: lint format check-all install

# Run all checks
check-all: lint format

# Run linting tools
lint:
	poetry run flake8 .
	poetry run isort --check .
	poetry run black --check .

# Format code
format:
	poetry run isort .
	poetry run black .
