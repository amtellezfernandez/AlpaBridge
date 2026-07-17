# Paper Changelog

## 2026-07-17

- Reframed the artifact vocabulary around the portable contract-validation
  matrix (CVM) instead of venue-specific row names.
- Added runtime-safe command-only route ablation support for `route_following`
  through the explicit `WOD2SIM_ROUTE_CONTRACT_MODE=command_only_route` driver
  environment override.
- Disabled AlpaSim video rendering for CVM closed-loop rows to keep evidence
  collection focused on metrics and audits.
- Executed 18/18 semantic ablation rows across three scenes, three replicate
  identifiers, and paired full/command-only route configurations.
- Executed 36/36 dependency-light core rows across six scenes, three replicate
  identifiers, and two public baselines.
- Added `semantic_ablation_pairs.csv`, semantic delta summaries, false-block
  counts, and CVM-prefixed paper macros generated from aggregate JSON/CSV.
- Rebuilt the root `wod2sim.pdf` as the only tracked manuscript PDF.
- Preserved the claim boundary: the paper now supports dependency-light core
  execution and bounded semantic integration-effectiveness evidence, but not
  direct-actor temporal ablation, learned-policy result, or policy-quality
  comparison.
