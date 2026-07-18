# Claim Evidence Matrix

This matrix gates paper claims. A claim is paper-supported only when the current
status names concrete generated artifacts and the paper keeps the same boundary.
The contract-validation matrix (CVM) is the configured evidence matrix
summarized throughout this report.

| Claim | Contract layer | Required evidence | Producing command | Test | Artifact | Current status | Paper location |
|---|---|---|---|---|---|---|---|
| WOD2Sim separates integration/precondition/evidence failures from policy-behavior and policy-failure attribution. | Evidence/All contracts | Failure-attribution summary plus route/sensor audit status for completed rows. | `uv run python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results`. | `tests/test_aggregate_cvm.py`; `tests/test_validate_cvm_submission.py`. | `artifacts/cvm/results/summary.json`; `artifacts/cvm/results/closed_loop_metrics.csv`. | Supported for current CVM: 26 policy-behavior diagnostic rows, 0 policy-failure rows, 95 non-policy-attributed rows, 24 integration/precondition blockers, and 71 completed non-policy diagnostics. | Abstract, Introduction, Results, Conclusion. |
| WOD2Sim preserves route geometry to policy-facing prediction input. | Semantic | Route-source audit showing route waypoints reach `PredictionInput`. | `uv run python -m pytest -q tests -k "semantic or route"` and CVM execution. | `tests/test_alpasim_integration.py`. | `tests/test_alpasim_integration.py`; `artifacts/cvm/results/closed_loop_metrics.csv`. | Supported for audit-valid full-contract rows: 26/27 completed full-contract rollouts are audit-valid; the non-audit-valid row remains outside policy attribution. | Semantic Contract, Results. |
| Command-proxy route fallback is not claim-valid evidence. | Semantic/Evidence | Completed command-only route rows rejected by audit. | `uv run python scripts/run_cvm_matrix.py --config configs/cvm/semantic_ablation.yaml --output artifacts/cvm/results/semantic_ablation --resume --execute`. | `tests/test_alpasim_integration.py`; `tests/test_run_cvm_matrix.py`. | `artifacts/cvm/results/semantic_ablation_pairs.csv`; `artifacts/cvm/results/summary.json`. | Supported: 15/15 command-only rows completed, logged `command_proxy`, and were rejected as non-claim-valid. | Semantic Contract, Results. |
| Contracts improve semantic integration effectiveness relative to a runnable command-only route wrapper. | Semantic/Evidence | Functional command-only wrapper rows with metrics plus contract-gated rejection counts. | Same semantic CVM command and `uv run python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results`. | `tests/test_aggregate_cvm.py`; `tests/test_validate_cvm_submission.py`. | `artifacts/cvm/results/summary.json`; `artifacts/cvm/tables/ablations.tex`. | Supported for the route boundary: 15/15 command-only rows produce metrics that a naive wrapper could accept, while WOD2Sim rejects 15/15 as invalid route evidence and improves attribution on 15 rows. Not a full non-contract timing or policy-quality comparison. | Abstract, Results, Limitations. |
| Semantic route loss changes measured closed-loop behavior. | Semantic/Evidence | Matched full-contract vs command-only metrics. | Same semantic CVM command and `uv run python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results`. | `tests/test_aggregate_cvm.py`. | `artifacts/cvm/results/semantic_ablation_pairs.csv`. | Supported as bounded integration evidence: 15/15 metric-bearing pairs; mean full-minus-command deltas are progress -0.049, relative progress -0.021, collision-any 0.067, off-road 0.000, plan deviation 0.016. | Results. |
| Valid full-contract rows are not falsely blocked by the evidence gate. | Evidence | Audit-valid full-contract rows and false-block denominator. | `uv run python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results`. | `tests/test_aggregate_cvm.py`. | `artifacts/cvm/results/summary.json`; `artifacts/cvm/tables/main_results.tex`. | Supported for current CVM: 0/26 valid full-contract rows false-blocked. | Results. |
| Public core dependency-light baselines execute across six scenes with one retained execution per policy/scene pair. | Evidence/Deployment | 12 completed `constant_velocity`/`route_following` rows plus audit aggregation. | `uv run python scripts/run_cvm_matrix.py --config configs/cvm/core.yaml --output artifacts/cvm/results/core --resume --execute` and `uv run python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results`. | `tests/test_run_cvm_matrix.py`; `tests/test_aggregate_cvm.py`. | `artifacts/cvm/results/core/runs.csv`; `artifacts/cvm/results/closed_loop_metrics.csv`; `artifacts/cvm/results/summary.json`. | Supported as complete dependency-light public core: 12/12 completed, 12/12 audit-valid, 0 blocked. Not a policy-quality benchmark. | Evaluation Method, Results. |
| Run manifests record scene IDs and scenario categories without claiming unsupported category coverage. | Deployment/Evidence | Per-run `scene` block, top-level `scenario_category`, and generated scenario-coverage summary. | `uv run python scripts/run_cvm_matrix.py --config configs/cvm/core.yaml --output artifacts/cvm/results/core --resume --refresh-manifests` and aggregate. | `tests/test_run_cvm_matrix.py`; `tests/test_validate_cvm_submission.py`. | `artifacts/cvm/manifests/scene_manifest.yaml`; `artifacts/cvm/manifests/run_manifests/*.json`; `artifacts/cvm/results/summary.json`. | Supported: all public manifests carry scene metadata; 15 local closed-loop scenes remain unclassified and 0/6 required scenario categories are verified, so scenario-category coverage is not claimed. | Evaluation Method, Results, Appendix. |
| Trajectory outputs are resampled to runtime cadence. | Temporal | Unit tests covering identity, interpolation, anchor, headings, invalid grids, explicit source timestamps, curved interpolation, and 10/20 Hz grids. | `uv run python -m pytest -q tests -k "temporal or resampl"`. | `tests/test_alpasim_integration.py`. | `tests/test_alpasim_integration.py`. | Supported as unit-level temporal contract. No closed-loop temporal-ablation metric is claimed. | Temporal Contract, Limitations. |
| Late/duplicate lifecycle messages do not crash service. | Lifecycle | Tests and synthetic lifecycle rows. | `make cvm-synthetic PYTHON='uv run python'`. | `tests/test_lifecycle_contract.py`. | `artifacts/cvm/results/lifecycle_stress/lifecycle_stress.csv`. | Supported as dependency-light synthetic conformance diagnostics only: 20/20 hardened cycles survived; 0/20 strict/pre-hardening cycles survived. Not simulator-backed stress evidence. | Lifecycle Contract, Limitations. |
| External model entry points are discoverable without optional built-in backends. | Deployment/Plugin | Clean-subprocess import and entry-point discovery tests. | `uv run python -m pytest -q tests -k "plugin or entry_point"`. | `tests/test_plugin_dependency_boundary.py`. | `tests/test_plugin_dependency_boundary.py`. | Supported for public-core models and optional gated entry-point metadata. Learned checkpoint and direct-actor proxy execution are not claimed. | Architecture, Limitations. |
| Launch commands and readiness state are materialized. | Deployment | Deterministic launch plans and manifests. | `make cvm-eval PYTHON='uv run python'` or matrix runner without `--execute`. | `tests/test_run_cvm_matrix.py`; `tests/test_check_alpasim_readiness.py`. | `artifacts/cvm/manifests/run_manifests/*.json`. | Supported for planned, executed, and blocked CVM rows. | Evaluation Method, Appendix. |
| Public frame-level evidence has a stable schema without bundling restricted sensor data. | Evidence | `frames.csv` header covers timing, route-source, trajectory, latency, lifecycle-warning, and policy-status fields. | `uv run python scripts/aggregate_cvm.py --inputs artifacts/cvm/results --output artifacts/cvm/results`. | `tests/test_aggregate_cvm.py`; `tests/test_validate_cvm_submission.py`. | `artifacts/cvm/results/frames.csv`. | Supported as schema-only public evidence; no unavailable frame rows are fabricated. | Appendix, Reproducibility notes. |
| Temporal ablation evaluates full resampling versus naive/disabled resampling. | Temporal/Evidence | 18 paired rows with invalid-output and latency metrics. | `uv run python scripts/run_cvm_matrix.py --config configs/cvm/temporal_ablation.yaml --output artifacts/cvm/results/temporal_ablation --resume --execute`. | `tests/test_run_cvm_matrix.py`; `tests/test_aggregate_cvm.py`. | `artifacts/cvm/results/temporal_ablation/runs.csv`. | Not supported: 18 rows blocked by missing scene-matched direct-actor oracle proxy. | Results, Limitations. |
| Fault localization detects and localizes configured injected faults. | Evidence/Diagnostics | `fault_injection.csv` with observed layer/code. | `make cvm-synthetic PYTHON='uv run python'`. | `tests/test_run_cvm_matrix.py`; `uv run python -m pytest -q tests -k "fault"`. | `artifacts/cvm/results/fault_injection/fault_injection.csv`. | Supported as synthetic conformance diagnostics only: 15/15 detected and localized. Not external mutation-testing precision or simulator-backed stress evidence. | Limitations, Appendix. |

## Aggregate Status

- Configured rows: 121.
- Public-core rows completed: 12/12.
- Attempted rows: 97.
- Completed rows: 97.
- Closed-loop completed rows: 42.
- Full-contract rows audit-valid: 26/27.
- Valid full-contract false-blocked rows: 0/26.
- Matched semantic metric pairs: 15/15.
- Command-only rows rejected as non-claim-valid: 15/15.
- Functional naive-wrapper invalid rows accepted: 15/15.
- Contract-invalid route evidence rejected: 15/15.
- Closed-loop unique scenes: 15.
- Verified required scenario categories: 0/6.
- Unclassified closed-loop scenes: 15.
- Contract-valid closed-loop rows: 26.
- Integration/evidence-invalid closed-loop rows: 16.
- Policy-attributable behavior rows: 26.
- Policy-attributable failure rows: 0.
- Non-policy-attributed rows: 95.
- Claim-valid policy benchmark rows: 0.
- Planned rows: 0.
- Blocked rows: 24.
- Aggregate artifact: `artifacts/cvm/results/summary.json`.

Note: one completed full-contract semantic row is intentionally not counted as
policy-attributable because the audit found 12/199 frames with `command_proxy`
route fallback. This is an integration-boundary finding, not a policy failure.
