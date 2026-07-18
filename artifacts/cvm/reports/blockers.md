# Release Blockers

## Resolved In This Pass

- The root paper PDF is the only tracked manuscript PDF: `wod2sim.pdf`.
- Public artifact vocabulary and paths use the contract-validation matrix
  (CVM).
- The command-only route ablation is runtime-safe and explicit:
  `WOD2SIM_ROUTE_CONTRACT_MODE=command_only_route`.
- AlpaSim video rendering is disabled for CVM rows with
  `eval.video.render_video=false`.
- Core dependency-light rows completed: 12/12 across `constant_velocity` and
  `route_following`.
- Semantic ablation completed 6/6 closed-loop rows with 3 matched
  full/command-only pairs.
- Run manifests now record scene metadata and `scenario_category`; local
  closed-loop scenes remain explicitly unclassified.

## Remaining Blockers

- Optional gated `direct_actor_planner` and temporal ablation rows remain blocked by
  `direct_actor_oracle_proxy_missing`; the proxy must be scene-matched, and
  adapters reject oracle frames whose `scene_id` does not match the current
  prediction scene.
- Scene categories remain unverified. Six local 26.02 front-camera scenes are
  selected by availability and recorded as unclassified, not authoritative
  straight/turn/lane-change/traffic category labels.
- Learned `token_dagger_bc` is excluded because no legitimate local checkpoint
  hash is established for release.
- Local validation uses `mutool` plus source/log checks and now enforces that
  every discovered paper font has an embedded font file. CI additionally
  installs Poppler and `qpdf` to run `pdfinfo`, `pdffonts`, and `qpdf --check`.

## Current Aggregate

- Configured rows: 97.
- Attempted rows: 73.
- Completed rows: 73.
- Closed-loop completed rows: 18.
- Full-contract audit-valid rows: 15/15.
- False-blocked valid full-contract rows: 0/15.
- Command-only rows rejected as non-claim-valid: 3/3.
- Planned rows: 0.
- Blocked rows: 24, all `direct_actor_oracle_proxy_missing`.

The release treats the completed public-core and semantic-ablation bullets as
the integration-effectiveness evidence. The blocked rows are optional gated
extension work retained for denominator honesty and failure analysis only.

## Claim Boundary

The paper may claim the completed dependency-light public core, semantic
route-boundary confound measurement, evidence-gate rejection of command-only
route rows, and false-block denominator on valid full-contract rows. Public
synthetic lifecycle/fault rows may be reported only as service-level
conformance diagnostics. Missing scene-matched actor proxies, learned
checkpoints, and redistributable restricted scenes block optional extension or
benchmark claims, not the public core. It must not claim a complete
direct-actor temporal ablation, learned-policy performance, simulator-backed
lifecycle/fault stress reliability, policy-quality superiority, or official
Waymo benchmark compatibility.
