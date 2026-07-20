# Release Blockers

## Resolved In This Pass

- The root paper PDF is the only tracked manuscript PDF: `wod2sim.pdf`.
- Public artifact vocabulary and paths use the contract-validation matrix
  (CVM).
- The command-only route ablation is runtime-safe and explicit:
  `WOD2SIM_ROUTE_CONTRACT_MODE=command_only_route`.
- AlpaSim video rendering is disabled for CVM rows with
  `eval.video.render_video=false`.
- Core dependency-light rows completed: 30/30 across `constant_velocity` and
  `route_following`.
- Semantic ablation completed 30/30 closed-loop rows with 15 matched
  full/command-only pairs.
- Run manifests now record scene metadata and `scenario_category`; local
  closed-loop scenes remain explicitly unclassified.
- The controlled fault harness now generates 15 separate current-adapter
  sessions and detects mutations without passing expected labels, with 15 valid
  controls and an executable status-only comparator.
- Timing evidence now records post-parse detector execution, the guarded
  in-process adapter Drive path, and a paired camera-set plus freshness-guard
  increment, with context-length validation retained in both arms and explicit
  exclusions for gRPC, simulator work,
  file I/O, and human investigation.
- Missing finite-output evidence is no longer treated as valid, and final
  protocol serialization rejects non-finite or structurally invalid output.
- A camera-alias freshness defect exposed by the new valid-session generator is
  fixed and regression-tested.
- A published NAVSIM EgoStatusMLP checkpoint now completes one live AlpaSim
  external-driver/controller/physics rollout: 197/197 finite outputs over
  19.93 simulated seconds. The public fixture's repeated camera seed and added
  declared flat surface remain explicit limitations; a camera-validating
  control rejects the frozen stream after four completed calls.

## Remaining Blockers

- Optional gated `direct_actor_planner` and temporal ablation rows remain blocked by
  `direct_actor_oracle_proxy_missing`; the proxy must be scene-matched, and
  adapters reject oracle frames whose `scene_id` does not match the current
  prediction scene.
- Scene categories remain unverified. Fifteen local 26.02 front-camera scenes are
  selected by availability and recorded as unclassified, not authoritative
  straight/turn/lane-change/traffic category labels.
- Learned `token_dagger_bc` is excluded because no legitimate local checkpoint
  hash is established for release.
- Local validation uses `mutool` plus source/log checks and now enforces that
  every discovered paper font has an embedded font file. CI additionally
  installs Poppler and `qpdf` to run `pdfinfo`, `pdffonts`, and `qpdf --check`.

## Current Aggregate

- Configured rows: 148.
- Attempted rows: 115.
- Completed rows: 115.
- Closed-loop completed rows: 60.
- Full-contract audit-valid rows: 42/45.
- Comparison-eligible semantic pairs: 14/15.
- Status-only baseline accepted rows: 15/15.
- Command-only rows rejected as non-claim-valid: 15/15.
- Controlled diagnostic classifications: WOD2Sim 30/30; status-only 15/30.
- Controlled fault localization and false positives: 15/15 and 0/15.
- Current protocol trace: 15 sessions, 120 drive calls, and 120/120 explicit
  finite serialized outputs.
- Fault-case detector execution: 28.096 us median and 55.774 us p95.
- Guarded in-process adapter Drive path: 617.549 us median and 897.100 us p95.
- Paired guard-path increment: 68.871 us median and 309.613 us p95 across 1,000
  pairs rotating over 15 valid sessions.
- Planned rows: 0.
- Blocked rows: 33, all `direct_actor_oracle_proxy_missing`.

The release treats the completed public-core and semantic-ablation bullets as
the integration-effectiveness evidence. The blocked rows are optional gated
extension work retained for denominator honesty and failure analysis only.
Three completed full-contract rows on scene
`clipgt-0fd06bc3-1899-4b45-9278-c5c018b3968d` are not audit-valid because
12/199 frames fell back to `command_proxy`; they are retained as integration
evidence and excluded from policy attribution rather than treated as policy
failures.

## Claim Boundary

The paper may claim the completed dependency-light public core, semantic
route-boundary diagnostic, evidence-gate rejection of command-only route rows,
controlled trace classification/localization against the executable
status-only gate, post-parse detector execution, and a paired guard-path
increment, plus the bounded learned reactive lifecycle run. Missing
scene-matched actor proxies, other learned
checkpoints, and redistributable restricted scenes block optional extension or
benchmark claims, not the public core. It must not claim a complete
direct-actor temporal ablation, learned-policy performance, simulator-backed
lifecycle stress reliability, broad integration-framework ranking,
policy-quality superiority, comparative runtime overhead, human
time-to-diagnosis, or official Waymo benchmark compatibility.
