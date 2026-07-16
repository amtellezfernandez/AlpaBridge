PYTHON ?= python3
ARXIV_PDF ?= arxiv.pdf

.PHONY: arxiv paper paper-verify lint coverage test smoke build verify clean

paper: arxiv

arxiv:
	$(MAKE) -C paper
	cp paper/paper.pdf $(ARXIV_PDF)

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

coverage:
	pytest --cov

smoke:
	$(PYTHON) scripts/release_bootstrap_smoke.py

build:
	if command -v uv >/dev/null 2>&1; then \
		uv build; \
	else \
		$(PYTHON) -m build; \
	fi

verify: lint coverage smoke build paper-verify

clean:
	rm -rf .pytest_cache build dist src/*.egg-info
	find scripts src tests -type d -name '__pycache__' -prune -exec rm -rf {} +
	$(MAKE) -C paper clean
