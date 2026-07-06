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
OPERATOR_MATRIX_RELATIVE = Path("docs/evidence/benchmark_operator_matrix_20260706.json")
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
        self.assertTrue(audit["diagnostic_evidence"]["valid"])
        self.assertTrue(audit["regeneration_commands"]["valid"])
        self.assertEqual(COMMANDS_RELATIVE.as_posix(), audit["regeneration_commands"]["artifact"])
        self.assertTrue(
            audit["regeneration_commands"]["checks"][
                "regeneration_commands_rows_match_plan_renderer"
            ]
        )
        self.assertTrue(audit["operator_matrix"]["valid"])
        self.assertEqual(OPERATOR_MATRIX_RELATIVE.as_posix(), audit["operator_matrix"]["artifact"])
        self.assertTrue(
            audit["operator_matrix"]["checks"]["operator_matrix_roles_matches_sources"]
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
            stages["front_camera_10scene_smoke"]["summary_provenance"][
                "expected_batch_dir_name"
            ],
        )
        self.assertEqual(
            "benchmark_spotlight_reflex_10scene_fresh",
            stages["front_camera_10scene_smoke"]["summary_provenance"][
                "observed_batch_dir_name"
            ],
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
        requirements = {
            item["requirement"]: item for item in completion["requirements"]
        }
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
            status = _read_json(evidence / STATUS_RELATIVE.name)
            status["completion_status"]["full_objective_complete"] = True
            for preset in (
                "front_camera_50scene_public2602",
                "front_camera_100scene_public2602",
            ):
                status["scale_status"][preset]["claim_valid_closed_loop_summary_tracked"] = True
            _write_json(evidence / STATUS_RELATIVE.name, status)

            for scene_count in (10, 50, 100):
                _write_json(
                    evidence / f"closed_loop_spotlight_reflex_{scene_count}scene_batch.json",
                    _batch_summary(scene_count),
                )
            _write_json(
                evidence / READINESS_RELATIVE.name,
                _readiness_report(plan, claim_valid_scene_counts={10, 50, 100}),
            )
            _write_operator_matrix(evidence)
            _write_public_evidence_manifest(
                evidence,
                claim_ready=True,
                missing_claim_valid_summaries=[],
            )

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")
            stages = {stage["scene_preset"]: stage for stage in audit["stages"]}

        self.assertTrue(audit["valid"])
        self.assertTrue(audit["claim_ready"])
        self.assertTrue(audit["objective_completion"]["complete"])
        self.assertEqual([], audit["objective_completion"]["remaining_requirements"])
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
            _write_json(evidence / "closed_loop_spotlight_reflex_10scene_batch.json", _batch_summary(10))
            for preset, scene_count in (
                ("front_camera_50scene_public2602", 50),
                ("front_camera_100scene_public2602", 100),
            ):
                _write_json(
                    evidence / f"closed_loop_spotlight_reflex_{scene_count}scene_batch.json",
                    _batch_summary(
                        scene_count,
                        input_summaries=_planned_merge_inputs(plan, preset),
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
        self.assertTrue(
            stages["front_camera_50scene_public2602"]["summary_provenance"][
                "source_matches_plan"
            ]
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
            _write_json(evidence / "closed_loop_spotlight_reflex_10scene_batch.json", _batch_summary(10))
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
            stages["front_camera_50scene_public2602"]["summary_provenance"][
                "source_matches_plan"
            ]
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
            _write_json(evidence / "closed_loop_spotlight_reflex_10scene_batch.json", _batch_summary(10))
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
                if artifact["path"] == "docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json":
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
        self.assertFalse(audit["operator_matrix"]["checks"]["operator_matrix_roles_matches_sources"])
        self.assertTrue(
            audit["public_evidence_manifest"]["checks"][
                "public_evidence_manifest_hashes_match_tracked_files"
            ]
        )
        self.assertIn(
            "operator matrix roles does not match audited sources",
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
        self.assertFalse(
            audit["diagnostic_evidence"]["checks"]["diagnostic_probe_summary_present"]
        )
        self.assertIn(
            f"diagnostic probe summary missing: {PROBE_50_RELATIVE.as_posix()}",
            audit["diagnostic_evidence"]["notes"],
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
            command[index + 1]
            for index, value in enumerate(command)
            if value == "--merge-summary"
        ]
    raise AssertionError(scene_preset)


def _readiness_report(
    plan: dict[str, object],
    *,
    claim_valid_scene_counts: set[int],
) -> dict[str, object]:
    stages = []
    for stage in plan["stages"]:
        scene_count = int(stage["scene_count"])
        claim_valid = scene_count in claim_valid_scene_counts
        stages.append(
            {
                "stage": stage["stage"],
                "scene_preset": stage["scene_preset"],
                "scene_count": scene_count,
                "requires_local_usdz_cache": bool(stage["requires_local_usdz_cache"]),
                "local_usdz_cache": {
                    "required": bool(stage["requires_local_usdz_cache"]),
                    "validation": {"valid": True},
                },
                "public_summary": {
                    "present": claim_valid,
                    "claim_valid": claim_valid,
                },
            }
        )
    scale_claims = [
        int(stage["scene_count"]) in claim_valid_scene_counts
        for stage in plan["stages"]
        if "public2602" in str(stage["scene_preset"])
    ]
    return {
        "schema": "wod2sim_benchmark_regeneration_readiness_v1",
        "plan_artifact": PLAN_RELATIVE.as_posix(),
        "status_artifact": STATUS_RELATIVE.as_posix(),
        "readiness": {
            "claim_valid_scale_summaries_present": all(scale_claims) if scale_claims else False,
        },
        "stages": stages,
    }


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_status_and_probe(evidence_dir: Path) -> None:
    shutil.copy2(ROOT / STATUS_RELATIVE, evidence_dir / STATUS_RELATIVE.name)
    shutil.copy2(ROOT / COMMANDS_RELATIVE, evidence_dir / COMMANDS_RELATIVE.name)
    shutil.copy2(ROOT / OPERATOR_MATRIX_RELATIVE, evidence_dir / OPERATOR_MATRIX_RELATIVE.name)
    shutil.copy2(ROOT / PROBE_50_RELATIVE, evidence_dir / PROBE_50_RELATIVE.name)
    shutil.copy2(ROOT / ATTEMPT_50_RELATIVE, evidence_dir / ATTEMPT_50_RELATIVE.name)


def _copy_evidence_jsons(evidence_dir: Path) -> None:
    for path in sorted((ROOT / "docs" / "evidence").glob("*.json")):
        shutil.copy2(path, evidence_dir / path.name)


def _write_public_evidence_manifest(
    evidence_dir: Path,
    *,
    claim_ready: bool,
    missing_claim_valid_summaries: list[str],
) -> None:
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
