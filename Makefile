PYTHON ?= python3
PAPER_PDF ?= wod2sim.pdf
CONFORMANCE_TESTS ?= tests/
DEMO_OUTPUT ?= demo/wod2sim-contract-demo

.PHONY: paper paper-verify lint conformance coverage test smoke build demo verify clean

paper:
	$(MAKE) -C paper
	cp paper/paper.pdf $(PAPER_PDF)

# Rebuild in a temp dir so verification does not rewrite the tracked PDF.
paper-verify:
	tmpdir="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmpdir"' EXIT; \
	cp -R paper/. "$$tmpdir"/; \
	cd "$$tmpdir" && pdflatex paper && bibtex paper && pdflatex paper && pdflatex paper

test:
	pytest tests/

lint:
	ruff check .

conformance:
	WOD2SIM_CORE_CONFORMANCE=1 pytest -q $(CONFORMANCE_TESTS)

coverage:
	pytest --cov

smoke:
	$(PYTHON) scripts/release_bootstrap_smoke.py

demo:
	$(PYTHON) scripts/run_synthetic_contract_demo.py --output $(DEMO_OUTPUT) --overwrite --json

build:
	if command -v uv >/dev/null 2>&1; then \
		uv build; \
	else \
		$(PYTHON) -m build; \
	fi

verify: lint conformance coverage smoke build paper-verify

clean:
	rm -rf .pytest_cache build dist src/*.egg-info $(DEMO_OUTPUT)
	find scripts src tests -type d -name '__pycache__' -prune -exec rm -rf {} +
	$(MAKE) -C paper clean
