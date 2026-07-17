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

- `execution_not_requested`: rows were expanded and recorded without `--execute`.
- `direct_actor_oracle_proxy_missing`: `direct_actor_planner` rows require a recorded oracle actor-proxy JSON.

Current blocked counts: 54 `execution_not_requested` rows and 36
`direct_actor_oracle_proxy_missing` rows.

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
