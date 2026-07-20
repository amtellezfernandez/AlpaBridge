# Release Test Report

This report records the final controlled validation of the contract-validation
matrix (CVM) release surface on 2026-07-20. Commands ran from the repository
root in the locked `uv run python` environment.

## Release Gates

| Command | Result |
|---|---|
| `make verify PYTHON='uv run python'` | Passed: lint, conformance, coverage, install smoke, package build, paper build, and submission validation. |
| `WOD2SIM_CORE_CONFORMANCE=1 uv run python -m pytest -q tests/` | 392 passed, 14 skipped, and 15 subtests passed. |
| `uv run python -m pytest --cov` | 392 passed, 14 skipped; total coverage 65.43% against the configured 33.0% minimum. |
| `tests/test_waymax_contract_study.py` | 19 passed, covering the retained artifact recomputation, factorial interaction, route-dependent audit, exact negative control, route selection, planner/action contracts, metrics, and pinned-checkout gate. |
| `uv run python scripts/run_diagnostic_experiment.py` | Passed: 15 faults plus 15 valid controls; WOD2Sim classified 30/30 and localized 15/15 with 0/15 control false positives; the status-only gate classified 15/30 and detected no faults. Counts are descriptive for the designed suite. |
| `docker run ... -m wod2sim.challenge.e2e_driver --self-test --self-test-iterations 8 --model navsim_ego_status_mlp ...` | Passed against the official seed-0 SHA-256: 8/8 Drive calls returned within 100 ms with no target miss. This is a model/service self-test, not a benchmark. |
| `./scripts/run_alpasim_replay_demo.sh` | Passed: four live gRPC arms returned 60/60 finite, nonstationary outputs. Route loss isolated `semantic.command_only` and changed 56/60 route-following endpoints; the official NAVSIM negative control had no fault and 60/60 exact output matches. Generated media and evidence hashes validate. |
| `uv run python scripts/run_cvm_matrix.py --config configs/cvm/fault_injection.yaml --output artifacts/cvm/results/fault_injection --resume --execute` | Passed: 15/15 label-withheld fault rows completed. |
| `uv run python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results` | Passed and regenerated summary/table macros from the current diagnostic schema and retained Waymax study. |
| `./scripts/build_cvm_paper.sh` | Passed: rebuilt the 6-page, 302218-byte A4 `wod2sim.pdf`. |
| `uv run python scripts/validate_cvm_submission.py` | Passed all source, artifact, claim-boundary, metadata, PDF, and reference-resolution checks. |
| `uv build` | Built `dist/wod2sim-0.1.0.tar.gz` and `dist/wod2sim-0.1.0-py3-none-any.whl`. |
| `qpdf --check wod2sim.pdf` | No syntax or stream encoding errors. |
| `pdfinfo wod2sim.pdf` | 6 portrait A4 pages, 302218 bytes, expected title/author/subject metadata. |
| `pdffonts wod2sim.pdf` | All listed fonts are embedded and subset; no Type 3 fonts. |
| `git diff --check` | Passed. |

The current six-page revision was not uploaded to the public PaperPlaza PDF
checker from this environment. An earlier four-page draft passed that external
check; the current revision is supported by the local structural, font,
MediaBox, metadata, and LaTeX-log gates above.

## Targeted Selections

| Selection | Result |
|---|---|
| `tests -k "semantic or route"` | 29 passed, 377 deselected. |
| `tests -k "temporal or resampl"` | 15 passed, 391 deselected, 15 subtests passed. |
| `tests -k "lifecycle or session"` | 20 passed, 386 deselected. |
| `tests -k "plugin or entry_point"` | 6 passed, 400 deselected. |
| `tests -k "deployment or readiness or launch"` | 23 passed, 383 deselected. |
| `tests -k "evidence or audit or benchmark"` | 40 passed, 366 deselected. |
| `tests -k "fault"` | 13 passed, 393 deselected. |

## Timing Scope

The frozen diagnostic artifact contains 3,000 fault-case detector samples and
1,000 paired adapter-path samples over 15 valid sessions. The guarded in-process
adapter Drive path includes state-to-input assembly, prediction, trajectory
serialization, finite-output validation, reasoning parsing, and in-memory
telemetry. It excludes gRPC transport, file I/O, simulator execution, and human
investigation. Accordingly, these checks do not establish simulator end-to-end
runtime overhead or human time-to-diagnosis.

Fault-case detector latency is 28.096 us median and 55.774 us p95. The guarded
Drive path is 617.549 us median and 897.100 us p95; its paired guard increment
is 68.871 us median and 309.613 us p95.

The separate protocol replay measures complete host-loopback client-to-service
gRPC calls. Route-following full/reduced latency is 3.769/4.833 ms median/p95
and 3.104/3.958 ms. NAVSIM EgoStatusMLP full/reduced is 4.715/5.945 ms and
4.943/6.963 ms. Its recorded inputs are non-reactive, so it does not measure
simulator stepping, closed-loop feedback, format overhead, or human diagnosis
time.

The separate reactive artifact is validated by
`tests/test_alpasim_navsim_reactive_evidence.py`,
`tests/test_aggregate_cvm.py`, and `tests/test_validate_cvm_submission.py`.
Those tests verify deterministic public-fixture derivation, all retained file
hashes, 197/197 finite outputs, 198 renderer requests, exact timing fields, the
declared static-camera/flat-ground boundary, and rejection of the frozen-camera
negative control. This is one exact-configuration lifecycle measurement, not a
comparative runtime or policy-quality test.

Passing tests support contract behavior, artifact integrity, and the declared
designed-suite results. They do not establish policy quality, population-level
fault performance, superiority to another integration framework, or human
debugging-time improvement.
