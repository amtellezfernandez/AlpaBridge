from __future__ import annotations

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


class BenchmarkRegenerationAuditTests(unittest.TestCase):
    def test_build_audit_reports_current_missing_50_and_100_scene_summaries(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")

        audit = module.build_audit(repo_root=ROOT, created_at="2026-07-06")
        stages = {stage["scene_preset"]: stage for stage in audit["stages"]}

        self.assertTrue(audit["valid"])
        self.assertFalse(audit["claim_ready"])
        self.assertEqual(READINESS_RELATIVE.as_posix(), audit["readiness_artifact"])
        self.assertTrue(audit["readiness_consistency"]["valid"])
        self.assertTrue(stages["front_camera_10scene_smoke"]["claim_valid"])
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
            shutil.copy2(ROOT / STATUS_RELATIVE, evidence / STATUS_RELATIVE.name)

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

            audit = module.build_audit(repo_root=repo_root, created_at="2026-07-06")
            stages = {stage["scene_preset"]: stage for stage in audit["stages"]}

        self.assertTrue(audit["valid"])
        self.assertTrue(audit["claim_ready"])
        self.assertEqual([], audit["missing_claim_valid_summaries"])
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
            shutil.copy2(ROOT / STATUS_RELATIVE, evidence / STATUS_RELATIVE.name)

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
        self.assertTrue(
            stages["front_camera_50scene_public2602"]["merge_provenance"]["summary_is_merged"]
        )
        self.assertTrue(
            stages["front_camera_50scene_public2602"]["merge_provenance"][
                "input_summaries_match_plan"
            ]
        )

    def test_mismatched_merged_scale_summary_inputs_fail_the_stage(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            shutil.copy2(ROOT / PLAN_RELATIVE, evidence / PLAN_RELATIVE.name)
            shutil.copy2(ROOT / STATUS_RELATIVE, evidence / STATUS_RELATIVE.name)
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

    def test_malformed_summary_is_reported_as_stage_error(self) -> None:
        module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_audit")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            evidence = repo_root / "docs" / "evidence"
            evidence.mkdir(parents=True)
            shutil.copy2(ROOT / PLAN_RELATIVE, evidence / PLAN_RELATIVE.name)
            shutil.copy2(ROOT / STATUS_RELATIVE, evidence / STATUS_RELATIVE.name)
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
            shutil.copy2(ROOT / STATUS_RELATIVE, evidence / STATUS_RELATIVE.name)

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
            shutil.copy2(ROOT / STATUS_RELATIVE, evidence / STATUS_RELATIVE.name)
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
            shutil.copy2(ROOT / STATUS_RELATIVE, evidence / STATUS_RELATIVE.name)
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
    }
    if input_summaries is not None:
        summary["source"] = {
            "summary_kind": "merged_batch_summaries",
            "input_summaries": input_summaries,
        }
    return summary


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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
