# Paper Changelog

## 2026-07-20

- Added a pinned Waymax/WOMD `2 x 2` policy-by-route experiment over 20 bundled
  TFExamples: 19 paired scenarios, 3,800 closed-loop steps, 1.017 m median
  route-following endpoint divergence, and exact constant-velocity invariance.
- Made the semantic audit policy-signature-aware before rollout metrics:
  RF/proxy is rejected 19/19 while RF/full and both constant-velocity controls
  pass 19/19.
- Reframed the principal claim as causal attribution correctness and limited
  cross-runtime evidence to the route semantic contract.
- Added one hash-validated reactive AlpaSim run of the published camera-blind
  NAVSIM checkpoint: 197/197 finite outputs, 198 render requests, and 19.93
  simulated seconds through live driver/controller/physics feedback.
- Reported the repeated public camera seed, declared synthetic flat ground,
  retained `wrong_lane=1`, and frozen-camera negative control; explicitly
  withheld visual-policy, policy-quality, comparative-overhead,
  human-diagnosis, and cross-simulator claims.
- Added a four-arm, hash-validated replay of the official AlpaSim integration
  protocol through live gRPC services.
- Replaced the project-specific replay checkpoint with NAVSIM's official
  EgoStatusMLP seed-0 checkpoint, pinned by repository revision and SHA-256.
- Made route-contract diagnostics policy-aware: route removal is a fault for
  route following, while the command-native NAVSIM model is a 60/60 exact-match
  negative control.
- Fixed and regression-tested an output serializer off-by-one error; schema v3
  distinguishes the current pose from every predicted future waypoint.
- Reported 60/60 finite outputs per arm and bounded client-to-service latency;
  retained the non-reactive, no-overhead, and no-human-diagnosis limits.
- Added structural generalization beyond WOD message types while explicitly
  withholding cross-runtime generalization of the remaining contracts.
- Replaced illustrative README media with one real-camera comparison video and
  a same-frame animated preview generated from the executed replay.

## 2026-07-19

- Switched the manuscript to the official PaperPlaza `ieeeconf` A4 conference
  class and kept the paper within the conference's regular-paper page range.
- Removed the unmeasured false-block claim and replaced the informal naive
  wrapper comparison with a defined status-only acceptance baseline.
- Added comparison eligibility to semantic pairs; 14/15 pairs qualify after
  excluding the pair whose full-contract arm is route-invalid.
- Recomputed semantic deltas on eligible pairs and removed the unsupported
  claim that route loss systematically changes behavior.
- Replaced policy-score columns with route, sensor, audit, crash, and blocker
  integration status.

## 2026-07-17

- Reframed the artifact vocabulary around the portable contract-validation
  matrix (CVM).
- Added runtime-safe command-only route ablation support for `route_following`
  through the explicit `ALPABRIDGE_ROUTE_CONTRACT_MODE=command_only_route` driver
  environment override.
- Disabled AlpaSim video rendering for CVM closed-loop rows to keep evidence
  collection focused on metrics and audits.
- Executed 30/30 dependency-light public-core rows across fifteen scenes and
  two public baselines.
- Executed 30/30 semantic ablation rows across fifteen scenes with paired
  full/command-only route configurations; retained 15/15 metric-bearing
  full/command-only pairs.
- Added an external AlpaSim E2E-style compatibility conformance artifact: 1/1
  rollout completed, 197 driver RPCs, 396 image events, and 197/197
  latency-target hits.
- Added `semantic_ablation_pairs.csv`, semantic delta summaries, and
  CVM-prefixed paper macros generated from aggregate JSON/CSV.
- Rebuilt the root `alpabridge.pdf` as the only tracked manuscript PDF.
- Preserved the claim boundary: the paper now supports dependency-light core
  execution and bounded semantic integration-effectiveness evidence, but not
  direct-actor temporal ablation, learned-policy result, or policy-quality
  comparison.
- Split the public-core claim from optional gated extension prerequisites:
  direct actor-aware rows, learned checkpoints, and restricted scene
  redistribution are no longer presented as release-core dependencies.
