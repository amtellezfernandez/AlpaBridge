# Baseline And Final Audit Report

This report records the command evidence for the contract-validation matrix
(CVM) release surface. Commands were run from the repository root with the
locked `uv run python` environment that CI exercises. Temporary raw logs were
not tracked; rerun the commands below to reproduce the release checks.

## Current Release Gate Evidence

| Command | Start UTC | End UTC | Duration | Exit | Result |
|---|---|---|---:|---:|---|
| `.venv/bin/python -m ruff check ...` | 2026-07-19T00:00:00Z | 2026-07-19T00:00:04Z | 3.7s | 0 | Touched source, scripts, and tests passed lint. |
| `.venv/bin/python -m pytest -q tests/` | 2026-07-19T00:00:00Z | 2026-07-19T00:00:03Z | 2.9s | 0 | 318 passed, 14 skipped, and 15 subtests passed. |
| `.venv/bin/python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results` | 2026-07-19T00:00:00Z | 2026-07-19T00:00:01Z | 0.2s | 0 | Regenerated the aggregate summary and paper-number macros, including external-conformance fields. |
| `./scripts/build_cvm_paper.sh` | 2026-07-19T00:00:00Z | 2026-07-19T00:00:01Z | 1.0s | 0 | Rebuilt the 6-page root `wod2sim.pdf` at 126223 bytes. |
| `.venv/bin/python scripts/validate_cvm_submission.py` | 2026-07-19T00:00:00Z | 2026-07-19T00:00:01Z | 0.5s | 0 | WOD2Sim paper validation passed. |
| `pdfinfo wod2sim.pdf` and `qpdf --check wod2sim.pdf` | 2026-07-19T00:00:00Z | 2026-07-19T00:00:01Z | <1s | 0 | PDF is 6 pages, portrait A4, 126223 bytes, and has no syntax or stream encoding errors reported by `qpdf`. |
| `.venv/bin/python -m build` | 2026-07-19T00:00:00Z | 2026-07-19T00:00:03Z | 2.4s | 0 | Source distribution and wheel built successfully with network-enabled build isolation. |

## Important Warnings

- Previous full-verify baseline evidence is retained for traceability:
  `make paper-verify PYTHON='uv run python'` rebuilt the root PDF and passed
  submission validation; `make cvm-check PYTHON='uv run python'` passed with
  311 passed, 14 skipped, and 15 subtests passed; coverage previously measured
  62.61% against the configured 33.0% minimum.
- The Docker-heavy `make verify` target was not rerun in the final controlled
  cleanup pass to avoid stressing the WSL environment. Its component gates were
  run directly where safe: lint, full unit tests, aggregate generation, paper
  build, submission validation, PDF structure checks, and package build.
- `make cvm-eval` exits 2 because the mixed core matrix preserves optional
  direct actor-aware rows without the required scene-matched oracle actor
  proxy. This is a recorded optional-extension precondition blocker, not a
  public-core test failure.
- The local validator uses `mutool` and LaTeX log/source checks, including a
  parsed MediaBox pass that rejects non-A4 page geometry and a font-descriptor
  pass that rejects unembedded paper fonts. CI installs Poppler and `qpdf` to
  run `pdfinfo`, `pdffonts`, and `qpdf --check` on the canonical paper PDF.
- Learned-policy tests remain skipped unless a legitimate local checkpoint is
  configured. No learned-policy result is claimed.

## Current Interpretation

The release status is complete with documented limitations for the CVM paper
package. It supports a completed dependency-light public core, semantic
route-boundary ablation evidence, false-block accounting for audit-valid rows,
and secondary synthetic lifecycle/fault conformance diagnostics. It does not
support a policy-quality benchmark, learned-policy result, direct-actor
temporal ablation, simulator-backed lifecycle/fault stress trial, or official
Waymo compatibility claim.

The validator now treats the integration-vs-policy boundary as a release gate:
blocked, failed, planned, and diagnostic rows cannot be labeled
policy-failure-attributable unless the corresponding manifest is explicitly
claim-valid. Aggregate summary logic separately labels completed full-contract
audit-valid rows as policy-behavior-attributable diagnostic evidence. The
manifest rule must name semantic, temporal, lifecycle, deployment, and evidence
gates before policy behavior or policy failure can be attributed to the
integrated policy.

The latest refresh also validates the aggregate-level attribution partition:
policy-failure rows cannot exceed policy-behavior rows, claim-valid benchmark
rows cannot exceed policy-behavior-attributable rows, policy-behavior rows must
match contract-valid closed-loop rows, and policy-attributed plus
non-policy-attributed rows must cover the full CVM denominator.
It also validates the scenario-coverage partition: scenario-category coverage
cannot be claimed while required categories are unverified or any closed-loop
scene remains unclassified.
It also checks that the aggregate-status bullets in
`artifacts/cvm/reports/claim_evidence_matrix.md` match the current
`artifacts/cvm/results/summary.json` counts.
It validates every `paper_numbers.tex` macro against `summary.json`,
`lifecycle_stress.csv`, and `fault_injection.csv` rather than trusting the
table hash alone.
It now also validates the generated table row values against the current
`summary.json`, `lifecycle_stress.csv`, and `fault_injection.csv` source fields,
so a table cannot drift while keeping a matching artifact hash. The generated
core policy table now also reports latency-p95 availability and terminal
service-crash rows from the retained CVM evidence.
It now rejects package metadata that drops the author, README, BSD-3-Clause
license expression, research keywords, publication classifiers, or repository,
documentation, paper, and citation URLs.
It now rejects CI workflow drift that drops package, conformance, coverage,
smoke, wheel-install, paper-validation, PDF-structure, artifact-upload, or
minimal permission gates.
It now rejects missing or repository-escaping local links and image references
from public Markdown/HTML files, while allowing external URLs.
It now requires public Markdown/HTML images, including remote images, to carry
non-empty alt text.
It now rejects `docs/cli.md` drift from console scripts declared in
`pyproject.toml` and `.PHONY` Make targets.
It now requires the README visual overview to explain the adapter boundary,
claim-validity disclaimer, runtime graphs, and that the graphs do not evaluate
policy quality.
It now requires the evaluation guide to state that completed local closed-loop
rows are diagnostic integration evidence, not a public policy benchmark.
It now requires GitHub contribution, pull-request, issue, and security templates
to preserve the claim boundary and restricted-asset hygiene.
It now rejects venue-style benchmark labels from public release text.
It now rejects unstable generated citation slugs from public release text.
It now validates the README failure-attribution count sentence against
`artifacts/cvm/results/summary.json`.
