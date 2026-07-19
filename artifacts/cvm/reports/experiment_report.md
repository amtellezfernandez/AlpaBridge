# Contract-Validation Experiment Report

Current status: the public aggregate contains a complete dependency-light
public core, completed semantic closed-loop ablation pairs, secondary public
synthetic lifecycle/fault conformance diagnostics, and explicit optional gated
direct-actor blockers. Raw local rollout directories remain ignored; CSV/JSON
aggregates, manifests, tables, and figures are the public contract-validation
matrix (CVM) evidence.

## Configured Matrices

| Matrix | Rows | Attempted | Completed | Planned | Blocked | Claim-valid |
|---|---:|---:|---:|---:|---:|---:|
| Core closed loop | 45 | 30 | 30 | 0 | 15 | 0 |
| Semantic ablation | 30 | 30 | 30 | 0 | 0 | 0 |
| Temporal ablation | 18 | 0 | 0 | 0 | 18 | 0 |
| Lifecycle stress | 40 | 40 | 40 | 0 | 0 | 0 |
| Fault injection | 15 | 15 | 15 | 0 | 0 | 0 |
| Total | 148 | 115 | 115 | 0 | 33 | 0 |

## Integration-Effectiveness Evidence

- Dependency-light public core: 30/30 completed, 28/30 audit-valid, 0 blocked.
- Full-contract rollouts: 42/45 audit-valid.
- Command-only route rows: 15/15 completed and 15/15 rejected as non-claim-valid.
- Status-only acceptance baseline: 15/15 command-only rows completed with
  metrics, so the defined baseline accepts them.
- Contract-gated route evidence: the same 15/15 rows are rejected as
  route-invalid and cannot support policy attribution.
- Comparison-eligible semantic pairs: 14/15; one pair is excluded because its
  nominal full-contract arm is also route-invalid.
- Mean full-contract minus command-only deltas on eligible pairs: progress
  -0.052, relative progress -0.023, collision-any 0.071, off-road 0.000, and
  plan deviation 0.016. Progress has median 0.000 and range [-0.690, 0.660].

These are route-boundary and evidence-gate measurements, not policy-superiority
claims. The status-only baseline is a defined acceptance rule, not a separate
wrapper or external competitor. The paired deltas are mixed and, with one
uncontrolled execution per arm, do not establish a systematic route-loss or
policy-quality effect. The supported integration result is that the contract
gate keeps completed metric-bearing route-invalid rows out of
policy-attribution claims. The 33 blocked
direct-actor/temporal rows are optional gated extension rows retained as
denominator and blocker context, not public-core dependencies or success
metrics.
The three non-audit-valid full-contract rows are also retained rather than
hidden. They all use scene
`clipgt-0fd06bc3-1899-4b45-9278-c5c018b3968d`, completed with metrics and a
valid sensor pipeline, but 12/199 audited frames fell back to `command_proxy`,
so the route contract correctly keeps those rows outside policy attribution.

## Failure Attribution

- Contract-valid closed-loop rows: 42.
- Integration/evidence-invalid closed-loop rows: 18.
- Precondition-blocked rows: 33.
- Synthetic diagnostic rows: 55.
- Policy-attributable behavior rows: 42.
- Policy-attributable failure rows: 0.
- Completed non-policy diagnostic rows: 73.
- Non-policy-attributed rows: 106.
- Claim-valid policy benchmark rows: 0.

Behavior is policy-attributable only after route/sensor audit, lifecycle state,
deployment preconditions, and evidence gates pass. Rows outside that boundary
are integration, precondition, evidence, or diagnostic rows; they are not policy
failures. A policy failure can be assigned only after the same claim-valid gate
passes and the retained failure layer is policy.

## Scene Metadata

- Every run manifest records `scene_id`, `scenario_category`, asset
  availability, selection rationale, route/interaction feature expectations,
  and license-gating status.
- The 15 local closed-loop scenes are marked
  `available_front_camera_26_02_unclassified` because the public repository does
  not expose authoritative straight/turn/lane-change/traffic/occlusion/merge
  labels.
- The generated coverage gate reports 0/6 verified required scenario categories
  and 15 unclassified closed-loop scenes; scenario-category coverage is not
  claimed.
- Synthetic lifecycle and fault rows are marked as public synthetic harness
  scenes, not closed-loop scene rollouts.

## Remaining Blockers

- `direct_actor_oracle_proxy_missing`: 33 optional gated rows remain blocked
  across direct-actor rows in the mixed core matrix and the temporal-ablation
  matrix. The required proxy must be scene-matched; adapters now reject oracle
  frames whose `scene_id` differs from the current prediction scene.
- The temporal full-vs-naive resampling scene ablation is therefore not claimed.
- Learned `token_dagger_bc` remains outside this CVM because no legitimate
  release checkpoint hash is configured.

## Secondary Synthetic Diagnostics

- Lifecycle stress: 20/20 full-hardening synthetic cycles survived; 0/20
  strict/pre-hardening synthetic cycles survived duplicate-close/late-message
  injection.
- Fault injection: 15/15 configured public synthetic faults were detected and
  localized to the expected contract layer/code.
- These diagnostics are not closed-loop scene rollouts and remain
  `claim_valid=false`. They are retained as service-level conformance checks,
  not as evidence of simulator-backed stress reliability or policy quality.

## Generated Artifacts

- `artifacts/cvm/results/runs.csv`
- `artifacts/cvm/results/failures.csv`
- `artifacts/cvm/results/closed_loop_metrics.csv`
- `artifacts/cvm/results/frames.csv`
- `artifacts/cvm/results/semantic_ablation_pairs.csv`
- `artifacts/cvm/results/summary.json`
- `artifacts/cvm/results/fault_injection.csv`
- `artifacts/cvm/manifests/run_manifests/*.json`
- `artifacts/cvm/tables/*.tex`
- `artifacts/cvm/figures/*.pdf`

`frames.csv` currently contains the public-safe frame-level schema only:
run ID, frame index, simulator and observation timestamps, observation age,
camera count, route source and waypoint count, source/target trajectory sample
counts, trajectory validity, inference/action latency, late-message count,
lifecycle warning code, and policy reasoning/status code. Raw frame-level
restricted sensor data are not bundled, and unavailable frame rows are not
fabricated.

## Interpretation

The current aggregate supports a bounded integration-effectiveness claim for
the completed dependency-light public core, route-boundary preservation, a
functional command-only route baseline comparison, and evidence-gate rejection.
It does not support a complete direct-actor temporal ablation, learned-policy
result, policy-quality comparison, timing-effort comparison, or official Waymo
benchmark claim.
