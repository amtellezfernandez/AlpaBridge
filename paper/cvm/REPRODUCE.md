# Reproducing Current WOD2Sim CVM Artifacts

Current status: buildable WOD2Sim paper draft with completed dependency-light
core rows, completed semantic closed-loop ablation rows, public synthetic
lifecycle/fault diagnostics, and explicit direct-actor blockers.

## Quality Gates

```bash
make cvm-check PYTHON=./.venv/bin/python
```

This runs lint, dependency-light conformance tests, and paper-artifact
validation.

## Matrix Expansion And Execution

Record core launch plans without launching:

```bash
./.venv/bin/python scripts/run_cvm_matrix.py \
  --config configs/cvm/core.yaml \
  --output artifacts/cvm/results/core \
  --resume
```

Execute supported local closed-loop rows:

```bash
./.venv/bin/python scripts/run_cvm_matrix.py \
  --config configs/cvm/core.yaml \
  --output artifacts/cvm/results/core \
  --resume \
  --execute
```

Execute the completed semantic route-boundary CVM:

```bash
./.venv/bin/python scripts/run_cvm_matrix.py \
  --config configs/cvm/semantic_ablation.yaml \
  --output artifacts/cvm/results/semantic_ablation \
  --resume \
  --execute
```

The command-only route arm is explicit and non-default:
`WOD2SIM_ROUTE_CONTRACT_MODE=command_only_route`. AlpaSim video rendering is
disabled in CVM configs with `eval.video.render_video=false`.

The `seed` column is a configured replicate identifier. It is recorded in
manifests and run IDs, but it is not yet forwarded as a deterministic AlpaSim
runtime seed override. Runtime seed metadata is logged when the patched
external-driver input exposes it.

## Public Synthetic Diagnostics

```bash
make cvm-synthetic PYTHON=./.venv/bin/python
```

These rows are service-harness diagnostics only; they are not closed-loop scene
rollouts and remain `claim_valid=false`.

## Aggregate, Figures, And Paper

```bash
make cvm-aggregate PYTHON=./.venv/bin/python
make cvm-paper PYTHON=./.venv/bin/python
make cvm-validate PYTHON=./.venv/bin/python
```

The output PDF is the repository-root `wod2sim.pdf`. The `paper/cvm/`
directory contains the source and generated TeX inputs, not a second tracked
paper PDF.

## Current Claim Boundary

- Configured rows: 145.
- Attempted rows: 109.
- Completed rows: 109.
- Closed-loop completed rows: 54.
- Full-contract rows audit-valid: 45/45.
- Valid full-contract false-blocked rows: 0/45.
- Matched semantic metric pairs: 9/9.
- Command-only rows rejected as non-claim-valid: 9/9.
- Planned rows: 0.
- Blocked rows: 36.
- Claim-valid benchmark matrix: 0.

The current aggregate supports dependency-light core execution, a bounded
semantic integration-effectiveness claim, and an evidence-gate claim. It does
not support direct-actor temporal ablation, learned-policy result, or
policy-quality comparison.

Failure attribution is explicit in `artifacts/cvm/results/summary.json` under
`failure_attribution`. A behavior row is policy-attributable only after route,
sensor, lifecycle, deployment, and evidence gates pass. Contract-invalid rows,
blocked rows, planned rows, and synthetic diagnostics must be reported as
integration/precondition/evidence states, not policy failures.
