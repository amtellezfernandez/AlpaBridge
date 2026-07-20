PYTHON ?= $(shell if command -v uv >/dev/null 2>&1; then printf 'uv run python'; else printf 'python3'; fi)
PAPER_PDF ?= alpabridge.pdf
CONFORMANCE_TESTS ?= tests/

.PHONY: lint conformance coverage test smoke build verify clean
.PHONY: paper paper-verify cvm-inventory cvm-check cvm-demo cvm-eval cvm-diagnostics
.PHONY: cvm-synthetic cvm-aggregate cvm-paper cvm-validate cvm-all

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

verify: lint conformance coverage smoke build paper-verify

paper:
	$(MAKE) cvm-paper PYTHON='$(PYTHON)'

paper-verify:
	$(MAKE) cvm-paper PYTHON='$(PYTHON)'
	$(MAKE) cvm-validate PYTHON='$(PYTHON)'

cvm-inventory:
	PYTHON='$(PYTHON)' ./scripts/cvm_inventory.sh

cvm-check: lint conformance
	$(PYTHON) scripts/validate_cvm_submission.py

cvm-demo:
	$(PYTHON) scripts/run_synthetic_contract_demo.py --output artifacts/cvm/results/demo --overwrite --json

cvm-eval:
	$(PYTHON) scripts/run_cvm_matrix.py --config configs/cvm/core.yaml --output artifacts/cvm/results/core --resume

cvm-diagnostics:
	$(PYTHON) scripts/run_diagnostic_experiment.py

cvm-synthetic:
	$(PYTHON) scripts/run_cvm_matrix.py --config configs/cvm/lifecycle_stress.yaml --output artifacts/cvm/results/lifecycle_stress --resume --execute
	$(PYTHON) scripts/run_cvm_matrix.py --config configs/cvm/fault_injection.yaml --output artifacts/cvm/results/fault_injection --resume --execute
	$(MAKE) cvm-diagnostics PYTHON='$(PYTHON)'

cvm-aggregate:
	$(PYTHON) scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results
	$(PYTHON) scripts/generate_cvm_figures.py --summary artifacts/cvm/results/summary.json --runs artifacts/cvm/results/runs.csv --output artifacts/cvm

cvm-paper:
	./scripts/build_cvm_paper.sh

cvm-validate:
	$(PYTHON) scripts/validate_cvm_submission.py

cvm-all: cvm-inventory cvm-check cvm-demo cvm-synthetic
	$(MAKE) cvm-eval PYTHON='$(PYTHON)'; status=$$?; \
	if [ "$$status" -ne 0 ] && [ "$$status" -ne 2 ]; then exit "$$status"; fi; \
	$(MAKE) cvm-aggregate PYTHON='$(PYTHON)'; \
	$(MAKE) cvm-paper PYTHON='$(PYTHON)'; \
	$(MAKE) cvm-validate PYTHON='$(PYTHON)'; \
	exit "$$status"

clean:
	rm -rf .pytest_cache build dist src/*.egg-info
	find scripts src tests -type d -name '__pycache__' -prune -exec rm -rf {} +
	$(MAKE) -C paper clean
