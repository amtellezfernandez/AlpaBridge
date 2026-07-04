.PHONY: paper paper-verify test build verify clean

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
		tests/test_alpasim_setup_scripts.py \
		tests/test_check_alpasim_readiness.py \
		tests/test_run_alpasim_scene_batch.py \
		tests/test_audit_alpasignal_bridge.py

build:
	python -m build

verify: test build paper-verify

clean:
	rm -rf .pytest_cache build dist src/*.egg-info
	find scripts src tests -type d -name '__pycache__' -prune -exec rm -rf {} +
	$(MAKE) -C paper clean
