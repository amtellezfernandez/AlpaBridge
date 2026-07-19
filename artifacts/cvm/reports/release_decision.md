# Release Decision

The current WOD2Sim public release is ready as a bounded
integration-attribution artifact. The contract-validation matrix (CVM) is the
release evidence surface for this decision. It is not a policy-quality
benchmark release.

## Claim-Ready

- WOD2Sim separates integration/precondition/evidence failures from policy
  behavior and policy-failure attribution.
- The dependency-light public core executes as auditable AlpaSim external
  drivers.
- The semantic route-loss invalidation experiment is claim-ready at the
  attribution boundary: 15/15 command-only rows satisfy a defined status-only
  acceptance baseline, and WOD2Sim rejects the same rows as non-claim-valid
  route evidence.
- Only 14/15 semantic pairs are comparison-eligible; their score deltas are
  descriptive and do not support a systematic policy-effect claim.
- The paper PDF, generated tables, figures, aggregate summaries, manifests, and
  public reports are reproducible through the CVM release targets.

## Not Claim-Ready

- Learned-policy performance.
- Direct actor-aware planning.
- Temporal scene ablation with direct-actor oracle proxy.
- Scenario-category coverage.
- Official Waymo or challenge leaderboard compatibility.
- Complete public policy benchmark status.

## Verification Gate

The release decision depends on these tracked gates remaining green:

- `uv run python scripts/validate_cvm_submission.py`
- `uv run python -m pytest -q tests/`
- `make cvm-check PYTHON='uv run python'`
- `make paper-verify PYTHON='uv run python'`
- `qpdf --check wod2sim.pdf`

If any paper number, table, figure, manifest, or PDF metadata changes, rebuild
through the CVM targets and rerun the gates above before treating the release as
public-ready.
