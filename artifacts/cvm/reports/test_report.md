# Release Test Report

This report records the validation commands for the contract-validation matrix
(CVM) release surface. Raw command logs are intentionally not tracked; rerun
these commands from the repository root to reproduce the checks. The latest
refresh used the locked `uv run python` environment.

| Command | Result |
|---|---|
| `./scripts/build_cvm_paper.sh` | Latest controlled pass rebuilt the 6-page root `wod2sim.pdf` at 127189 bytes. |
| `uv run python scripts/validate_cvm_submission.py` | Passed, including metadata-backed title/author/affiliation/abstract checks, output-PDF title/author/subject checks, IEEE A4 source-layout checks, parsed PDF A4 MediaBox checks, LaTeX log warnings, canonical-to-paper generated asset sync, generated-table row/source-field value sync, package metadata checks, CI workflow gate checks, community-template claim-boundary checks, public local-reference and image-alt checks, CLI command-documentation drift checks, README visual/graph explanation checks, evaluation-status checks, venue-style benchmark-label checks, unstable generated citation-slug hygiene checks, README attribution-count sync, paper-number macro value sync, claim-evidence-matrix count sync, contract-test audit coverage checks, embedded PDF font descriptors, manifest-level failure-attribution checks, summary-level attribution and scenario-coverage partition checks, generic credential-leak checks, and README/paper claim-boundary checks. |
| `make paper-verify PYTHON='uv run python'` | Passed: rebuilt 6-page root `wod2sim.pdf` and ran submission validation. |
| `make conformance PYTHON='uv run python'` | Previously passed through `make verify`: 311 passed, 14 skipped, 15 subtests passed. |
| `make demo PYTHON='uv run python'` | Passed: synthetic demo valid with `valid_claim_evidence=false`. |
| `make cvm-check PYTHON='uv run python'` | Previously passed: ruff clean, 311 passed, 14 skipped, 15 subtests passed, validation passed. |
| `make cvm-eval PYTHON='uv run python'` | Expected exit 2: current aggregate retains 30 completed dependency-light public-core rows, 30 completed semantic-ablation rows, and 33 optional gated blockers. |
| `.venv/bin/python -m pytest -q tests/` | Latest controlled pass: 318 passed, 14 skipped, 15 subtests passed. |
| `uv run python -m pytest --cov` | Previously passed through `make verify`: 311 passed, 14 skipped, total coverage 62.61% against the configured 33.0% minimum. Not rerun in the final WSL-safe cleanup pass. |
| `.venv/bin/python -m build` | Latest controlled pass built source distribution and wheel with network-enabled build isolation. |
| `uv run pre-commit run --all-files` | Passed without modifying files. |
| `qpdf --check wod2sim.pdf && pdfinfo wod2sim.pdf` | Latest controlled pass: 6 pages, portrait A4, 127189 bytes, and no syntax or stream encoding errors reported by `qpdf`. |
| `git diff --check` | Run as final whitespace validation. |

Targeted contract selections:

| Selection | Result |
|---|---|
| `tests -k "semantic or route"` | 10 passed, 312 deselected. |
| `tests -k "temporal or resampl"` | 10 passed, 312 deselected, 15 subtests passed. |
| `tests -k "lifecycle or session"` | 10 passed, 312 deselected. |
| `tests -k "plugin or entry_point"` | 5 passed, 317 deselected. |
| `tests -k "deployment or readiness or launch"` | 20 passed, 302 deselected. |
| `tests -k "evidence or audit or benchmark"` | 27 passed, 295 deselected. |
| `tests -k "fault"` | 5 passed, 317 deselected. |

The release claim boundary is intentionally narrower than the test suite:
passing tests support contract behavior and artifact hygiene, while policy
quality and official benchmark claims require separate completed evidence.
The submission validator now fails if a CVM run manifest omits or contradicts
the integration-vs-policy `failure_attribution` record.
It requires the attribution rule to name semantic, temporal, lifecycle,
deployment, and evidence gates before any policy-behavior or policy-failure
claim.
It also fails if README or paper text drops the failure-attribution boundary,
or if the aggregate summary no longer partitions policy-attributable and
non-policy-attributed rows over the complete CVM denominator.
It also validates the public `frames.csv` schema so frame-level timing, route,
trajectory, latency, lifecycle-warning, and policy-status fields cannot
silently disappear from regenerated artifacts.
It now rejects a paper PDF if any discovered font lacks an embedded
`/FontFile`, `/FontFile2`, or `/FontFile3` descriptor.
It rejects a paper PDF whose parsed MediaBox is not portrait A4.
It rejects generated PDF title, author, or subject drift from
`paper/cvm/metadata.json`.
It also rejects title, author, affiliation, PDF-subject, abstract word-count, or
abstract-source drift against `paper/cvm/metadata.json`.
It rejects manuscript-source page, margin, font-scaling, page-style, and
negative-spacing overrides so the IEEE A4 template remains unmodified.
It rejects unresolved citations/references, multiply defined labels, and
overfull or underfull `\hbox` warnings in the generated LaTeX log.
It rejects drift between canonical generated artifacts under `artifacts/cvm`
and the paper-side copies under `paper/cvm/generated` and `paper/cvm/figures`.
It rejects `paper_numbers.tex` macro drift from `summary.json`,
`lifecycle_stress.csv`, and `fault_injection.csv`.
It rejects generated table row drift from `summary.json`,
`lifecycle_stress.csv`, and `fault_injection.csv`, including missing or
non-integer source fields.
It rejects missing public-core policy rows in `main_results.tex`, including
latency-p95 and terminal service-crash columns, and preserves tracked public
closed-loop metrics when ignored raw run directories are absent.
It rejects package metadata that drops the author, README, BSD-3-Clause license
expression, research keywords, publication classifiers, or repository,
documentation, paper, and citation URLs.
It rejects CI workflow drift that drops package, conformance, coverage, smoke,
wheel-install, paper-validation, PDF-structure, artifact-upload, or minimal
permission gates.
It rejects missing or repository-escaping local links and image references from
public Markdown/HTML files while allowing external URLs.
It rejects public Markdown/HTML images, including remote images, without
non-empty alt text.
It rejects `docs/cli.md` drift from console scripts declared in
`pyproject.toml` and `.PHONY` Make targets.
It rejects README visual sections that omit the adapter-boundary disclaimer,
runtime graph explanations, or the statement that graphs do not evaluate
policy quality.
It rejects evaluation-guide status text that omits completed local diagnostic
closed-loop rows or misstates them as public policy benchmark evidence.
It rejects GitHub contribution, pull-request, issue, and security templates
that drop the claim boundary or restricted-asset hygiene.
It rejects venue-style benchmark labels from public release text.
It rejects unstable generated citation slugs from public release text.
It rejects README failure-attribution count drift from
`artifacts/cvm/results/summary.json`.
It rejects aggregate-count drift between
`artifacts/cvm/reports/claim_evidence_matrix.md` and
`artifacts/cvm/results/summary.json`.
It rejects repository-inventory drift from the actual top-level
`tests/test_*.py` file count and keeps runtime pass/skip counts in
`test_report.md`.
It rejects historical `.venv` baseline-report evidence and stale hardening-era
pass counts from the public baseline report.
It rejects a missing or incomplete
`artifacts/cvm/reports/contract_test_audit.md`; that audit must name semantic,
temporal, lifecycle, deployment/plugin-dependency, evidence, and
fault-injection coverage, explicit gaps kept out of policy claims, and only
existing test files.
