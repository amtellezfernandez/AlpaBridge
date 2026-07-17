# SII 2027 Repository Inventory

Captured: 2026-07-17T13:19Z UTC

## Repository State

- Repository root: `<repo>` (`/home/...` prefix redacted in generated artifacts)
- Git SHA at inventory refresh: `5ee9a2e87e724215cc38d560e3520478d0c90575`
- Initial source state before this cleanup pass: clean `main...origin/main`
- Current dirty state at inventory refresh: generated inventory/environment
  snapshots only; the publish state is the Git commit containing those artifacts
- Git submodules: none reported by `git submodule status --recursive`
- Raw command logs: `artifacts/sii2027/environment/git_state.txt` and `artifacts/sii2027/logs/baseline/search_*.log`

## Manuscript And PDF

- Historical manuscript source retained in Git: `paper/paper.tex`,
  `paper/paper.bib`, and `paper/wod_alpasim_2026.sty`
- Canonical release paper source: `paper/sii2027/main.tex`
- Canonical tracked release PDF: `wod2sim.pdf`
- Local build byproducts under `paper/sii2027/` are ignored so the repository has
  one tracked paper PDF.
- PDF metadata fallback: `mutool info` reports an A4 PDF 1.5 build below 6 MB.
- Missing local validators: `pdfinfo`, `pdffonts`, `qpdf`, and `latexmk` are unavailable; `pdflatex`, `bibtex`, and `mutool` are available.

## Python And Packaging

- Package config: `pyproject.toml`
- Lockfile: `uv.lock`
- Active test interpreter used for release checks: `./.venv/bin/python`
- Default `python` command: unavailable in this shell; scripts should use `$(PYTHON)` or `./.venv/bin/python`.
- Project dependencies: `numpy`, `PyYAML`
- Optional extras: `dev`, `alpasim`, `viz`
- Build backend: `setuptools.build_meta`

## Make Targets

Defined in the current top-level `Makefile`:

- `paper`
- `paper-verify`
- `test`
- `lint`
- `conformance`
- `coverage`
- `smoke`
- `demo`
- `build`
- `verify`
- `clean`

SII release targets:

- `sii2027-inventory`
- `sii2027-check`
- `sii2027-demo`
- `sii2027-eval`
- `sii2027-synthetic`
- `sii2027-aggregate`
- `sii2027-paper`
- `sii2027-validate`
- `sii2027-all`

## Tests

Test root: `tests/`

Current test modules:

- `tests/test_alpasim_integration.py`
- `tests/test_alpasim_setup_scripts.py`
- `tests/test_audit_run_command.py`
- `tests/test_batch_summary.py`
- `tests/test_benchmark_readiness.py`
- `tests/test_benchmark_summary.py`
- `tests/test_bootstrap_alpasim_env_script.py`
- `tests/test_build_alpasim_local_usdz_cache.py`
- `tests/test_check_alpasim_readiness.py`
- `tests/test_import_alpasim_scene_cache_script.py`
- `tests/test_maneuver_candidates.py`
- `tests/test_promote_batch_summary.py`
- `tests/test_release_bootstrap_smoke.py`
- `tests/test_reproduce_closed_loop.py`
- `tests/test_run_alpasim_scene_batch.py`
- `tests/test_run_sii2027_matrix.py`
- `tests/test_support_bundle_command.py`
- `tests/test_synthetic_contract_demo.py`
- `tests/test_wod2sim_doctor.py`

Baseline skip reason: 14 learned-policy tests skip because `torch` is not installed or the Torch environment is unavailable.

## Launch, Audit, And Experiment Scripts

Current scripts relevant to SII 2027:

- `scripts/run_alpasim_local_external.py`
- `scripts/run_alpasim_scene_batch.py`
- `scripts/check_alpasim_readiness.py`
- `scripts/setup_alpasim_local_plugin.py`
- `scripts/build_alpasim_local_usdz_cache.py`
- `scripts/build_alpasim_oracle_actor_proxy.py`
- `scripts/audit_run.py`
- `scripts/batch_summary.py`
- `scripts/benchmark_readiness.py`
- `scripts/benchmark_summary.py`
- `scripts/promote_batch_summary.py`
- `scripts/reproduce_closed_loop.py`
- `scripts/run_synthetic_contract_demo.py`
- `scripts/support_bundle.py`
- `scripts/wod2sim_doctor.py`
- `scripts/release_bootstrap_smoke.py`

SII release scripts:

- `scripts/sii2027_inventory.sh`
- `scripts/run_sii2027_matrix.py`
- `scripts/aggregate_sii2027.py`
- `scripts/generate_sii2027_figures.py`
- `scripts/build_sii2027_paper.sh`
- `scripts/validate_sii2027_submission.py`

## Public Model And Plugin Entry Points

From `pyproject.toml`, `alpasim.models` exposes:

- `constant_velocity = wod2sim.simulator.baseline_drivers:ConstantVelocityAlpaSimModel`
- `route_following = wod2sim.simulator.baseline_drivers:RouteFollowingAlpaSimModel`
- `token_dagger_bc = wod2sim.simulator.alpasim_token_bc:TokenBCAlpaSimModel`
- `direct_actor_planner = wod2sim.simulator.alpasim_direct_actor_planner:DirectActorPlannerAlpaSimModel`

From `pyproject.toml`, `alpasim.configs` exposes:

- `wod2sim = wod2sim.simulator.alpasim_configs`

## Scene Presets And Driver Configs

Scene preset files:

- `src/wod2sim/simulator/alpasim_scene_presets/fresh_3scene.yaml`
- `src/wod2sim/simulator/alpasim_scene_presets/front_camera_10scene_smoke.yaml`
- `src/wod2sim/simulator/alpasim_scene_presets/front_camera_30scene_merged.yaml`
- `src/wod2sim/simulator/alpasim_scene_presets/front_camera_50scene_public2602.yaml`
- `src/wod2sim/simulator/alpasim_scene_presets/front_camera_100scene_public2602.yaml`
- `src/wod2sim/simulator/alpasim_scene_presets/front_camera_collision18.yaml`

Driver config files:

- `src/wod2sim/simulator/alpasim_configs/driver/constant_velocity.yaml`
- `src/wod2sim/simulator/alpasim_configs/driver/route_following.yaml`
- `src/wod2sim/simulator/alpasim_configs/driver/token_dagger_bc.yaml`
- `src/wod2sim/simulator/alpasim_configs/driver/direct_actor_planner.yaml`

## Simulator Patch Files

Repository-tracked override/patch locations:

- `third_party/alpasim_overrides/route_waypoints.patch`
- `third_party/alpasim_overrides/local_checkout.patch`
- `third_party/alpasim_overrides/Dockerfile.amd64`
- `third_party/alpasim_overrides/src/driver/src/alpasim_driver/models/__init__.py`
- `third_party/alpasim_overrides/src/wizard/alpasim_wizard/deployment/docker_compose.py`
- `third_party/alpasim_overrides/src/wizard/configs/deploy/local_arm_external_driver.yaml`
- Mirrored package overrides under `src/wod2sim/alpasim_overrides/`

## Existing Result Evidence

Ignored run evidence currently exists under `runs/`:

- `runs/alpasim_constant_velocity_one_scene_exec*/run-status.json`
- `runs/alpasim_constant_velocity_one_scene_smoke/run-status.json`
- `runs/bench_constant_velocity_15_public2602/constant_velocity-batch-summary.json`
- `runs/bench_constant_velocity_14_public2602_claim_clean/constant_velocity-batch-summary.json`

Important claim boundary from current evidence:

- The 15-scene constant-velocity run is diagnostic only because one scene has route-contract failures.
- The 14-scene subset is clean adapter evidence, but it is not a full benchmark claim because the default benchmark gate requires broader scene/baseline coverage.
- The synthetic demo is public and auditable, but explicitly not closed-loop benchmark evidence.

## Simulator And Gated Prerequisites

- Docker is available.
- NVIDIA runtime is available; GPU reported by `nvidia-smi`.
- Docker images present:
  - `alpasim-base:0.66.0`, image ID `7ba4dbee3391`, no repo digest
  - `nvcr.io/nvidia/nre/nre-ga:26.02`, digest `sha256:dbb6be50cabc878fa15bbc9cf3bf4fb4b0904cb67bea7a83a32aa9d96bac8b8d`
- Missing mutable image tag: `alpasim-base:latest`
- AlpaSim worktree SHA: `049f70fbfe8207e1efd4831a6c3e78a38703d473`
- AlpaSim worktrees are dirty with local WOD2Sim/AlpaSim override changes.
- Local USDZ caches exist for one front-camera scene and a 15-scene front-camera set under `workspace/alpasim-clean/data/nre-artifacts/`.
- Gated assets are local only; no restricted scene assets should be copied into public artifacts.
- Learned checkpoint availability is not established; Torch is not installed in the baseline environment.

## Required Search Logs

The required repository searches were executed and saved under:

- `artifacts/sii2027/logs/baseline/search_1.log`
- `artifacts/sii2027/logs/baseline/search_2.log`
- `artifacts/sii2027/logs/baseline/search_3.log`
- `artifacts/sii2027/logs/baseline/search_4.log`
- `artifacts/sii2027/logs/baseline/search_5.log`
- `artifacts/sii2027/logs/baseline/search_6.log`
- `artifacts/sii2027/logs/baseline/search_7.log`
- `artifacts/sii2027/logs/baseline/search_8.log`

Search scope excluded generated SII artifacts, ignored run/workspace directories, `.git`, `.venv`, and `.uv-cache` to avoid self-matches and private/gated data.
