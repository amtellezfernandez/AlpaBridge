# Release Test Report

This report records the final controlled validation of the contract-validation
matrix (CVM) release surface on 2026-07-20. Commands ran from the repository
root in the locked `uv run python` environment.

## Release Gates

| Command | Result |
|---|---|
| `make verify PYTHON='uv run python'` | Passed: lint, conformance, coverage, install smoke, package build, paper build, and submission validation. |
| `WOD2SIM_CORE_CONFORMANCE=1 uv run python -m pytest -q tests/` | 359 passed, 14 skipped, and 15 subtests passed. |
| `uv run python -m pytest --cov` | 359 passed, 14 skipped; total coverage 65.33% against the configured 33.0% minimum. |
| `uv run python scripts/run_diagnostic_experiment.py` | Passed: 15 faults plus 15 valid controls; WOD2Sim classified 30/30 and localized 15/15 with 0/15 control false positives; the status-only gate classified 15/30 and detected no faults. Counts are descriptive for the designed suite. |
| `./scripts/run_alpasim_replay_demo.sh` | Passed: both live gRPC arms returned 60/60 finite outputs; the full-contract audit was clean and the command-only audit isolated `semantic.command_only`; generated media and evidence hashes validate. |
| `uv run python scripts/run_cvm_matrix.py --config configs/cvm/fault_injection.yaml --output artifacts/cvm/results/fault_injection --resume --execute` | Passed: 15/15 label-withheld fault rows completed. |
| `uv run python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results` | Passed and regenerated summary/table macros from the current diagnostic schema. |
| `./scripts/build_cvm_paper.sh` | Passed: rebuilt the 5-page, 200108-byte A4 `wod2sim.pdf`. |
| `uv run python scripts/validate_cvm_submission.py` | Passed all source, artifact, claim-boundary, metadata, PDF, and reference-resolution checks. |
| `uv build` | Built `dist/wod2sim-0.1.0.tar.gz` and `dist/wod2sim-0.1.0-py3-none-any.whl`. |
| `qpdf --check wod2sim.pdf` | No syntax or stream encoding errors. |
| `pdfinfo wod2sim.pdf` | 5 portrait A4 pages, 200108 bytes, expected title/author/subject metadata. |
| `pdffonts wod2sim.pdf` | All listed fonts are embedded and subset; no Type 3 fonts. |
| `git diff --check` | Passed. |

The current five-page revision was not uploaded to the public PaperPlaza PDF
checker from this environment. An earlier four-page draft passed that external
check; the current revision is supported by the local structural, font,
MediaBox, metadata, and LaTeX-log gates above.

## Targeted Selections

| Selection | Result |
|---|---|
| `tests -k "semantic or route"` | 18 passed, 355 deselected. |
| `tests -k "temporal or resampl"` | 15 passed, 358 deselected, 15 subtests passed. |
| `tests -k "lifecycle or session"` | 20 passed, 353 deselected. |
| `tests -k "plugin or entry_point"` | 6 passed, 367 deselected. |
| `tests -k "deployment or readiness or launch"` | 23 passed, 350 deselected. |
| `tests -k "evidence or audit or benchmark"` | 33 passed, 340 deselected. |
| `tests -k "fault"` | 13 passed, 360 deselected. |

## Timing Scope

The frozen diagnostic artifact contains 3,000 fault-case detector samples and
1,000 paired adapter-path samples over 15 valid sessions. The guarded in-process
adapter Drive path includes state-to-input assembly, prediction, trajectory
serialization, finite-output validation, reasoning parsing, and in-memory
telemetry. It excludes gRPC transport, file I/O, simulator execution, and human
investigation. Accordingly, these checks do not establish simulator end-to-end
runtime overhead or human time-to-diagnosis.

The separate protocol replay measures complete host-loopback client-to-service
gRPC calls: full-contract latency is 1.786 ms median and 2.191 ms p95, and
command-only latency is 1.835 ms median and 2.338 ms p95. Its recorded inputs
are non-reactive, so it does not measure simulator stepping, closed-loop
feedback, format overhead, or human diagnosis time.

Passing tests support contract behavior, artifact integrity, and the declared
designed-suite results. They do not establish policy quality, population-level
fault performance, superiority to another integration framework, or human
debugging-time improvement.
