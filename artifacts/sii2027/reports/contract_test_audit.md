# SII 2027 Contract Test Audit

This audit maps the required Phase D SII tests to the current repository tests.
Status meanings:

- `supported`: an existing test directly checks the required behavior.
- `partial`: related coverage exists, but the required SII behavior is not fully checked.
- `missing`: no independently diagnosable equivalent was found.
- `skipped-or-gated`: a test exists but does not run in the ungated public environment.

Evidence source: `artifacts/sii2027/logs/tests/all_test_names.log`, inspected test
bodies in `tests/`, and filtered test runs recorded in `artifacts/sii2027/reports/test_report.md`.

## Summary

| Contract area | Required tests | Supported | Partial | Missing | Skipped or gated |
|---|---:|---:|---:|---:|---:|
| Semantic | 8 | 5 | 3 | 0 | 0 |
| Temporal | 10 | 10 | 0 | 0 | 0 |
| Lifecycle | 8 | 0 | 2 | 6 | 0 |
| Plugin/dependency boundary | 9 | 5 | 2 | 1 | 1 |
| Deployment | 9 | 5 | 4 | 0 | 0 |
| Evidence | 9 | 6 | 2 | 1 | 0 |
| Fault injection | 15 | 15 | 0 | 0 | 0 |

Overall status: the existing suite is useful for public release hardening, route
semantics, deployment planning, and evidence gating, but Phase D is not complete.
The SII paper can cite conformance tests and public synthetic diagnostics. It cannot
claim closed-loop lifecycle stress or simulator-backed fault-localization coverage.

## D1 Semantic Contract

| Required behavior | Current status | Current evidence |
|---|---|---|
| `test_route_waypoints_reach_prediction_input` | `supported` | `tests/test_alpasim_integration.py::test_alpasim_signal_uses_route_waypoints_as_lane_center`; `test_route_following_baseline_tracks_supplied_route_geometry` |
| `test_command_proxy_route_is_marked_not_claim_valid` | `supported` | `tests/test_audit_run_command.py::test_build_report_rejects_command_proxy_route_fallback`; `tests/test_batch_summary.py::test_route_contract_failure_prevents_clean_claim_summary` |
| `test_ego_lane_reference_is_not_raw_road_center` | `partial` | Route-waypoint lane-center coverage exists, and the synthetic demo records road-center offset diagnostics; no named multi-lane offset regression test was found. |
| `test_structured_hazard_aliases_are_semantically_equivalent` | `partial` | Structured/static/moving hazard paths are covered, but alias equivalence across all accepted input names is not tested as one contract. |
| `test_static_hazard_geometry_and_heading_are_preserved` | `supported` | `tests/test_alpasim_integration.py::test_alpasim_signal_preserves_static_hazard_shape_metadata` |
| `test_dynamic_actor_velocity_heading_and_behavior_are_preserved` | `supported` | `test_alpasim_signal_preserves_moving_hazards_as_actors`; `test_alpasim_signal_preserves_moving_hazard_shape_metadata`; `test_alpasim_signal_preserves_explicit_moving_behavior`; `test_alpasim_signal_preserves_explicit_heading_for_elongated_vehicle` |
| `test_visibility_risk_does_not_fabricate_obstacles` | `supported` | `tests/test_alpasim_integration.py::test_alpasim_signal_keeps_inferred_risk_diagnostic_only` |
| `test_missing_route_has_explicit_fallback_and_reason_code` | `partial` | Command-proxy fallback is detected by audit and batch summary, but the prediction-time missing-route reason code is not fully covered as a standalone test. |

## D2 Temporal Contract

| Required behavior | Current status | Current evidence |
|---|---|---|
| `test_resampling_identity_when_grids_match` | `supported` | `tests/test_alpasim_integration.py::test_resample_trajectory_preserves_native_runtime_samples` |
| `test_linear_endpoint_trajectory_interpolates_exactly` | `supported` | `tests/test_alpasim_integration.py::test_resample_trajectory_uses_origin_anchored_endpoint_interpolation` |
| `test_interpolation_is_anchored_at_current_ego_origin` | `supported` | `tests/test_alpasim_integration.py::test_interpolation_is_anchored_at_current_ego_origin` |
| `test_headings_are_recomputed_on_runtime_grid` | `supported` | `tests/test_alpasim_integration.py::test_headings_are_recomputed_on_runtime_grid` |
| `test_output_shape_matches_runtime_contract` | `supported` | Multiple adapter tests assert `(20, 2)` trajectory output and `(20,)` headings. |
| `test_nonfinite_trajectory_is_rejected` | `supported` | `tests/test_alpasim_integration.py::test_nonfinite_trajectory_is_rejected` |
| `test_invalid_horizon_or_frequency_is_rejected` | `supported` | `tests/test_alpasim_integration.py::test_invalid_horizon_or_frequency_is_rejected` |
| `test_duplicate_or_nonmonotonic_timestamps_are_handled_explicitly` | `supported` | `tests/test_alpasim_integration.py::test_duplicate_or_nonmonotonic_timestamps_are_handled_explicitly`; `resample_trajectory(..., source_timestamps=...)` rejects duplicate, nonmonotonic, nonfinite, and out-of-horizon source timestamps. |
| `test_curved_path_error_matches_piecewise_linear_reference` | `supported` | `tests/test_alpasim_integration.py::test_curved_path_error_matches_piecewise_linear_reference` |
| `test_multiple_runtime_frequencies_are_supported` | `supported` | `tests/test_alpasim_integration.py::test_multiple_runtime_frequencies_are_supported` checks 10 Hz and 20 Hz target grids over a 5 s horizon. |

## D3 Lifecycle Contract

| Required behavior | Current status | Current evidence |
|---|---|---|
| `test_duplicate_close_is_idempotent` | `missing` | The setup patch contains an idempotent-close log message, but no executable unit test was found. |
| `test_late_image_after_close_does_not_crash` | `missing` | Patch text exists; no runtime test was found. |
| `test_late_egomotion_after_close_does_not_crash` | `missing` | Patch text exists; no runtime test was found. |
| `test_late_route_after_close_does_not_crash` | `missing` | Patch text exists; no runtime test was found. |
| `test_unknown_session_event_is_structured_and_counted` | `partial` | Late/unknown-session messages are present in patch materialization, but structured counters are not asserted by tests. |
| `test_session_cleanup_prevents_state_leak` | `missing` | No session state-leak regression test found. |
| `test_interleaved_sessions_remain_isolated` | `missing` | No interleaved-session isolation test found. |
| `test_repeated_start_stop_cycles_are_stable` | `partial` | The SII synthetic lifecycle matrix executed 40 rows: 20/20 hardened cycles survived and 0/20 strict/pre-hardening cycles survived. This is not an AlpaSim service unit test. |

## D4 Plugin And Dependency Boundary

| Required behavior | Current status | Current evidence |
|---|---|---|
| `test_base_model_contract_imports_without_optional_backends` | `partial` | Core tests pass without learned-policy checkpoint execution; no clean-subprocess optional-backend exclusion test was found. |
| `test_external_entry_points_are_discoverable` | `supported` | `tests/test_alpasim_integration.py::test_pyproject_registers_alpasim_plugin_entrypoints`; doctor entry-point checks. |
| `test_unselected_alpamayo_or_vam_is_not_imported` | `missing` | No explicit unselected optional-module import isolation test found. |
| `test_missing_optional_backend_has_actionable_error` | `partial` | Skipped Torch tests and setup diagnostics exist, but no dedicated actionable-error assertion for every optional backend was found. |
| `test_missing_checkpoint_fails_cleanly` | `supported` | Launcher/model preset tests enforce checkpoint requirements for learned/direct actor paths. |
| `test_invalid_token_schema_is_rejected` | `skipped-or-gated` | `tests/test_alpasim_integration.py::test_token_bc_alpasim_adapter_rejects_unknown_checkpoint_tokens` exists, but token-BC adapter tests are skipped from core conformance and skip when Torch is unavailable. |
| `test_constant_velocity_is_deterministic` | `supported` | `test_constant_velocity_baseline_is_dependency_light_and_auditable` covers deterministic geometry and audit log fields. |
| `test_route_following_is_deterministic` | `supported` | `test_route_following_baseline_tracks_supplied_route_geometry` covers deterministic route-following output for a fixed input. |
| `test_direct_actor_planner_returns_valid_model_prediction` | `supported` | `tests/test_alpasim_integration.py::test_direct_actor_planner_returns_trajectory_without_token_selector` |

Skipped/gated note: learned-policy checkpoint tests are skipped from core conformance when Torch or a legitimate checkpoint is unavailable.

## D5 Deployment Contract

| Required behavior | Current status | Current evidence |
|---|---|---|
| `test_setup_check_only_has_no_mutating_side_effect` | `supported` | `tests/test_alpasim_setup_scripts.py::test_setup_check_only_does_not_bootstrap_or_install` |
| `test_readiness_reports_each_missing_precondition` | `partial` | Doctor/readiness tests cover missing Docker/image/GPU/cache classes; exact SII precondition set is not a single test. |
| `test_print_mode_materializes_deterministic_commands` | `supported` | `tests/test_run_alpasim_scene_batch.py::test_scene_command_forwards_launcher_options`; setup print-mode tests. |
| `test_driver_and_wizard_commands_use_matching_address_topology_and_ports` | `supported` | Launch command tests assert propagated topology/ports/options. |
| `test_scene_preset_expansion_is_exact` | `supported` | `tests/test_run_alpasim_scene_batch.py::test_selected_scene_ids_can_slice_preset`; `test_scene_offset_preserves_batch_index_numbering` |
| `test_shell_arguments_are_safely_quoted` | `partial` | Commands are built as argument vectors in several tests; no explicit shell-quoting adversarial case found. |
| `test_manifest_records_git_image_config_and_checkpoint_hashes` | `partial` | Dry-run and print-mode manifests record git/image/config/checkpoint fields, but digest/hash completeness is not fully asserted for SII manifests. |
| `test_arm_and_gpu_platform_guards_are_explicit` | `partial` | Docker/GPU preflight tests exist; architecture/platform guard coverage is not complete. |
| `test_repeated_setup_is_idempotent` | `supported` | Setup/override synchronization tests and check-only behavior cover idempotent setup paths. |

## D6 Evidence Contract

| Required behavior | Current status | Current evidence |
|---|---|---|
| `test_proxy_route_rejects_claim_validity` | `supported` | `tests/test_benchmark_summary.py::test_strict_main_rejects_command_proxy_route_evidence`; audit and batch-summary route contract tests. |
| `test_incomplete_rollout_rejects_claim_validity` | `supported` | `tests/test_batch_summary.py::test_strict_main_fails_for_incomplete_batch` |
| `test_missing_manifest_field_rejects_claim_validity` | `partial` | Manifest planned-count fallback is tested; missing-field rejection is not comprehensively tested. |
| `test_hash_mismatch_is_detected` | `missing` | Hashes are calculated in benchmark-summary tests, but no explicit mismatch-failure test was found. |
| `test_failed_runs_are_retained_in_aggregation` | `supported` | Batch-summary and SII aggregation retain failed/blocked rows; current SII results preserve 55 completed synthetic rows and 90 blocked closed-loop rows. |
| `test_aggregate_denominators_include_failures` | `supported` | Batch-summary tests and SII aggregate summary include failed/blocked denominators. |
| `test_support_bundle_excludes_restricted_assets_and_secrets` | `supported` | `tests/test_support_bundle_command.py::test_build_report_creates_bundle_with_audit_outputs`; generated-artifact secret scan. |
| `test_benchmark_readiness_requires_minimum_scene_baseline_matrix` | `supported` | `tests/test_benchmark_readiness.py::test_default_gate_rejects_partial_single_model_evidence`; `test_gate_accepts_clean_minimum_matrix` |
| `test_demo_output_schema_is_valid` | `partial` | Synthetic demo JSON summary is tested; SII-specific demo schema validation is not a standalone test. |

## D7 Fault Injection

| Required injection | Current status | Current evidence |
|---|---|---|
| `semantic.route_missing` | `supported` | Executed by `scripts/run_sii2027_matrix.py --execute`; see `artifacts/sii2027/results/fault_injection.csv`. |
| `semantic.command_only` | `supported` | Executed by the public synthetic fault harness. |
| `semantic.road_center_reference` | `supported` | Executed by the public synthetic fault harness. |
| `temporal.stale_observation` | `supported` | Executed by the public synthetic fault harness. |
| `temporal.invalid_sample_count` | `supported` | Executed by the public synthetic fault harness. |
| `temporal.nan_trajectory` | `supported` | Executed by the public synthetic fault harness. |
| `lifecycle.duplicate_close` | `supported` | Executed by the public synthetic fault harness. |
| `lifecycle.late_image` | `supported` | Executed by the public synthetic fault harness. |
| `lifecycle.late_route` | `supported` | Executed by the public synthetic fault harness. |
| `plugin.optional_backend_missing` | `supported` | Executed by the public synthetic fault harness. |
| `deployment.docker_unavailable` | `supported` | Executed by the public synthetic fault harness. |
| `deployment.gpu_runtime_unavailable` | `supported` | Executed by the public synthetic fault harness. |
| `deployment.scene_artifact_missing` | `supported` | Executed by the public synthetic fault harness. |
| `evidence.manifest_missing` | `supported` | Executed by the public synthetic fault harness. |
| `evidence.hash_mismatch` | `supported` | Executed by the public synthetic fault harness. |

Current public synthetic fault-localization denominator: 15 configured injections,
15 executed injections, and 15 correctly localized injected failures. This may be
reported only as a synthetic harness diagnostic, not as closed-loop policy evidence.

## Release Implication

This audit strengthens the public release because it prevents overclaiming. The
repository can be released as a contract-based integration package with passing public
quality gates and an honest SII draft, but it is not ready to claim completed SII
closed-loop experiments or simulator-backed lifecycle/fault reliability.
