# Claim Evidence Matrix

This matrix gates paper claims. A claim is paper-supported only when the current
status names concrete generated artifacts and the paper keeps the same boundary.

| Claim | Contract layer | Required evidence | Producing command | Artifact | Current status |
|---|---|---|---|---|---|
| WOD2Sim separates integration/precondition/evidence failures from policy-behavior attribution. | Evidence/All contracts | Failure-attribution summary plus route/sensor audit status for completed rows. | `python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results`. | `artifacts/cvm/results/summary.json`; `artifacts/cvm/results/closed_loop_metrics.csv`. | Supported for current CVM: 45 contract-valid closed-loop rows, 9 integration/evidence-invalid closed-loop rows, 36 precondition-blocked rows, 55 synthetic diagnostic rows, and 0 claim-valid policy benchmark rows. |
| WOD2Sim preserves route geometry to policy-facing prediction input. | Semantic | Route-source audit showing route waypoints reach `PredictionInput`. | `python -m pytest -q tests -k "semantic or route"` and CVM execution. | `tests/test_alpasim_integration.py`; `artifacts/cvm/results/closed_loop_metrics.csv`. | Supported for full-contract rows: 45/45 completed full-contract rollouts are audit-valid. |
| Command-proxy route fallback is not claim-valid evidence. | Semantic/Evidence | Completed command-only route rows rejected by audit. | `python scripts/run_cvm_matrix.py --config configs/cvm/semantic_ablation.yaml --output artifacts/cvm/results/semantic_ablation --resume --execute`. | `artifacts/cvm/results/semantic_ablation_pairs.csv`; `artifacts/cvm/results/summary.json`. | Supported: 9/9 command-only rows completed, logged `command_proxy`, and were rejected as non-claim-valid. |
| Semantic route loss changes measured closed-loop behavior. | Semantic/Evidence | Matched full-contract vs command-only metrics. | Same semantic CVM command. | `artifacts/cvm/results/semantic_ablation_pairs.csv`. | Supported as bounded integration evidence: 9/9 metric-bearing pairs; mean full-minus-command deltas are progress -0.243, relative progress 0.007, collision-any 0.333, off-road 0.000, plan deviation 0.353. |
| Valid full-contract rows are not falsely blocked by the evidence gate. | Evidence | Audit-valid full-contract rows and false-block denominator. | `python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results`. | `artifacts/cvm/results/summary.json`; `artifacts/cvm/tables/main_results.tex`. | Supported for current CVM: 0/45 valid full-contract rows false-blocked. |
| Core dependency-light baselines execute across six scenes and three replicate IDs. | Evidence/Deployment | 36 completed `constant_velocity`/`route_following` rows plus audit aggregation. | `python scripts/run_cvm_matrix.py --config configs/cvm/core.yaml --output artifacts/cvm/results/core --resume --execute`. | `artifacts/cvm/results/core/runs.csv`; `artifacts/cvm/results/closed_loop_metrics.csv`. | Supported as dependency-light integration evidence; not a policy-quality benchmark. |
| Trajectory outputs are resampled to runtime cadence. | Temporal | Unit tests covering identity, interpolation, anchor, headings, invalid grids, explicit source timestamps, curved interpolation, and 10/20 Hz grids. | `python -m pytest -q tests -k "temporal or resampl"`. | `tests/test_alpasim_integration.py`. | Supported as unit-level temporal contract. No closed-loop temporal-ablation metric is claimed. |
| Late/duplicate lifecycle messages do not crash service. | Lifecycle | Tests and synthetic lifecycle rows. | `make cvm-synthetic PYTHON=./.venv/bin/python`. | `artifacts/cvm/results/lifecycle_stress/lifecycle_stress.csv`. | Supported as dependency-light synthetic diagnostics only: 20/20 hardened cycles survived; 0/20 strict/pre-hardening cycles survived. |
| External model entry points are discoverable without optional built-in backends. | Deployment/Plugin | Clean-subprocess import and entry-point discovery tests. | `python -m pytest -q tests -k "plugin or entry_point"`. | `tests/test_plugin_dependency_boundary.py`. | Supported for dependency-light public models and entry-point metadata. Learned checkpoint execution is not claimed. |
| Launch commands and readiness state are materialized. | Deployment | Deterministic launch plans and manifests. | `make cvm-eval PYTHON=./.venv/bin/python` or matrix runner without `--execute`. | `artifacts/cvm/manifests/run_manifests/*.json`. | Supported for planned, executed, and blocked CVM rows. |
| Temporal ablation evaluates full resampling versus naive/disabled resampling. | Temporal/Evidence | 18 paired rows with invalid-output and latency metrics. | `python scripts/run_cvm_matrix.py --config configs/cvm/temporal_ablation.yaml --output artifacts/cvm/results/temporal_ablation --resume --execute`. | `artifacts/cvm/results/temporal_ablation/runs.csv`. | Not supported: 18 rows blocked by missing direct-actor oracle proxy. |
| Fault localization detects and localizes configured injected faults. | Evidence/Diagnostics | `fault_injection.csv` with observed layer/code. | `make cvm-synthetic PYTHON=./.venv/bin/python`. | `artifacts/cvm/results/fault_injection/fault_injection.csv`. | Supported as synthetic diagnostics only: 15/15 detected and localized. |

## Aggregate Status

- Configured rows: 145.
- Attempted rows: 109.
- Completed rows: 109.
- Closed-loop completed rows: 54.
- Full-contract rows audit-valid: 45/45.
- Valid full-contract false-blocked rows: 0/45.
- Matched semantic metric pairs: 9/9.
- Command-only rows rejected as non-claim-valid: 9/9.
- Contract-valid closed-loop rows: 45.
- Integration/evidence-invalid closed-loop rows: 9.
- Claim-valid policy benchmark rows: 0.
- Planned rows: 0.
- Blocked rows: 36.
- Aggregate artifact: `artifacts/cvm/results/summary.json`.
