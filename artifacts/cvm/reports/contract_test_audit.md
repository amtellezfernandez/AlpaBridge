# Contract Test Audit

This report maps the public contract-validation matrix (CVM) contract-test
surface to executable tests and explicit gaps. It is a traceability report, not
a new result table. A row marked
`Covered` means the stated behavior is exercised by the listed public tests or
generated artifacts. A row marked `Partially covered` means unit or synthetic
coverage exists, but simulator-backed or gated-asset evidence is still missing.
A row marked `Gap` names work that remains unsupported by current public
artifacts.

## Semantic Contract

| Behavior | Evidence | Status |
|---|---|---|
| Route waypoints reach prediction input. | `tests/test_alpasim_integration.py`: `test_route_following_baseline_tracks_supplied_route_geometry`, `test_alpasim_signal_uses_route_waypoints_as_lane_center`; `artifacts/cvm/results/closed_loop_metrics.csv`. | Covered. |
| Command-proxy route fallback is marked non-claim-valid. | `tests/test_alpasim_integration.py`: `test_route_following_command_only_ablation_ignores_route_geometry`; `tests/test_audit_run_command.py`: `test_build_report_rejects_command_proxy_route_fallback`; `tests/test_run_cvm_matrix.py`: `test_command_only_manifest_records_proxy_route_expectation`. | Covered. |
| Ego lane reference is not treated as a raw road center. | `tests/test_alpasim_integration.py`: `test_alpasim_signal_uses_route_waypoints_as_lane_center`; `tests/test_synthetic_contract_demo.py`: `test_generate_demo_writes_audited_public_artifacts`. | Covered. |
| Structured hazard aliases, static geometry, dynamic actor motion, headings, and behavior fields are preserved where available. | `tests/test_alpasim_integration.py`: `test_alpasim_signal_uses_structured_hazards`, `test_alpasim_signal_preserves_static_hazard_shape_metadata`, `test_alpasim_signal_preserves_moving_hazards_as_actors`, `test_alpasim_signal_preserves_moving_hazard_shape_metadata`, `test_alpasim_signal_preserves_explicit_moving_behavior`, `test_alpasim_signal_preserves_explicit_heading_for_elongated_vehicle`. | Covered. |
| Visibility-risk diagnostics do not fabricate obstacles. | `tests/test_alpasim_integration.py`: `test_alpasim_signal_keeps_inferred_risk_diagnostic_only`. | Covered. |
| Missing route or command-only fallback carries an explicit reason code. | `tests/test_run_cvm_matrix.py`: `test_command_only_manifest_records_proxy_route_expectation`; `artifacts/cvm/results/semantic_ablation_pairs.csv`. | Covered for command-only route fallback; missing-route simulator evidence remains outside current public rows. |

## Temporal Contract

| Behavior | Evidence | Status |
|---|---|---|
| Matching grids preserve trajectories and runtime grids resample deterministically. | `tests/test_alpasim_integration.py`: `test_resample_trajectory_preserves_native_runtime_samples`, `test_resample_trajectory_uses_origin_anchored_endpoint_interpolation`, `test_interpolation_is_anchored_at_current_ego_origin`, `test_multiple_runtime_frequencies_are_supported`. | Covered at unit level. |
| Runtime headings are recomputed from runtime points. | `tests/test_alpasim_integration.py`: `test_headings_are_recomputed_on_runtime_grid`. | Covered at unit level. |
| Output shape, finite values, valid horizon, valid frequency, and monotonic source timestamps are enforced. | `tests/test_alpasim_integration.py`: `test_output_shape_matches_runtime_contract`, `test_nonfinite_trajectory_is_rejected`, `test_invalid_horizon_or_frequency_is_rejected`, `test_duplicate_or_nonmonotonic_timestamps_are_handled_explicitly`. | Covered at unit level. |
| Curved-path interpolation error is bounded against the piecewise-linear reference. | `tests/test_alpasim_integration.py`: `test_curved_path_error_matches_piecewise_linear_reference`. | Covered at unit level. |
| Full temporal ablation compares resampling against naive or disabled resampling on closed-loop scene rows. | `configs/cvm/temporal_ablation.yaml`; `artifacts/cvm/reports/blockers.md`; `artifacts/cvm/results/summary.json`. | Gap: current rows are blocked by missing scene-matched direct-actor proxy evidence. No temporal-ablation scene metric is claimed. |

## Lifecycle Contract

| Behavior | Evidence | Status |
|---|---|---|
| Duplicate close is idempotent and late image, egomotion, route, and close events do not crash the service. | `tests/test_lifecycle_contract.py`: `test_duplicate_close_is_idempotent`, `test_late_image_after_close_does_not_crash`, `test_late_egomotion_after_close_does_not_crash`, `test_late_route_after_close_does_not_crash`. | Covered in the dependency-light service harness. |
| Unknown-session events are structured and counted. | `tests/test_lifecycle_contract.py`: `test_unknown_session_event_is_structured_and_counted`. | Covered in the dependency-light service harness. |
| Session cleanup prevents state leak and interleaved sessions remain isolated. | `tests/test_lifecycle_contract.py`: `test_session_cleanup_prevents_state_leak`, `test_interleaved_sessions_remain_isolated`. | Covered in the dependency-light service harness. |
| Repeated start/stop cycles remain stable under hardened lifecycle handling. | `tests/test_lifecycle_contract.py`: `test_repeated_start_stop_cycles_are_stable`; `artifacts/cvm/results/lifecycle_stress/lifecycle_stress.csv`. | Covered as public synthetic diagnostics only. |
| Strict or pre-hardening behavior exposes the benign crash mode separately from policy behavior. | `tests/test_lifecycle_contract.py`: `test_strict_pre_hardening_behavior_stops_on_duplicate_close`; `artifacts/cvm/results/lifecycle_stress/lifecycle_stress.csv`. | Covered as synthetic diagnostic evidence; not a functional non-contract wrapper comparison. |

## Deployment And Plugin-Dependency Contract

| Behavior | Evidence | Status |
|---|---|---|
| Base model contracts import without optional AlpaMayo or VAM backends. | `tests/test_plugin_dependency_boundary.py`: `test_plugin_base_model_contract_imports_without_optional_backends`, `test_plugin_unselected_alpamayo_or_vam_is_not_imported`. | Covered. |
| Missing optional backends, missing checkpoints, invalid token schemas, and scene-mismatched actor proxies fail with actionable errors. | `tests/test_plugin_dependency_boundary.py`: `test_plugin_missing_optional_backend_has_actionable_error`; `tests/test_alpasim_integration.py`: `test_token_bc_alpasim_adapter_rejects_unknown_checkpoint_tokens`, `test_direct_actor_planner_rejects_oracle_actor_proxy_scene_mismatch`; `tests/test_alpasim_setup_scripts.py`: `test_direct_actor_planner_preset_requires_oracle_actor_proxy`. | Covered for public parser, adapter, and plugin paths. |
| Constant-velocity, route-following, and direct-actor planner entry points are deterministic and discoverable. | `tests/test_alpasim_integration.py`: `test_constant_velocity_baseline_is_dependency_light_and_auditable`, `test_route_following_baseline_tracks_supplied_route_geometry`, `test_direct_actor_planner_returns_trajectory_without_token_selector`; `tests/test_wod2sim_doctor.py`: `test_build_report_validates_public_release_surface`. | Covered. |
| Setup check-only mode has no mutating side effects. | `tests/test_alpasim_setup_scripts.py`: `test_setup_check_only_does_not_bootstrap_or_install`. | Covered. |
| Readiness reports missing preconditions, platform guards, Docker/image status, and scene-cache requirements. | `tests/test_alpasim_setup_scripts.py`: `test_preflight_rejects_missing_local_alpasim_environment`, `test_preflight_rejects_missing_gated_artifacts_without_hf_token`, `test_preflight_docker_access_rejects_socket_permission_denied`, `test_preflight_alpasim_base_image_rejects_missing_image`, `test_platform_preflight_rejects_arm_without_override`; `tests/test_check_alpasim_readiness.py`: `test_readiness_script_calls_all_preflights`. | Covered for public preflight logic. |
| Print mode materializes deterministic commands with matching topology, addresses, ports, scene IDs, and safe shell arguments. | `tests/test_alpasim_setup_scripts.py`: `test_print_mode_skips_live_runtime_and_scene_artifact_preflights`, `test_driver_command_uses_alpasim_venv_python`, `test_wizard_command_uses_alpasim_venv_binary`, `test_wizard_command_can_append_overrides`; `tests/test_run_cvm_matrix.py`: `test_run_manifest_contains_closed_loop_launch_plan`. | Covered for command materialization. |
| Manifest records runtime Git state, image/config/checkpoint hashes, and local simulator state after live execution. | `tests/test_run_cvm_matrix.py`: `test_run_manifest_contains_closed_loop_launch_plan`; `artifacts/cvm/manifests/run_manifests/*.json`. | Partially covered: manifests record public source/config state; Docker image digests and GPU runtime identity require the local live runtime and are recorded when available. |

## Evidence Contract

| Behavior | Evidence | Status |
|---|---|---|
| Proxy routes, incomplete rollouts, missing manifest fields, and hash mismatches reject claim validity. | `tests/test_audit_run_command.py`: `test_build_report_rejects_command_proxy_route_fallback`; `tests/test_benchmark_summary.py`: `test_strict_main_fails_for_plan_only_summary`, `test_strict_main_rejects_command_proxy_route_evidence`, `test_hash_mismatch_is_detected`; `tests/test_validate_cvm_submission.py`: `test_manifest_attribution_rejects_policy_attribution_for_blocker`. | Covered. |
| Failed, planned, blocked, completed, and diagnostic rows remain in aggregate denominators. | `tests/test_aggregate_cvm.py`: `test_failure_attribution_separates_integration_and_policy_rows`; `tests/test_run_cvm_matrix.py`: `test_resume_without_execute_preserves_completed_rows`; `artifacts/cvm/results/summary.json`. | Covered. |
| Support bundles exclude restricted assets and retain deterministic public-safe output. | `tests/test_support_bundle_command.py`: `test_build_report_creates_bundle_with_audit_outputs`, `test_build_report_writes_byte_stable_bundle`; `scripts/validate_cvm_submission.py` archive hygiene checks. | Covered for public support bundles. |
| Benchmark readiness requires a minimum scene/baseline/metric matrix before policy-quality claims. | `tests/test_benchmark_readiness.py`: `test_default_gate_rejects_partial_single_model_evidence`, `test_gate_accepts_clean_minimum_matrix`, `test_gate_requires_metric_coverage_for_every_scene`. | Covered. |
| Synthetic demo output schema is valid but not benchmark evidence. | `tests/test_synthetic_contract_demo.py`: `test_generate_demo_writes_audited_public_artifacts`, `test_script_prints_json_summary`; `README.md` ungated demo section. | Covered. |
| Public frame-level evidence exposes timing, route, trajectory, latency, lifecycle-warning, and policy-status fields without raw sensor frames. | `tests/test_validate_cvm_submission.py`: `test_frame_schema_accepts_required_public_fields`; `artifacts/cvm/results/frames.csv`. | Covered as schema-only public evidence. |

## Fault-Injection Diagnostics

| Behavior | Evidence | Status |
|---|---|---|
| Semantic, temporal, lifecycle, deployment/plugin, and evidence injections carry expected layer/code records. | `configs/cvm/fault_injection.yaml`; `artifacts/cvm/results/fault_injection.csv`; `tests/test_run_cvm_matrix.py`. | Covered as public synthetic diagnostics. |
| Fault detection and localization accuracy are aggregated with denominators. | `artifacts/cvm/results/fault_injection/fault_injection.csv`; `artifacts/cvm/tables/fault_localization.tex`; `tests/test_validate_cvm_submission.py`: `test_generated_table_value_check_accepts_summary_synced_tables`. | Covered as public synthetic diagnostics: 15/15 detected and 15/15 localized. |
| Mutation-style or third-party-authored fault precision is evaluated. | No current generated artifact. | Gap: current fault injection remains framework-authored diagnostics. The paper does not claim external mutation-testing precision or false-positive rate beyond valid full-contract false-block evidence. |

## Explicit Gaps Kept Out Of Policy Claims

- Temporal ablation scene rows are blocked by missing scene-matched direct-actor proxy evidence.
- Direct-actor policy behavior is not benchmarked in the public CVM.
- Learned token policy behavior is not benchmarked without a legitimate local checkpoint hash.
- Scenario-category coverage is not claimed because current local scene metadata is unclassified.
- The strict lifecycle comparison is a synthetic diagnostic, not evidence against a functional non-contract wrapper.
- Fault injection is framework-authored synthetic diagnostics, not external mutation-testing precision.
- The public release contains 0 claim-valid policy benchmark rows and 0 policy-failure-attributable rows.
