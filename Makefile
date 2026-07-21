PYTHON ?= $(shell if command -v uv >/dev/null 2>&1; then printf 'uv run python'; else printf 'python3'; fi)
CONFORMANCE_TESTS ?= tests/

.PHONY: lint conformance coverage test smoke build verify clean

test:
	$(PYTHON) -m pytest tests/

lint:
	$(PYTHON) -m ruff check .

conformance:
	ALPABRIDGE_CORE_CONFORMANCE=1 $(PYTHON) -m pytest -q $(CONFORMANCE_TESTS)

coverage:
	$(PYTHON) -m pytest --cov

smoke:
	$(PYTHON) scripts/release_bootstrap_smoke.py

build:
	if command -v uv >/dev/null 2>&1; then \
		uv build; \
	else \
		$(PYTHON) -m build; \
	fi

verify: lint conformance coverage smoke build

clean:
	rm -rf .pytest_cache build dist src/*.egg-info
	find scripts src tests -type d -name '__pycache__' -prune -exec rm -rf {} +
