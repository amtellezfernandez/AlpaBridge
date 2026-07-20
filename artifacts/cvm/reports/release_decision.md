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
  microbenchmark: median `28.096 us` and p95 `55.774 us` over 3,000 fault-case
  calls. The guarded in-process adapter Drive path is `617.549 us` median and
  `897.100 us` p95. Its paired guard-path increment is `68.871 us` median and
  `309.613 us` p95 over 1,000 pairs across 15 valid sessions.
- The non-reactive protocol replay is claim-ready for client-to-service timing
  and policy-specific semantic applicability: route loss changes 56/60
  route-following endpoints, while NAVSIM EgoStatusMLP is an exact 60/60
  command-native negative control.
- The separate reactive NAVSIM rollout is claim-ready only for its bounded
  lifecycle and exact-configuration timing: 1/1 rollout passes with 197/197
  finite outputs over 19.93 simulated seconds. The repeated camera seed and
  declared flat surface are explicit; the camera-validating control rejects
  the frozen stream after four completed calls.
- Only 14/15 semantic pairs are comparison-eligible; their score deltas are
  descriptive and do not support a systematic policy-effect claim.
- The paper PDF, generated tables, figures, aggregate summaries, manifests, and
  public reports are reproducible through the CVM release targets.

## Not Claim-Ready

- Learned-policy performance.
- Visual or multimodal learned-policy behavior.
- Direct actor-aware planning.
- Temporal scene ablation with direct-actor oracle proxy.
- Scenario-category coverage.
- Official Waymo or challenge leaderboard compatibility.
- Complete public policy benchmark status.
- Ranking against a complete external integration framework.
- Comparative runtime overhead or human time-to-diagnosis.
- Cross-simulator empirical generalization.

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
