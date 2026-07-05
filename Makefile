PYTHON ?= python3

.PHONY: paper paper-verify test smoke build verify clean

paper:
	$(MAKE) -C paper

# Rebuild in a temp dir so verification does not rewrite the tracked PDF.
paper-verify:
	tmpdir="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmpdir"' EXIT; \
	cp -R paper/. "$$tmpdir"/; \
	cd "$$tmpdir" && pdflatex paper && bibtex paper && pdflatex paper && pdflatex paper

test:
	pytest tests/test_alpasim_integration.py \
		tests/test_audit_run_command.py \
		tests/test_support_bundle_command.py \
		tests/test_alpasim_setup_scripts.py \
		tests/test_bootstrap_alpasim_env_script.py \
		tests/test_check_alpasim_readiness.py \
		tests/test_import_alpasim_scene_cache_script.py \
		tests/test_run_alpasim_scene_batch.py \
		tests/test_audit_alpasignal_bridge.py \
		tests/test_release_bootstrap_smoke.py \
		tests/test_wod2sim_doctor.py

smoke:
	$(PYTHON) scripts/release_bootstrap_smoke.py

build:
	if command -v uv >/dev/null 2>&1; then \
		uv build; \
	else \
		$(PYTHON) -m build; \
	fi

verify: test smoke build paper-verify

clean:
	rm -rf .pytest_cache build dist src/*.egg-info
	find scripts src tests -type d -name '__pycache__' -prune -exec rm -rf {} +
	$(MAKE) -C paper clean
