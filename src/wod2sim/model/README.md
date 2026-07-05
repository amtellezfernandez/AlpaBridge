# Model / WOD-E2E Surface

This subtree is the Waymo candidate-generation and selector surface of the repo.

Use it for:

- Waymo `E2EDFrame` parsing
- candidate generation
- learned trajectory models
- selector training
- submission writing

## Start Here

- `wod_e2e.py` — Waymo frame parsing and schema handling
- `kinematic_candidates.py` — physics-based candidate families
- `learned_trajectory_model.py` — ridge learned candidates
- `wod_ranker.py` — candidate selector / ranker
- `wod_submission.py` — official submission formatting

## File Map

- `trajectory_io.py` / `trajectory_resampling.py` — candidate trajectory utilities
- `rfs_metric.py` — RFS-side metric helpers
- `wod_preference.py` — preference-label handling
- `anchor_trajectory_model.py` / `neural_trajectory_model.py` / `transformer_trajectory_model.py`
  — alternative learned candidate models
- `v20_planner.py` / `neural_planner.py` — direct-policy / planner variants
- `internvla_av_bridge.py` / `world_model.py` / `zero_shot_eval.py`
  — visual/world-prior bridge and evaluation helpers

## Boundary

This directory is first-party repo code. It is distinct from:

- `src/wod2sim/simulator/` — closed-loop simulator surface
- `third_party/` — explicit external overrides or patches
- `workspace/waymo-open-dataset/` — separate nested upstream checkout

For the benchmark write-up, go to:

- [`docs/wod-e2e-system-walkthrough.md`](../../../docs/wod-e2e-system-walkthrough.md)
