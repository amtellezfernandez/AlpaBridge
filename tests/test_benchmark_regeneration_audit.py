from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
AUDIT_RELATIVE = Path("docs/evidence/benchmark_regeneration_audit_20260706.json")
PLAN_RELATIVE = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
STATUS_RELATIVE = Path("docs/evidence/benchmark_regeneration_status_20260706.json")
READINESS_RELATIVE = Path("docs/evidence/benchmark_regeneration_readiness_20260706.json")
MANIFEST_RELATIVE = Path("docs/evidence/benchmark_public_evidence_manifest_20260706.json")
COMMANDS_RELATIVE = Path("docs/evidence/benchmark_regeneration_commands_20260706.json")
RESUME_COMMANDS_RELATIVE = Path(
    "docs/evidence/benchmark_regeneration_resume_commands_20260706.json"
)
OPERATOR_MATRIX_RELATIVE = Path("docs/evidence/benchmark_operator_matrix_20260706.json")
HANDOFF_RELATIVE = Path("docs/benchmark_regeneration_handoff.md")
PROBE_50_RELATIVE = Path(
    "docs/evidence/closed_loop_spotlight_reflex_50scene_localprobe_1scene.json"
)
ATTEMPT_50_RELATIVE = Path(
    "docs/evidence/closed_loop_spotlight_reflex_50scene_attempt_partial.json"
)


class BenchmarkRegenerationAuditTests(unittest.TestCase):
    def test_build_audit_reports_current_missing_50_and_100_scene_summaries(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")

        audit = module.build_audit(repo_root=ROOT, created_at="2026-07-06")
        stages = {stage["scene_preset"]: stage for stage in audit["stages"]}

        self.assertTrue(audit["valid"])
        self.assertFalse(audit["claim_ready"])
        self.assertEqual(READINESS_RELATIVE.as_posix(), audit["readiness_artifact"])
        self.assertTrue(audit["readiness_consistency"]["valid"])
        self.assertTrue(
            audit["readiness_consistency"]["checks"][
                "readiness_blocking_requirement_ids_match_state"
            ]
        )
        self.assertTrue(
            audit["readiness_consistency"]["checks"][
                "readiness_next_command_group_names_match_state"
            ]
        )
        self.assertTrue(
            audit["readiness_consistency"]["checks"][
                "readiness_next_command_group_renderer_groups_match_state"
            ]
        )
        self.assertTrue(audit["diagnostic_evidence"]["valid"])
        self.assertTrue(audit["regeneration_plan"]["valid"])
        self.assertEqual(PLAN_RELATIVE.as_posix(), audit["regeneration_plan"]["artifact"])
        self.assertTrue(audit["regeneration_plan"]["checks"]["regeneration_plan_matches_generator"])
        self.assertTrue(audit["regeneration_commands"]["valid"])
        self.assertEqual(COMMANDS_RELATIVE.as_posix(), audit["regeneration_commands"]["artifact"])
        self.assertTrue(
            audit["regeneration_commands"]["checks"][
                "regeneration_commands_rows_match_plan_renderer"
            ]
        )
        self.assertTrue(
            audit["regeneration_commands"]["checks"][
                "regeneration_commands_cover_readiness_renderer_groups"
            ]
        )
        self.assertTrue(
            audit["regeneration_commands"]["checks"][
                "regeneration_commands_execution_boundary_counts_match"
            ]
        )
        self.assertTrue(
            audit["regeneration_commands"]["checks"][
                "regeneration_commands_operator_role_counts_match"
            ]
        )
        self.assertTrue(
            audit["regeneration_commands"]["checks"]["regeneration_commands_boundary_totals_match"]
        )
        self.assertTrue(audit["regeneration_resume_commands"]["valid"])
        self.assertEqual(
            RESUME_COMMANDS_RELATIVE.as_posix(),
            audit["regeneration_resume_commands"]["artifact"],
        )
        self.assertEqual(36, audit["regeneration_resume_commands"]["row_count"])
        self.assertEqual(36, audit["regeneration_resume_commands"]["expected_row_count"])
        self.assertTrue(
            audit["regeneration_resume_commands"]["checks"][
                "regeneration_resume_commands_rows_match_audit_renderer"
            ]
        )
        self.assertTrue(
            audit["regeneration_resume_commands"]["checks"][
                "regeneration_resume_commands_resume_plan_matches_audit"
            ]
        )
        self.assertTrue(
            audit["regeneration_resume_commands"]["checks"][
                "regeneration_resume_commands_filters_match_resume_mode"
            ]
        )
        self.assertEqual(
            {
                "claim_summary_merge": 2,
                "claim_summary_promotion": 2,
                "live_closed_loop_rollout": 30,
                "public_metadata_review": 2,
            },
            audit["regeneration_resume_commands"]["execution_boundary_counts"],
        )
        self.assertEqual(
            2, audit["regeneration_resume_commands"]["resume_plan"]["affected_stage_count"]
        )
        self.assertEqual(
            15,
            audit["regeneration_resume_commands"]["resume_plan"]["missing_shard_summary_count"],
        )
        self.assertEqual(
            {
                "claim_summary_merge": 2,
                "claim_summary_promotion": 3,
                "live_closed_loop_rollout": 32,
                "private_cache_preparation": 6,
                "public_metadata_review": 4,
            },
            audit["regeneration_commands"]["execution_boundary_counts"],
        )
        self.assertTrue(audit["operator_matrix"]["valid"])
        self.assertEqual(OPERATOR_MATRIX_RELATIVE.as_posix(), audit["operator_matrix"]["artifact"])
        self.assertTrue(
            audit["operator_matrix"]["checks"]["operator_matrix_summary_matches_sources"]
        )
        self.assertTrue(
            audit["operator_matrix"]["checks"]["operator_matrix_command_execution_matches_sources"]
        )
        self.assertTrue(
            audit["operator_matrix"]["checks"][
                "operator_matrix_resume_command_execution_matches_sources"
            ]
        )
        self.assertTrue(
            audit["operator_matrix"]["checks"][
                "operator_matrix_resume_repair_scope_matches_sources"
            ]
        )
        self.assertTrue(audit["operator_matrix"]["checks"]["operator_matrix_roles_matches_sources"])
        self.assertTrue(audit["public_handoff_doc"]["valid"])
        self.assertEqual(HANDOFF_RELATIVE.as_posix(), audit["public_handoff_doc"]["artifact"])
        self.assertTrue(
            audit["public_handoff_doc"]["checks"]["public_handoff_doc_lists_resume_command"]
        )
        self.assertTrue(audit["public_evidence_manifest"]["valid"])
        self.assertEqual(
            MANIFEST_RELATIVE.as_posix(),
            audit["public_evidence_manifest"]["artifact"],
        )
        self.assertTrue(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_hashes_match_tracked_files"
            ]
        )
        self.assertTrue(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_scale_claim_gaps_match_audit"
            ]
        )
        self.assertEqual(PROBE_50_RELATIVE.as_posix(), audit["diagnostic_evidence"]["artifact"])
        self.assertEqual(
            "diagnostic_only_not_full_stage_claim",
            audit["diagnostic_evidence"]["claim_scope"],
        )
        partial_attempt = audit["diagnostic_evidence"]["scale_attempts"][
            "fifty_scene_partial_attempt"
        ]
        self.assertTrue(partial_attempt["valid"])
        self.assertEqual(ATTEMPT_50_RELATIVE.as_posix(), partial_attempt["artifact"])
        self.assertEqual(50, partial_attempt["observed"]["planned_scene_count"])
        self.assertEqual(2, partial_attempt["observed"]["observed_scene_count"])
        self.assertEqual(2, partial_attempt["observed"]["failed_scene_count"])
        self.assertFalse(audit["regeneration_provenance"]["all_stage_sources_match_plan"])
        self.assertEqual([], audit["regeneration_provenance"]["present_stage_source_mismatches"])
        self.assertTrue(stages["front_camera_10scene_smoke"]["claim_valid"])
        self.assertTrue(
            stages["front_camera_10scene_smoke"]["summary_provenance"]["source_matches_plan"]
        )
        self.assertEqual(
            "benchmark_spotlight_reflex_10scene_fresh",
            stages["front_camera_10scene_smoke"]["summary_provenance"]["expected_batch_dir_name"],
        )
        self.assertEqual(
            "benchmark_spotlight_reflex_10scene_fresh",
            stages["front_camera_10scene_smoke"]["summary_provenance"]["observed_batch_dir_name"],
        )
        self.assertFalse(stages["front_camera_50scene_public2602"]["claim_valid"])
        self.assertFalse(stages["front_camera_100scene_public2602"]["claim_valid"])
        self.assertIn(
            "docs/evidence/closed_loop_spotlight_reflex_50scene_batch.json",
            audit["missing_claim_valid_summaries"],
        )
        self.assertIn(
            "docs/evidence/closed_loop_spotlight_reflex_100scene_batch.json",
            audit["missing_claim_valid_summaries"],
        )
        completion = audit["objective_completion"]
        self.assertFalse(completion["complete"])
        self.assertIn(
            "produce_claim_valid_50_scene_summary",
            completion["remaining_requirements"],
        )
        self.assertIn(
            "produce_claim_valid_100_scene_summary",
            completion["remaining_requirements"],
        )
        self.assertIn("hf_token_missing", completion["blocking_requirements"])
        self.assertIn(
            "front_camera_50scene_public2602_cache_invalid",
            completion["blocking_requirements"],
        )
        self.assertIn(
            "front_camera_100scene_public2602_claim_summary_missing",
            completion["blocking_requirements"],
        )
        self.assertEqual(
            [
                "refresh_readiness",
                "build_and_validate_scale_caches",
                "run_scale_shards_and_promote_summaries",
                "refresh_status",
                "verify_claim_gate",
            ],
            completion["next_command_groups"],
        )
        self.assertEqual(
            {
                "build_and_validate_scale_caches": ["cache"],
                "refresh_readiness": ["readiness"],
                "refresh_status": ["post"],
                "run_scale_shards_and_promote_summaries": [
                    "shards",
                    "merge",
                    "promote",
                ],
                "verify_claim_gate": ["post"],
            },
            completion["next_command_renderer_groups"],
        )
        plan = _read_json(ROOT / PLAN_RELATIVE)
        scale_claim_gaps = {row["scene_preset"]: row for row in completion["scale_claim_gaps"]}
        expected_50_merge_inputs = _planned_merge_inputs(
            plan,
            "front_camera_50scene_public2602",
        )
        expected_100_merge_inputs = _planned_merge_inputs(
            plan,
            "front_camera_100scene_public2602",
        )
        self.assertEqual(
            {
                "front_camera_50scene_public2602",
                "front_camera_100scene_public2602",
            },
            set(scale_claim_gaps),
        )
        self.assertEqual(
            50, scale_claim_gaps["front_camera_50scene_public2602"]["expected_scene_count"]
        )
        self.assertEqual(
            5,
            scale_claim_gaps["front_camera_50scene_public2602"]["expected_merge_input_count"],
        )
        self.assertEqual(
            expected_50_merge_inputs,
            scale_claim_gaps["front_camera_50scene_public2602"]["expected_merge_input_summaries"],
        )
        self.assertEqual(
            {
                "claim_valid_count": 0,
                "complete": False,
                "expected_count": 5,
                "invalid_present_count": 0,
                "missing_count": 5,
                "present_count": 0,
            },
            scale_claim_gaps["front_camera_50scene_public2602"]["merge_input_progress"],
        )
        self.assertEqual(
            {
                "schema": "wod2sim_closed_loop_batch_summary_v1",
                "clean_closed_loop_batch": True,
                "planned_scene_count": 50,
                "completed_scene_count": 50,
                "failed_scene_count": 0,
                "sensor_failure_scene_count": 0,
                "source_kind": "merged_batch_summaries",
                "merge_input_summary_count": 5,
                "merge_input_summaries": expected_50_merge_inputs,
            },
            scale_claim_gaps["front_camera_50scene_public2602"]["claim_summary_acceptance"],
        )
        merge_statuses_50 = stages["front_camera_50scene_public2602"]["merge_provenance"][
            "expected_input_summary_statuses"
        ]
        self.assertEqual(5, len(merge_statuses_50))
        self.assertEqual(expected_50_merge_inputs[0], merge_statuses_50[0]["path"])
        self.assertFalse(merge_statuses_50[0]["present"])
        self.assertFalse(merge_statuses_50[0]["claim_valid"])
        self.assertEqual(["summary_missing"], merge_statuses_50[0]["errors"])
        self.assertFalse(scale_claim_gaps["front_camera_50scene_public2602"]["claim_valid"])
        self.assertFalse(
            scale_claim_gaps["front_camera_50scene_public2602"]["public_summary_present"]
        )
        self.assertEqual(
            ["summary_missing"],
            scale_claim_gaps["front_camera_50scene_public2602"]["public_summary_errors"],
        )
        self.assertEqual(
            {
                "expected_scene_count": 50,
                "matching_scene_count": 0,
                "missing_scene_count": 50,
                "nonmatching_usdz_file_count": 0,
                "present_scene_count": 0,
                "required": True,
                "usdz_file_count": 0,
                "valid": False,
            },
            scale_claim_gaps["front_camera_50scene_public2602"]["local_usdz_cache"],
        )
        self.assertEqual(
            {
                "expected_scene_count": 50,
                "matching_scene_count": 0,
                "missing_scene_count": 50,
                "nonmatching_usdz_file_count": 0,
                "present_scene_count": 0,
                "required": True,
                "usdz_file_count": 0,
                "valid": False,
            },
            scale_claim_gaps["front_camera_50scene_public2602"]["source_usdz_cache"],
        )
        self.assertIn(
            "front_camera_50scene_public2602_claim_summary_missing",
            scale_claim_gaps["front_camera_50scene_public2602"]["blocking_requirements"],
        )
        self.assertIn(
            "run_scale_shards_and_promote_summaries",
            scale_claim_gaps["front_camera_50scene_public2602"]["next_command_groups"],
        )
        self.assertEqual(
            100,
            scale_claim_gaps["front_camera_100scene_public2602"]["expected_scene_count"],
        )
        self.assertEqual(
            10,
            scale_claim_gaps["front_camera_100scene_public2602"]["expected_merge_input_count"],
        )
        self.assertEqual(
            expected_100_merge_inputs,
            scale_claim_gaps["front_camera_100scene_public2602"]["expected_merge_input_summaries"],
        )
        self.assertEqual(
            {
                "claim_valid_count": 0,
                "complete": False,
                "expected_count": 10,
                "invalid_present_count": 0,
                "missing_count": 10,
                "present_count": 0,
            },
            scale_claim_gaps["front_camera_100scene_public2602"]["merge_input_progress"],
        )
        self.assertEqual(
            "merged_batch_summaries",
            scale_claim_gaps["front_camera_100scene_public2602"]["claim_summary_acceptance"][
                "source_kind"
            ],
        )
        self.assertEqual(
            10,
            scale_claim_gaps["front_camera_100scene_public2602"]["claim_summary_acceptance"][
                "merge_input_summary_count"
            ],
        )
        self.assertEqual(
            100,
            scale_claim_gaps["front_camera_100scene_public2602"]["local_usdz_cache"][
                "missing_scene_count"
            ],
        )
        requirements = {item["requirement"]: item for item in completion["requirements"]}
        self.assertTrue(requirements["validate_10_scene_pilot"]["satisfied"])
        self.assertTrue(requirements["track_50_scene_scale_progress"]["satisfied"])
        self.assertFalse(requirements["pass_strict_claim_gate"]["satisfied"])
        self.assertIn(
            "front_camera_50scene_public2602_cache_invalid",
            requirements["produce_claim_valid_50_scene_summary"]["blocking_requirements"],
        )
        self.assertIn(
            "front_camera_100scene_public2602_claim_summary_missing",
            requirements["produce_claim_valid_100_scene_summary"]["blocking_requirements"],
        )
        self.assertIn(
            "run_scale_shards_and_promote_summaries",
            requirements["produce_claim_valid_50_scene_summary"]["next_command_groups"],
        )
        self.assertIn(
            "verify_claim_gate",
            requirements["pass_strict_claim_gate"]["next_command_groups"],
        )

    def test_strict_main_fails_until_all_planned_summaries_are_claim_valid(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "audit.json"

            with patch.object(
                sys,
                "argv",
                [
                    "wod2sim-benchmark-audit",
                    "--repo-root",
                    str(ROOT),
                    "--created-at",
                    "2026-07-06",
                    "--output",
                    str(output),
                    "--strict",
                    "--json",
                ],
            ):
                returncode = module.main()

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(1, returncode)
        self.assertFalse(payload["claim_ready"])

    def test_audit_can_pass_when_all_planned_summaries_and_status_flags_are_present(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            shutil.copy2(ROOT / PLAN_RELATIVE, evidence / PLAN_RELATIVE.name)
            _copy_status_and_probe(evidence)

            plan = _read_json(evidence / PLAN_RELATIVE.name)
            for scene_count in (10, 50, 100):
                _write_json(
                    evidence / f"closed_loop_spotlight_reflex_{scene_count}scene_batch.json",
                    _batch_summary(scene_count),
                )
            _write_json(
                evidence / READINESS_RELATIVE.name,
                _readiness_report(plan, claim_valid_scene_counts={10, 50, 100}),
            )
            _write_status(evidence)
            _write_operator_matrix(evidence)
            _write_public_evidence_manifest(
                evidence,
                claim_ready=True,
                missing_claim_valid_summaries=[],
            )
            _write_test_handoff_doc(
                repo_root,
                claim_ready=True,
                missing_claim_valid_summaries=[],
                blocker_ids=[],
                next_group_names=["refresh_readiness", "refresh_status", "verify_claim_gate"],
                renderer_groups=["post", "readiness"],
            )

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")
            stages = {stage["scene_preset"]: stage for stage in audit["stages"]}

        self.assertTrue(audit["valid"])
        self.assertTrue(audit["claim_ready"])
        self.assertTrue(audit["objective_completion"]["complete"])
        self.assertEqual([], audit["objective_completion"]["remaining_requirements"])
        self.assertEqual([], audit["objective_completion"]["blocking_requirements"])
        self.assertEqual([], audit["objective_completion"]["next_command_groups"])
        self.assertEqual({}, audit["objective_completion"]["next_command_renderer_groups"])
        self.assertTrue(
            all(row["claim_valid"] for row in audit["objective_completion"]["scale_claim_gaps"])
        )
        scale_claim_gaps = {
            row["scene_preset"]: row for row in audit["objective_completion"]["scale_claim_gaps"]
        }
        self.assertEqual(
            5,
            scale_claim_gaps["front_camera_50scene_public2602"]["expected_merge_input_count"],
        )
        self.assertEqual(
            10,
            scale_claim_gaps["front_camera_100scene_public2602"]["expected_merge_input_count"],
        )
        self.assertTrue(
            all(
                row["local_usdz_cache"]["valid"]
                for row in audit["objective_completion"]["scale_claim_gaps"]
            )
        )
        self.assertFalse(audit["regeneration_provenance"]["all_stage_sources_match_plan"])
        self.assertEqual([], audit["missing_claim_valid_summaries"])
        self.assertTrue(
            stages["front_camera_10scene_smoke"]["summary_provenance"]["source_matches_plan"]
        )
        self.assertFalse(
            stages["front_camera_50scene_public2602"]["merge_provenance"]["summary_is_merged"]
        )

    def test_audit_accepts_merged_scale_summary_when_inputs_match_plan(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            shutil.copy2(ROOT / PLAN_RELATIVE, evidence / PLAN_RELATIVE.name)
            _copy_status_and_probe(evidence)

            plan = _read_json(evidence / PLAN_RELATIVE.name)
            status = _read_json(evidence / STATUS_RELATIVE.name)
            status["completion_status"]["full_objective_complete"] = True
            for preset in (
                "front_camera_50scene_public2602",
                "front_camera_100scene_public2602",
            ):
                status["scale_status"][preset]["claim_valid_closed_loop_summary_tracked"] = True
            _write_json(evidence / STATUS_RELATIVE.name, status)
            _write_json(
                evidence / "closed_loop_spotlight_reflex_10scene_batch.json", _batch_summary(10)
            )
            for preset, scene_count in (
                ("front_camera_50scene_public2602", 50),
                ("front_camera_100scene_public2602", 100),
            ):
                planned_inputs = _planned_merge_inputs(plan, preset)
                for input_summary in planned_inputs:
                    input_path = repo_root / input_summary
                    input_path.parent.mkdir(parents=True, exist_ok=True)
                    _write_json(input_path, _batch_summary(10))
                _write_json(
                    evidence / f"closed_loop_spotlight_reflex_{scene_count}scene_batch.json",
                    _batch_summary(
                        scene_count,
                        input_summaries=planned_inputs,
                    ),
                )
            _write_json(
                evidence / READINESS_RELATIVE.name,
                _readiness_report(plan, claim_valid_scene_counts={10, 50, 100}),
            )

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")
            stages = {stage["scene_preset"]: stage for stage in audit["stages"]}

        self.assertTrue(audit["claim_ready"])
        self.assertTrue(audit["regeneration_provenance"]["all_stage_sources_match_plan"])
        self.assertTrue(
            stages["front_camera_50scene_public2602"]["merge_provenance"]["summary_is_merged"]
        )
        self.assertTrue(
            stages["front_camera_50scene_public2602"]["merge_provenance"][
                "input_summaries_match_plan"
            ]
        )
        self.assertEqual(
            {
                "claim_valid_count": 5,
                "complete": True,
                "expected_count": 5,
                "invalid_present_count": 0,
                "missing_count": 0,
                "present_count": 5,
            },
            stages["front_camera_50scene_public2602"]["merge_provenance"][
                "expected_input_summary_progress"
            ],
        )
        self.assertTrue(
            all(
                row["claim_valid"]
                for row in stages["front_camera_50scene_public2602"]["merge_provenance"][
                    "expected_input_summary_statuses"
                ]
            )
        )
        self.assertTrue(
            stages["front_camera_50scene_public2602"]["summary_provenance"]["source_matches_plan"]
        )

    def test_mismatched_merged_scale_summary_inputs_fail_the_stage(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            shutil.copy2(ROOT / PLAN_RELATIVE, evidence / PLAN_RELATIVE.name)
            _copy_status_and_probe(evidence)
            shutil.copy2(ROOT / READINESS_RELATIVE, evidence / READINESS_RELATIVE.name)
            _write_json(
                evidence / "closed_loop_spotlight_reflex_10scene_batch.json", _batch_summary(10)
            )
            _write_json(
                evidence / "closed_loop_spotlight_reflex_50scene_batch.json",
                _batch_summary(50, input_summaries=["wrong-shard.json"]),
            )

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")
            stages = {stage["scene_preset"]: stage for stage in audit["stages"]}

        self.assertFalse(stages["front_camera_50scene_public2602"]["claim_valid"])
        self.assertIn(
            "merge_input_summaries_mismatch",
            stages["front_camera_50scene_public2602"]["errors"],
        )
        self.assertFalse(
            stages["front_camera_50scene_public2602"]["merge_provenance"][
                "input_summaries_match_plan"
            ]
        )
        self.assertFalse(
            stages["front_camera_50scene_public2602"]["summary_provenance"]["source_matches_plan"]
        )

    def test_malformed_summary_is_reported_as_stage_error(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            shutil.copy2(ROOT / PLAN_RELATIVE, evidence / PLAN_RELATIVE.name)
            _copy_status_and_probe(evidence)
            shutil.copy2(ROOT / READINESS_RELATIVE, evidence / READINESS_RELATIVE.name)
            (evidence / "closed_loop_spotlight_reflex_10scene_batch.json").write_text(
                "{not-json\n",
                encoding="utf-8",
            )

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")
            stages = {stage["scene_preset"]: stage for stage in audit["stages"]}

        self.assertFalse(stages["front_camera_10scene_smoke"]["claim_valid"])
        self.assertTrue(
            any(
                error.startswith("summary_invalid_json:")
                for error in stages["front_camera_10scene_smoke"]["errors"]
            )
        )

    def test_tracked_audit_artifact_is_linked_from_docs(self) -> None:
        audit = _read_json(ROOT / AUDIT_RELATIVE)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        evaluation_protocol = (ROOT / "docs/evaluation_protocol.md").read_text(encoding="utf-8")

        self.assertEqual("wod2sim_benchmark_regeneration_audit_v1", audit["schema"])
        self.assertEqual(PLAN_RELATIVE.as_posix(), audit["plan_artifact"])
        self.assertEqual(STATUS_RELATIVE.as_posix(), audit["status_artifact"])
        self.assertEqual(READINESS_RELATIVE.as_posix(), audit["readiness_artifact"])
        self.assertTrue(audit["readiness_consistency"]["valid"])
        self.assertTrue(audit["diagnostic_evidence"]["valid"])
        self.assertTrue(audit["public_handoff_doc"]["valid"])
        self.assertEqual(HANDOFF_RELATIVE.as_posix(), audit["public_handoff_doc"]["artifact"])
        handoff_raw = (ROOT / HANDOFF_RELATIVE).read_bytes()
        self.assertEqual(len(handoff_raw), audit["public_handoff_doc"]["size_bytes"])
        self.assertEqual(
            hashlib.sha256(handoff_raw).hexdigest(),
            audit["public_handoff_doc"]["sha256"],
        )
        self.assertIn("objective_completion", audit)
        self.assertFalse(audit["objective_completion"]["complete"])
        self.assertFalse(audit["claim_ready"])
        self.assertIn(AUDIT_RELATIVE.as_posix(), readme)
        self.assertIn(AUDIT_RELATIVE.name, evaluation_protocol)

    def test_missing_readiness_artifact_invalidates_audit_artifact_set(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            shutil.copy2(ROOT / PLAN_RELATIVE, evidence / PLAN_RELATIVE.name)
            _copy_status_and_probe(evidence)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(audit["readiness_consistency"]["checks"]["readiness_artifact_loaded"])
        self.assertTrue(any(error.startswith("readiness missing:") for error in audit["errors"]))

    def test_readiness_summary_state_must_match_audited_summaries(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            shutil.copy2(ROOT / PLAN_RELATIVE, evidence / PLAN_RELATIVE.name)
            _copy_status_and_probe(evidence)
            plan = _read_json(evidence / PLAN_RELATIVE.name)
            _write_json(
                evidence / "closed_loop_spotlight_reflex_10scene_batch.json", _batch_summary(10)
            )
            _write_json(
                evidence / READINESS_RELATIVE.name,
                _readiness_report(plan, claim_valid_scene_counts=set()),
            )

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertIn(
            "readiness public_summary state does not match audit for front_camera_10scene_smoke",
            audit["readiness_consistency"]["notes"],
        )

    def test_readiness_next_command_group_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            readiness_path = evidence / READINESS_RELATIVE.name
            readiness = _read_json(readiness_path)
            readiness["next_command_groups"][1]["name"] = "stale_cache_group"
            _write_json(readiness_path, readiness)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, READINESS_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["readiness_consistency"]["checks"][
                "readiness_next_command_group_names_match_state"
            ]
        )
        self.assertTrue(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_hashes_match_tracked_files"
            ]
        )
        self.assertIn(
            "readiness.next_command_groups names do not match readiness state",
            audit["readiness_consistency"]["notes"],
        )

    def test_readiness_source_cache_flag_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            readiness_path = evidence / READINESS_RELATIVE.name
            readiness = _read_json(readiness_path)
            readiness["readiness"]["source_cache_link_ready"] = True
            _write_json(readiness_path, readiness)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, READINESS_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["readiness_consistency"]["checks"][
                "readiness_source_cache_link_flag_matches_stage_state"
            ]
        )
        self.assertIn(
            "readiness.source_cache_link_ready does not match source cache state",
            audit["readiness_consistency"]["notes"],
        )

    def test_readiness_cache_requirement_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            readiness_path = evidence / READINESS_RELATIVE.name
            readiness = _read_json(readiness_path)
            readiness["stages"][1]["cache_requirements"]["scene_ids_sha256"] = "bad"
            _write_json(readiness_path, readiness)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, READINESS_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["readiness_consistency"]["checks"][
                "front_camera_50scene_public2602_readiness_cache_requirements_match_preset"
            ]
        )
        self.assertIn(
            "readiness cache_requirements do not match preset for front_camera_50scene_public2602",
            audit["readiness_consistency"]["notes"],
        )

    def test_readiness_cache_inventory_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            readiness_path = evidence / READINESS_RELATIVE.name
            readiness = _read_json(readiness_path)
            readiness["stages"][1]["source_usdz_cache"]["matching_scene_count"] = 10
            _write_json(readiness_path, readiness)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, READINESS_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["readiness_consistency"]["checks"][
                (
                    "front_camera_50scene_public2602_readiness_source_usdz_cache_"
                    "inventory_counts_match_validation"
                )
            ]
        )
        self.assertIn(
            (
                "readiness source_usdz_cache inventory counts do not match validation "
                "for front_camera_50scene_public2602"
            ),
            audit["readiness_consistency"]["notes"],
        )

    def test_public_handoff_doc_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            handoff_path = repo_root / HANDOFF_RELATIVE
            handoff = handoff_path.read_text(encoding="utf-8")
            handoff_path.write_text(
                handoff.replace("hf_token_missing", "hf_token_removed"),
                encoding="utf-8",
            )

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["public_handoff_doc"]["checks"]["public_handoff_doc_lists_readiness_blockers"]
        )
        self.assertIn(
            "public handoff doc does not list current readiness blockers",
            audit["public_handoff_doc"]["notes"],
        )

    def test_public_handoff_cleanup_boundary_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            handoff_path = repo_root / HANDOFF_RELATIVE
            handoff = handoff_path.read_text(encoding="utf-8")
            handoff_path.write_text(
                handoff.replace("wod2sim-benchmark-cleanup --json", "cleanup command omitted"),
                encoding="utf-8",
            )

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["public_handoff_doc"]["checks"]["public_handoff_doc_states_cleanup_boundary"]
        )
        self.assertIn(
            "public handoff doc does not state the cleanup safety boundary",
            audit["public_handoff_doc"]["notes"],
        )

    def test_public_handoff_resume_command_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            handoff_path = repo_root / HANDOFF_RELATIVE
            handoff = handoff_path.read_text(encoding="utf-8")
            handoff_path.write_text(
                handoff.replace(
                    "wod2sim-benchmark-commands --resume-missing-shards-from-audit",
                    "resume command omitted",
                ),
                encoding="utf-8",
            )

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["public_handoff_doc"]["checks"]["public_handoff_doc_lists_resume_command"]
        )
        self.assertIn(
            "public handoff doc does not list the audit-based shard resume command",
            audit["public_handoff_doc"]["notes"],
        )

    def test_status_evidence_artifacts_must_match_audited_chain(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            shutil.copy2(ROOT / PLAN_RELATIVE, evidence / PLAN_RELATIVE.name)
            _copy_status_and_probe(evidence)
            shutil.copy2(ROOT / READINESS_RELATIVE, evidence / READINESS_RELATIVE.name)
            status = _read_json(evidence / STATUS_RELATIVE.name)
            status["evidence_artifacts"]["readiness_snapshot"] = "wrong-readiness.json"
            _write_json(evidence / STATUS_RELATIVE.name, status)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["status_consistency"]["checks"]["status_evidence_artifacts_match_audit_inputs"]
        )
        self.assertIn(
            "status.evidence_artifacts does not match the audited evidence chain",
            audit["status_consistency"]["notes"],
        )

    def test_public_evidence_manifest_hash_mismatch_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            manifest = _read_json(evidence / MANIFEST_RELATIVE.name)
            for artifact in manifest["artifacts"]:
                if (
                    artifact["path"]
                    == "docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json"
                ):
                    artifact["sha256"] = "0" * 64
                    break
            _write_json(evidence / MANIFEST_RELATIVE.name, manifest)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_hashes_match_tracked_files"
            ]
        )
        self.assertIn(
            "manifest hash mismatch: docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json",
            audit["public_evidence_manifest"]["notes"],
        )

    def test_public_evidence_manifest_scale_gap_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            manifest_path = evidence / MANIFEST_RELATIVE.name
            manifest = _read_json(manifest_path)
            manifest["claim_gate"]["scale_claim_gaps"][0]["local_usdz_cache"]["valid"] = True
            _write_json(manifest_path, manifest)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_scale_claim_gaps_match_audit"
            ]
        )
        self.assertIn(
            "public evidence manifest scale_claim_gaps do not match current audit",
            audit["public_evidence_manifest"]["notes"],
        )

    def test_regeneration_plan_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            plan_path = evidence / PLAN_RELATIVE.name
            plan = _read_json(plan_path)
            plan["who_can_do_what"][0]["role"] = "stale_reviewer"
            _write_json(plan_path, plan)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, PLAN_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["regeneration_plan"]["checks"]["regeneration_plan_matches_generator"]
        )
        self.assertTrue(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_hashes_match_tracked_files"
            ]
        )
        self.assertIn(
            "regeneration plan does not match wod2sim-benchmark-plan output",
            audit["regeneration_plan"]["notes"],
        )

    def test_status_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            status_path = evidence / STATUS_RELATIVE.name
            status = _read_json(status_path)
            status["completion_status"]["reason"] = "stale status fixture"
            _write_json(status_path, status)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, STATUS_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(audit["status_consistency"]["checks"]["status_matches_generator"])
        self.assertTrue(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_hashes_match_tracked_files"
            ]
        )
        self.assertIn(
            "status artifact does not match wod2sim-benchmark-status output",
            audit["status_consistency"]["notes"],
        )

    def test_status_cache_inventory_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            status_path = evidence / STATUS_RELATIVE.name
            status = _read_json(status_path)
            status["scale_status"]["front_camera_50scene_public2602"]["source_usdz_cache"][
                "matching_scene_count"
            ] = 10
            _write_json(status_path, status)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, STATUS_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["status_consistency"]["checks"][
                ("front_camera_50scene_public2602_source_usdz_cache_inventory_matches_readiness")
            ]
        )
        self.assertIn(
            (
                "scale_status.front_camera_50scene_public2602.source_usdz_cache "
                "does not match readiness"
            ),
            audit["status_consistency"]["notes"],
        )

    def test_regeneration_commands_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            commands_path = evidence / COMMANDS_RELATIVE.name
            commands = _read_json(commands_path)
            commands["row_count"] = int(commands["row_count"]) + 1
            _write_json(commands_path, commands)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, COMMANDS_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["regeneration_commands"]["checks"]["regeneration_commands_row_count_matches"]
        )
        self.assertTrue(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_hashes_match_tracked_files"
            ]
        )
        self.assertIn(
            "regeneration commands row_count does not match expected rows",
            audit["regeneration_commands"]["notes"],
        )

    def test_regeneration_commands_must_cover_readiness_renderer_groups(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            commands_path = evidence / COMMANDS_RELATIVE.name
            commands = _read_json(commands_path)
            commands["commands"] = [
                row for row in commands["commands"] if row.get("group") != "cache"
            ]
            commands["row_count"] = len(commands["commands"])
            commands["group_counts"].pop("cache")
            _write_json(commands_path, commands)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, COMMANDS_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["regeneration_commands"]["checks"][
                "regeneration_commands_cover_readiness_renderer_groups"
            ]
        )
        self.assertTrue(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_hashes_match_tracked_files"
            ]
        )
        self.assertIn(
            "regeneration commands do not cover readiness command_renderer_groups",
            audit["regeneration_commands"]["notes"],
        )

    def test_regeneration_commands_boundary_count_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            commands_path = evidence / COMMANDS_RELATIVE.name
            commands = _read_json(commands_path)
            commands["execution_boundary_counts"]["live_closed_loop_rollout"] = 0
            _write_json(commands_path, commands)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, COMMANDS_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["regeneration_commands"]["checks"][
                "regeneration_commands_execution_boundary_counts_match"
            ]
        )
        self.assertIn(
            "regeneration commands execution_boundary_counts do not match expected rows",
            audit["regeneration_commands"]["notes"],
        )

    def test_regeneration_resume_commands_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            resume_path = evidence / RESUME_COMMANDS_RELATIVE.name
            resume = _read_json(resume_path)
            resume["row_count"] = int(resume["row_count"]) + 1
            _write_json(resume_path, resume)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, RESUME_COMMANDS_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["regeneration_resume_commands"]["checks"][
                "regeneration_resume_commands_row_count_matches"
            ]
        )
        self.assertTrue(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_hashes_match_tracked_files"
            ]
        )
        self.assertIn(
            "regeneration resume commands row_count does not match expected rows",
            audit["regeneration_resume_commands"]["notes"],
        )

    def test_regeneration_resume_plan_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            resume_path = evidence / RESUME_COMMANDS_RELATIVE.name
            resume = _read_json(resume_path)
            resume["resume_plan"]["missing_shard_summary_count"] = 14
            _write_json(resume_path, resume)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, RESUME_COMMANDS_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["regeneration_resume_commands"]["checks"][
                "regeneration_resume_commands_resume_plan_matches_audit"
            ]
        )
        self.assertTrue(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_hashes_match_tracked_files"
            ]
        )
        self.assertIn(
            "regeneration resume commands resume_plan does not match current audit",
            audit["regeneration_resume_commands"]["notes"],
        )

    def test_operator_matrix_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            operator_path = evidence / OPERATOR_MATRIX_RELATIVE.name
            operator_matrix = _read_json(operator_path)
            operator_matrix["roles"][0]["can_run_now_from_tracked_state"] = False
            _write_json(operator_path, operator_matrix)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, OPERATOR_MATRIX_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["operator_matrix"]["checks"]["operator_matrix_roles_matches_sources"]
        )
        self.assertTrue(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_hashes_match_tracked_files"
            ]
        )
        self.assertIn(
            "operator matrix roles does not match audited sources",
            audit["operator_matrix"]["notes"],
        )

    def test_operator_matrix_command_execution_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            operator_path = evidence / OPERATOR_MATRIX_RELATIVE.name
            operator_matrix = _read_json(operator_path)
            operator_matrix["command_execution"]["public_review_command_count"] = 0
            _write_json(operator_path, operator_matrix)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, OPERATOR_MATRIX_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(
            audit["operator_matrix"]["checks"]["operator_matrix_command_execution_matches_sources"]
        )
        self.assertIn(
            "operator matrix command_execution does not match audited sources",
            audit["operator_matrix"]["notes"],
        )

    def test_missing_diagnostic_probe_invalidates_audit_artifact_set(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            shutil.copy2(ROOT / PLAN_RELATIVE, evidence / PLAN_RELATIVE.name)
            shutil.copy2(ROOT / STATUS_RELATIVE, evidence / STATUS_RELATIVE.name)
            shutil.copy2(ROOT / READINESS_RELATIVE, evidence / READINESS_RELATIVE.name)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        self.assertFalse(audit["valid"])
        self.assertFalse(audit["diagnostic_evidence"]["valid"])
        self.assertFalse(audit["diagnostic_evidence"]["checks"]["diagnostic_probe_summary_present"])
        self.assertIn(
            f"diagnostic probe summary missing: {PROBE_50_RELATIVE.as_posix()}",
            audit["diagnostic_evidence"]["notes"],
        )

    def test_partial_attempt_summary_scope_drift_invalidates_audit(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            _copy_evidence_jsons(evidence)
            attempt_path = evidence / ATTEMPT_50_RELATIVE.name
            attempt = _read_json(attempt_path)
            attempt["claim_boundary"] = "ambiguous partial evidence"
            _write_json(attempt_path, attempt)
            _refresh_manifest_hash(evidence / MANIFEST_RELATIVE.name, ATTEMPT_50_RELATIVE)

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")

        partial_attempt = audit["diagnostic_evidence"]["scale_attempts"][
            "fifty_scene_partial_attempt"
        ]
        self.assertFalse(audit["valid"])
        self.assertFalse(audit["diagnostic_evidence"]["valid"])
        self.assertFalse(partial_attempt["checks"]["partial_attempt_summary_scope_is_non_claim"])
        self.assertIn(
            "partial_attempt_summary_scope_is_non_claim failed",
            partial_attempt["notes"],
        )


def _batch_summary(
    scene_count: int,
    *,
    input_summaries: list[str] | None = None,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "schema": "wod2sim_closed_loop_batch_summary_v1",
        "clean_closed_loop_batch": True,
        "aggregate": {
            "planned_scene_count": scene_count,
            "completed_scene_count": scene_count,
            "failed_scene_count": 0,
            "sensor_failure_scene_count": 0,
            "total_audited_frames": scene_count * 199,
        },
        "created_at": "2026-07-06",
        "source": {
            "batch_dir_name": _batch_dir_name(scene_count),
            "batch_status": "batch-status.json",
            "batch_manifest": "batch-manifest.json",
        },
    }
    if input_summaries is not None:
        summary["source"] = {
            "summary_kind": "merged_batch_summaries",
            "input_summaries": input_summaries,
        }
    return summary


def _batch_dir_name(scene_count: int) -> str:
    if scene_count in {50, 100}:
        return f"benchmark_spotlight_reflex_{scene_count}scene_public2602_fresh"
    return f"benchmark_spotlight_reflex_{scene_count}scene_fresh"


def _planned_merge_inputs(plan: dict[str, object], scene_preset: str) -> list[str]:
    for stage in plan["stages"]:
        if stage["scene_preset"] != scene_preset:
            continue
        command = stage["commands"]["merge_shard_summaries"]["argv"]
        return [
            command[index + 1] for index, value in enumerate(command) if value == "--merge-summary"
        ]
    raise AssertionError(scene_preset)


def _readiness_report(
    plan: dict[str, object],
    *,
    claim_valid_scene_counts: set[int],
) -> dict[str, object]:
    from wod2sim.cli.commands.run_alpasim_local_external import _scene_ids

    stages = []
    for stage in plan["stages"]:
        scene_count = int(stage["scene_count"])
        claim_valid = scene_count in claim_valid_scene_counts
        scene_ids = _scene_ids(str(stage["scene_preset"]), [])
        requires_cache = bool(stage["requires_local_usdz_cache"])
        stages.append(
            {
                "stage": stage["stage"],
                "scene_preset": stage["scene_preset"],
                "scene_count": scene_count,
                "requires_local_usdz_cache": requires_cache,
                "cache_requirements": {
                    "required": requires_cache,
                    "scene_preset_file": (
                        f"src/wod2sim/simulator/alpasim_scene_presets/{stage['scene_preset']}.yaml"
                    ),
                    "scene_count": len(scene_ids),
                    "scene_ids_sha256": _scene_ids_sha256(scene_ids),
                    "scene_ids_sample": scene_ids[:10],
                    "local_usdz_dir": stage["local_usdz_dir"] if requires_cache else None,
                    "source_usdz_dir": stage["source_usdz_dir"] if requires_cache else None,
                },
                "local_usdz_cache": {
                    "required": requires_cache,
                    "local_usdz_dir": stage["local_usdz_dir"] if requires_cache else None,
                    "usdz_file_count": scene_count if requires_cache else None,
                    "matching_scene_count": scene_count if requires_cache else None,
                    "nonmatching_usdz_file_count": 0 if requires_cache else None,
                    "validation": {
                        "schema": "wod2sim_local_usdz_cache_validation_v1",
                        "valid": True,
                        "expected_scene_count": scene_count,
                        "present_scene_count": scene_count,
                    },
                },
                "source_usdz_cache": {
                    "required": requires_cache,
                    "source_usdz_dir": stage.get("source_usdz_dir"),
                    "usdz_file_count": scene_count if requires_cache else None,
                    "matching_scene_count": scene_count if requires_cache else None,
                    "nonmatching_usdz_file_count": 0 if requires_cache else None,
                    "validation": {
                        "schema": "wod2sim_local_usdz_cache_validation_v1",
                        "valid": True,
                        "expected_scene_count": scene_count,
                        "present_scene_count": scene_count,
                    },
                },
                "public_summary": {
                    "present": claim_valid,
                    "claim_valid": claim_valid,
                },
            }
        )
    scale_stages = [stage for stage in stages if bool(stage["requires_local_usdz_cache"])]
    scale_claims = [
        int(stage["scene_count"]) in claim_valid_scene_counts
        for stage in plan["stages"]
        if "public2602" in str(stage["scene_preset"])
    ]
    blocking_requirement_ids = [
        f"{stage['scene_preset']}_claim_summary_missing"
        for stage in scale_stages
        if stage["public_summary"]["claim_valid"] is not True
    ]
    next_group_names = ["refresh_readiness"]
    renderer_groups = {"refresh_readiness": ["readiness"]}
    if any(stage["local_usdz_cache"]["validation"]["valid"] is not True for stage in scale_stages):
        next_group_names.append("build_and_validate_scale_caches")
        renderer_groups["build_and_validate_scale_caches"] = ["cache"]
    if any(stage["public_summary"]["claim_valid"] is not True for stage in scale_stages):
        next_group_names.append("run_scale_shards_and_promote_summaries")
        renderer_groups["run_scale_shards_and_promote_summaries"] = [
            "shards",
            "merge",
            "promote",
        ]
    next_group_names.extend(["refresh_status", "verify_claim_gate"])
    renderer_groups["refresh_status"] = ["post"]
    renderer_groups["verify_claim_gate"] = ["post"]
    return {
        "schema": "wod2sim_benchmark_regeneration_readiness_v1",
        "plan_artifact": PLAN_RELATIVE.as_posix(),
        "status_artifact": STATUS_RELATIVE.as_posix(),
        "blocking_requirements": [
            {"id": requirement_id} for requirement_id in blocking_requirement_ids
        ],
        "next_command_groups": [
            {
                "command_renderer_groups": renderer_groups[name],
                "name": name,
                "order": order,
            }
            for order, name in enumerate(next_group_names, start=1)
        ],
        "readiness": {
            "all_scale_caches_valid": True,
            "all_scale_source_caches_valid": True,
            "source_cache_link_ready": True,
            "claim_valid_scale_summaries_present": all(scale_claims) if scale_claims else False,
        },
        "stages": stages,
    }


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _scene_ids_sha256(scene_ids: list[str]) -> str:
    return hashlib.sha256(("\n".join(scene_ids) + "\n").encode("utf-8")).hexdigest()


def _copy_status_and_probe(evidence_dir: Path) -> None:
    shutil.copy2(ROOT / STATUS_RELATIVE, evidence_dir / STATUS_RELATIVE.name)
    shutil.copy2(ROOT / COMMANDS_RELATIVE, evidence_dir / COMMANDS_RELATIVE.name)
    shutil.copy2(ROOT / RESUME_COMMANDS_RELATIVE, evidence_dir / RESUME_COMMANDS_RELATIVE.name)
    shutil.copy2(ROOT / OPERATOR_MATRIX_RELATIVE, evidence_dir / OPERATOR_MATRIX_RELATIVE.name)
    shutil.copy2(ROOT / PROBE_50_RELATIVE, evidence_dir / PROBE_50_RELATIVE.name)
    shutil.copy2(ROOT / ATTEMPT_50_RELATIVE, evidence_dir / ATTEMPT_50_RELATIVE.name)


def _copy_evidence_jsons(evidence_dir: Path) -> None:
    for path in sorted((ROOT / "docs" / "evidence").glob("*.json")):
        shutil.copy2(path, evidence_dir / path.name)
    handoff_target = evidence_dir.parents[1] / HANDOFF_RELATIVE
    handoff_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / HANDOFF_RELATIVE, handoff_target)


def _write_test_handoff_doc(
    repo_root: Path,
    *,
    claim_ready: bool,
    missing_claim_valid_summaries: list[str],
    blocker_ids: list[str],
    next_group_names: list[str],
    renderer_groups: list[str],
) -> None:
    handoff_path = repo_root / HANDOFF_RELATIVE
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    required_links = [
        PLAN_RELATIVE.as_posix(),
        STATUS_RELATIVE.as_posix(),
        READINESS_RELATIVE.as_posix(),
        COMMANDS_RELATIVE.as_posix(),
        RESUME_COMMANDS_RELATIVE.as_posix(),
        OPERATOR_MATRIX_RELATIVE.as_posix(),
        AUDIT_RELATIVE.as_posix(),
    ]
    lines = [
        "# Test Benchmark Regeneration Handoff",
        *required_links,
        *missing_claim_valid_summaries,
        *blocker_ids,
        *next_group_names,
        *(f"`{group}`" for group in renderer_groups),
        "wod2sim-benchmark-audit --strict --json",
        "wod2sim-benchmark-cleanup --json",
        "wod2sim-benchmark-commands --resume-missing-shards-from-audit",
        "dry-run by default",
        "tracked files",
        "--include-gated-assets",
        "--include-scale-caches",
        "--apply",
        "valid=true",
        f"claim_ready={str(claim_ready).lower()}",
        "Do not commit raw USDZ assets, Docker layers, Hugging Face caches, rollout videos, or support bundles.",
    ]
    handoff_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_public_evidence_manifest(
    evidence_dir: Path,
    *,
    claim_ready: bool,
    missing_claim_valid_summaries: list[str],
) -> None:
    audit_module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
    repo_root = evidence_dir.parents[1]
    bootstrap_audit = audit_module.build_audit(repo_root=repo_root, created_at="2026-07-06")
    _write_json(evidence_dir / AUDIT_RELATIVE.name, bootstrap_audit)
    scale_claim_gaps = bootstrap_audit["objective_completion"]["scale_claim_gaps"]

    manifest_path = evidence_dir / MANIFEST_RELATIVE.name
    artifacts = []
    for path in sorted(evidence_dir.glob("*.json")):
        if path.name == MANIFEST_RELATIVE.name:
            continue
        raw = path.read_bytes()
        relative = f"docs/evidence/{path.name}"
        artifacts.append(
            {
                "path": relative,
                "present": True,
                "public_safe": True,
                "schema": _read_json(path).get("schema"),
                "artifact_type": "test_fixture_public_evidence",
                "claim_scope": (
                    "manifest_source_artifact"
                    if relative
                    in {
                        PLAN_RELATIVE.as_posix(),
                        STATUS_RELATIVE.as_posix(),
                    }
                    else "test_fixture_public_evidence"
                ),
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    manifest = {
        "schema": "wod2sim_benchmark_public_evidence_manifest_v1",
        "created_at": "2026-07-06",
        "manifest_artifact": MANIFEST_RELATIVE.as_posix(),
        "source_artifacts": {
            "audit": AUDIT_RELATIVE.as_posix(),
            "plan": PLAN_RELATIVE.as_posix(),
            "status": STATUS_RELATIVE.as_posix(),
        },
        "generator": {
            "command": "wod2sim-benchmark-evidence-manifest",
            "no_download_or_rollout_probes": True,
            "excludes_self_hash": True,
        },
        "claim_gate": {
            "valid": True,
            "claim_ready": claim_ready,
            "missing_claim_valid_summaries": missing_claim_valid_summaries,
            "scale_claim_gaps": scale_claim_gaps,
            "strict_command": "wod2sim-benchmark-audit --strict --json",
        },
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "missing_expected_artifacts": [
            {
                "path": path,
                "present": False,
                "required_for_full_claim": True,
                "claim_scope": "missing_claim_valid_scale_summary",
            }
            for path in missing_claim_valid_summaries
        ],
    }
    _write_json(manifest_path, manifest)


def _write_operator_matrix(evidence_dir: Path) -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_operator_matrix")
    repo_root = evidence_dir.parents[1]
    matrix = module.build_operator_matrix(
        repo_root=repo_root,
        plan_path=PLAN_RELATIVE,
        status_path=STATUS_RELATIVE,
        readiness_path=READINESS_RELATIVE,
        created_at="2026-07-06",
    )
    _write_json(evidence_dir / OPERATOR_MATRIX_RELATIVE.name, matrix)


def _write_status(evidence_dir: Path) -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_status")
    repo_root = evidence_dir.parents[1]
    status = module.build_status(repo_root=repo_root, created_at="2026-07-06")
    _write_json(evidence_dir / STATUS_RELATIVE.name, status)


def _refresh_manifest_hash(manifest_path: Path, artifact_relative: Path) -> None:
    manifest = _read_json(manifest_path)
    artifact_path = manifest_path.parents[2] / artifact_relative
    raw = artifact_path.read_bytes()
    for artifact in manifest["artifacts"]:
        if artifact["path"] == artifact_relative.as_posix():
            artifact["size_bytes"] = len(raw)
            artifact["sha256"] = hashlib.sha256(raw).hexdigest()
            break
    _write_json(manifest_path, manifest)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
