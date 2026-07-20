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
- The controlled diagnostic comparison is claim-ready for its declared case
  set: 30/30 WOD2Sim classifications versus 15/30 status-only, 15/15 fault
  localizations, 0/15 control false positives, and 15/15 discordant pairs
  favoring WOD2Sim. The counts are descriptive for the designed suite.
- Post-parse detector execution is claim-ready only as a software
  microbenchmark: median `11.441 us` and p95 `21.915 us` over 3,000 fault-case
  calls. The guarded in-process adapter Drive path is `257.390 us` median and
  `449.371 us` p95. Its paired guard-path increment is `25.630 us` median and
  `112.659 us` p95 over 1,000 pairs across 15 valid sessions.
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
- Ranking against a complete external integration framework.
- End-to-end runtime overhead or human time-to-diagnosis.

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
