# Release Blockers

## Resolved In This Pass

- The root paper PDF is the only tracked manuscript PDF: `wod2sim.pdf`.
- Public artifact vocabulary and paths use the contract-validation matrix
  (CVM).
- The command-only route ablation is runtime-safe and explicit:
  `WOD2SIM_ROUTE_CONTRACT_MODE=command_only_route`.
- AlpaSim video rendering is disabled for CVM rows with
  `eval.video.render_video=false`.
- Core dependency-light rows completed: 36/36 across `constant_velocity` and
  `route_following`.
- Semantic ablation completed 18/18 closed-loop rows with 9 matched
  full/command-only pairs.
- Run manifests now record scene metadata and `scenario_category`; local
  closed-loop scenes remain explicitly unclassified.

## Remaining Blockers

- `direct_actor_planner` and temporal ablation rows remain blocked by
  `direct_actor_oracle_proxy_missing`.
- Scene categories remain unverified. Six local 26.02 front-camera scenes are
  selected by availability and recorded as unclassified, not authoritative
  straight/turn/lane-change/traffic category labels.
- Learned `token_dagger_bc` is excluded because no legitimate local checkpoint
  hash is established for release.
- Local validation uses `mutool` plus source/log checks and now enforces that
  every discovered paper font has an embedded font file. CI additionally
  installs Poppler and `qpdf` to run `pdfinfo`, `pdffonts`, and `qpdf --check`.

## Current Aggregate

- Configured rows: 145.
- Attempted rows: 109.
- Completed rows: 109.
- Closed-loop completed rows: 54.
- Full-contract audit-valid rows: 45/45.
- False-blocked valid full-contract rows: 0/45.
- Command-only rows rejected as non-claim-valid: 9/9.
- Planned rows: 0.
- Blocked rows: 36, all `direct_actor_oracle_proxy_missing`.

## Claim Boundary

The paper may claim the completed dependency-light core execution, semantic
route-boundary confound measurement, evidence-gate rejection of command-only
route rows, false-block denominator on valid full-contract rows, and public
synthetic diagnostics. It must not claim a complete direct-actor temporal
ablation, learned-policy performance, policy-quality superiority, or official
Waymo benchmark compatibility.
