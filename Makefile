.PHONY: check

VENV_BIN := .venv/bin

check:
	$(VENV_BIN)/ruff format --check src tests
	$(VENV_BIN)/ruff check src tests
	$(VENV_BIN)/mypy --strict src tests
	$(VENV_BIN)/pytest --cov=tv90.domain --cov=tv90.application --cov-branch --cov-fail-under=90
