# SII 2027 Experiment Report

Current status: public synthetic lifecycle/fault matrices executed; closed-loop scene
matrices remain blocked before launch.

## Configured Matrices

| Matrix | Expected rows | Attempted | Completed | Blocked | Claim-valid |
|---|---:|---:|---:|---:|---:|
| Core closed loop | 54 | 0 | 0 | 54 | 0 |
| Semantic ablation | 18 | 0 | 0 | 18 | 0 |
| Temporal ablation | 18 | 0 | 0 | 18 | 0 |
| Lifecycle stress | 40 | 40 | 40 | 0 | 0 |
| Fault injection | 15 | 15 | 15 | 0 | 0 |
| Total | 145 | 55 | 55 | 90 | 0 |

## Current Blocked Reasons

- `execution_not_requested`: full-contract-capable rows were expanded and recorded
  with exact readiness/launch plans, but not launched because `--execute` was not
  requested.
- `direct_actor_oracle_proxy_missing`: `direct_actor_planner` rows require a recorded oracle actor-proxy JSON.
- `semantic_ablation_runtime_flag_missing`: command-only semantic ablation rows
  are configured, but no runtime-safe adapter flag currently switches the launcher
  into that ablated behavior.

Current blocked counts: 45 `execution_not_requested` rows, 36
`direct_actor_oracle_proxy_missing` rows, and 9
`semantic_ablation_runtime_flag_missing` rows.

The configured local 26.02 USDZ cache passed readiness for a selected SII scene
with Docker, GPU runtime, image, local AlpaSim environment, and scene-artifact
checks. The release blocker is therefore execution/oracle/ablation support, not
the selected local-cache preflight.

## Synthetic Diagnostics

- Lifecycle stress: 20/20 full-hardening synthetic cycles survived; 0/20
  strict/pre-hardening synthetic cycles survived duplicate-close/late-message injection.
- Fault injection: 15/15 configured public synthetic faults were detected and localized
  to the expected contract layer/code.
- These diagnostics are not closed-loop scene rollouts and remain `claim_valid=false`.

## Generated Artifacts

- `artifacts/sii2027/results/runs.csv`
- `artifacts/sii2027/results/failures.csv`
- `artifacts/sii2027/results/frames.csv`
- `artifacts/sii2027/results/summary.json`
- `artifacts/sii2027/results/summary.csv`
- `artifacts/sii2027/results/fault_injection.csv`
- `artifacts/sii2027/manifests/run_manifests/*.json` with per-row readiness and
  launch plans
- `artifacts/sii2027/tables/contract_map.tex`
- `artifacts/sii2027/tables/main_results.tex`
- `artifacts/sii2027/tables/ablations.tex`
- `artifacts/sii2027/tables/fault_localization.tex`
- `artifacts/sii2027/figures/system_architecture.pdf`
- `artifacts/sii2027/figures/evaluation_pipeline.pdf`
- `artifacts/sii2027/figures/main_results.pdf`

## Interpretation

No closed-loop SII 2027 result is currently claim-valid. The generated tables and figures may
describe configured/blocked closed-loop rows and public synthetic diagnostics only. They must not
be used as evidence of policy performance, real-scene ablation effects, or simulator-backed
lifecycle/fault reliability.
