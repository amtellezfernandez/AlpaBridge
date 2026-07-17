PYTHON ?= python3
PAPER_PDF ?= wod2sim.pdf
CONFORMANCE_TESTS ?= tests/
DEMO_OUTPUT ?= demo/wod2sim-contract-demo

.PHONY: paper paper-verify lint conformance coverage test smoke build demo verify clean
.PHONY: sii2027-inventory sii2027-check sii2027-demo sii2027-eval sii2027-synthetic sii2027-aggregate
.PHONY: sii2027-paper sii2027-validate sii2027-all

paper:
	$(MAKE) sii2027-paper PYTHON=$(PYTHON)

paper-verify:
	$(MAKE) sii2027-paper PYTHON=$(PYTHON)

test:
	$(PYTHON) -m pytest tests/

lint:
	$(PYTHON) -m ruff check .

conformance:
	WOD2SIM_CORE_CONFORMANCE=1 $(PYTHON) -m pytest -q $(CONFORMANCE_TESTS)

coverage:
	$(PYTHON) -m pytest --cov

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

sii2027-inventory:
	./scripts/sii2027_inventory.sh

sii2027-check: lint conformance
	$(PYTHON) scripts/validate_sii2027_submission.py

sii2027-demo:
	$(PYTHON) scripts/run_synthetic_contract_demo.py --output artifacts/sii2027/results/demo --overwrite --json

sii2027-eval:
	$(PYTHON) scripts/run_sii2027_matrix.py --config configs/sii2027/core.yaml --output artifacts/sii2027/results/core --resume

sii2027-synthetic:
	$(PYTHON) scripts/run_sii2027_matrix.py --config configs/sii2027/lifecycle_stress.yaml --output artifacts/sii2027/results/lifecycle_stress --resume --execute
	$(PYTHON) scripts/run_sii2027_matrix.py --config configs/sii2027/fault_injection.yaml --output artifacts/sii2027/results/fault_injection --resume --execute

sii2027-aggregate:
	$(PYTHON) scripts/aggregate_sii2027.py --inputs artifacts/sii2027/results --output artifacts/sii2027/results
	$(PYTHON) scripts/generate_sii2027_figures.py --summary artifacts/sii2027/results/summary.json --runs artifacts/sii2027/results/runs.csv --output artifacts/sii2027

sii2027-paper:
	./scripts/build_sii2027_paper.sh

sii2027-validate:
	$(PYTHON) scripts/validate_sii2027_submission.py

sii2027-all: sii2027-inventory sii2027-check sii2027-demo sii2027-synthetic
	$(MAKE) sii2027-eval PYTHON=$(PYTHON); status=$$?; \
	if [ "$$status" -ne 0 ] && [ "$$status" -ne 2 ]; then exit "$$status"; fi; \
	$(MAKE) sii2027-aggregate PYTHON=$(PYTHON); \
	$(MAKE) sii2027-paper PYTHON=$(PYTHON); \
	$(MAKE) sii2027-validate PYTHON=$(PYTHON); \
	exit "$$status"

clean:
	rm -rf .pytest_cache build dist src/*.egg-info $(DEMO_OUTPUT)
	find scripts src tests -type d -name '__pycache__' -prune -exec rm -rf {} +
	$(MAKE) -C paper clean
