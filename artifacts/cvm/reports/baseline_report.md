# Baseline And Final Audit Report

This report records the final command evidence for the contract-validation
matrix (CVM) release surface. Commands ran from the repository root on
2026-07-20 with the locked `uv run python` environment used by CI.

## Current Release Gate Evidence

| Command | Result |
|---|---|
| `uv run python -m ruff check .` | Passed. |
| `WOD2SIM_CORE_CONFORMANCE=1 uv run python -m pytest -q tests/` | 373 passed, 14 skipped, and 15 subtests passed. |
| `uv run python -m pytest --cov` | 373 passed, 14 skipped; 65.31% against the configured 33.0% minimum. |
| `uv run python scripts/run_diagnostic_experiment.py` | Generated 15 current-adapter controls, 15 label-withheld faults, exact descriptive comparator counts, post-parse detector timing, and paired in-process adapter Drive-path timing. |
| `./scripts/run_alpasim_replay_demo.sh` | Executed four 60-call gRPC arms, verified the official AlpaSim recording and NAVSIM checkpoint hashes, and regenerated telemetry, paired trajectories, and real-camera media. |
| `uv run python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results` | Regenerated the aggregate summary and paper macros from diagnostic schema v3. |
| `make cvm-check PYTHON='uv run python'` | Passed lint, conformance, and submission validation. |
| `make paper-verify PYTHON='uv run python'` | Passed the deterministic six-page paper rebuild and submission validation. |
| `make verify PYTHON='uv run python'` | Passed lint, conformance, coverage, install smoke, package build, paper rebuild, and submission validation. |
| `uv build` | Built the source distribution and wheel. |
| `qpdf --check wod2sim.pdf`, `pdfinfo wod2sim.pdf`, and `pdffonts wod2sim.pdf` | The PDF is 6 pages, portrait A4, 206932 bytes, uses embedded subset Type 1 fonts, and has no syntax or stream encoding errors reported by `qpdf`. |

## Important Warnings

- The current six-page revision was not uploaded to the public PaperPlaza PDF
  checker from this environment. An earlier four-page draft passed; the current
  file passes the repository's local structure, MediaBox, font, metadata, and
  LaTeX-log checks.
- `make cvm-eval` can exit 2 because the mixed matrix retains optional
  direct-actor rows without the required scene-matched oracle actor proxy. This
  is an explicit optional-extension precondition blocker, not a public-core test
  failure.
- Optional learned-policy benchmark tests remain skipped unless their gated
  inputs are configured. Separately, the hash-pinned official NAVSIM checkpoint
  was executed as a non-reactive policy-signature negative control and one
  bounded reactive external-driver lifecycle. The reactive fixture repeats a
  recorded camera seed on declared flat ground; no learned-policy quality or
  visual-policy result is claimed.
- The human time-to-diagnosis question cannot be answered from automated
  repository execution. It requires real participants, controlled tasks, and a
  separate study protocol.

## Current Interpretation

The release supports the completed dependency-light public core, semantic
route-boundary diagnostics, a defined completion-and-metrics comparator,
contract-gated attribution, 15 designed fault mutations paired with 15 valid
current-adapter sessions, post-parse detector timing, and an in-process adapter
Drive-path timing ablation. The separate four-arm replay supports bounded
client-to-service timing, a route-loss consequence for route following, and an
exact 60/60 learned command-native negative control.
The additional reactive artifact supports 1/1 camera-blind learned rollout,
197/197 finite outputs, and exact-configuration service/runtime observations;
it does not support comparative overhead or policy quality.

The adapter measurement includes state-to-input assembly, prediction,
trajectory serialization, finite-output validation, reasoning parsing, and
in-memory telemetry. It excludes gRPC transport, file I/O, simulator work, and
human investigation. It therefore does not support simulator end-to-end
runtime overhead or human time-to-diagnosis.

The release does not support a policy-quality benchmark, learned-policy
performance, a completed direct-actor temporal ablation, natural-fault
prevalence, comparison against an independently maintained integration
framework, or official Waymo benchmark compatibility. Counts from the
controlled mutation suite are exact descriptive results for that designed set;
no population confidence interval or hypothesis test is reported.
