from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
STATUS_RELATIVE = Path("docs/evidence/benchmark_regeneration_status_20260706.json")
PILOT_RELATIVE = Path("docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json")
PROBE_50_RELATIVE = Path(
    "docs/evidence/closed_loop_spotlight_reflex_50scene_localprobe_1scene.json"
)
ATTEMPT_50_RELATIVE = Path(
    "docs/evidence/closed_loop_spotlight_reflex_50scene_attempt_partial.json"
)
PLAN_RELATIVE = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
READINESS_RELATIVE = Path("docs/evidence/benchmark_regeneration_readiness_20260706.json")
AUDIT_RELATIVE = Path("docs/evidence/benchmark_regeneration_audit_20260706.json")
COMMANDS_RELATIVE = Path("docs/evidence/benchmark_regeneration_commands_20260706.json")
RESUME_COMMANDS_RELATIVE = Path(
    "docs/evidence/benchmark_regeneration_resume_commands_20260706.json"
)
OPERATOR_MATRIX_RELATIVE = Path("docs/evidence/benchmark_operator_matrix_20260706.json")
EVIDENCE_MANIFEST_RELATIVE = Path("docs/evidence/benchmark_public_evidence_manifest_20260706.json")
HANDOFF_RELATIVE = Path("docs/benchmark_regeneration_handoff.md")


def test_regeneration_status_matches_tracked_ten_scene_evidence() -> None:
    status = _read_json(ROOT / STATUS_RELATIVE)
    pilot = _read_json(ROOT / PILOT_RELATIVE)

    public_pilot = status["current_public_evidence"]["ten_scene_pilot"]
    assert status["schema"] == "wod2sim_benchmark_regeneration_status_v1"
    assert public_pilot["artifact"] == PILOT_RELATIVE.as_posix()
    assert public_pilot["schema"] == pilot["schema"]
    assert public_pilot["clean_closed_loop_batch"] is True
    assert public_pilot["clean_closed_loop_batch"] == pilot["clean_closed_loop_batch"]

    for key in (
        "planned_scene_count",
        "completed_scene_count",
        "failed_scene_count",
        "sensor_failure_scene_count",
        "total_audited_frames",
    ):
        assert public_pilot[key] == pilot["aggregate"][key]

    for key in (
        "collision_scene_count",
        "at_fault_collision_scene_count",
        "wrong_lane_scene_count",
        "offroad_scene_count",
        "low_progress_scene_count",
        "high_plan_deviation_scene_count",
    ):
        assert public_pilot["failure_taxonomy"][key] == pilot["failure_taxonomy"][key]

    assert status["completion_status"]["full_objective_complete"] is False


def test_large_scale_status_is_workflow_ready_but_not_claim_valid() -> None:
    status = _read_json(ROOT / STATUS_RELATIVE)
    plan = _read_json(ROOT / PLAN_RELATIVE)
    audit = _read_json(ROOT / AUDIT_RELATIVE)
    readiness = _read_json(ROOT / READINESS_RELATIVE)
    stages = {stage["scene_preset"]: stage for stage in plan["stages"]}
    readiness_stages = {stage["scene_preset"]: stage for stage in readiness["stages"]}

    for preset in (
        "front_camera_50scene_public2602",
        "front_camera_100scene_public2602",
    ):
        scale_status = status["scale_status"][preset]
        readiness_stage = readiness_stages[preset]
        source_cache = readiness_stage["source_usdz_cache"]
        source_validation = source_cache["validation"]
        assert scale_status["preset_tracked"] is True
        assert scale_status["cache_builder_workflow_tracked"] is True
        assert scale_status["summary_artifact"] == stages[preset]["public_summary_target"]
        assert scale_status["summary_artifact"] in audit["missing_claim_valid_summaries"]
        assert scale_status["claim_valid_closed_loop_summary_tracked"] is False
        assert scale_status["local_usdz_cache"]["valid"] is False
        assert scale_status["source_usdz_cache"] == {
            "required": True,
            "valid": False,
            "expected_scene_count": source_validation["expected_scene_count"],
            "present_scene_count": source_validation["present_scene_count"],
            "missing_scene_count": source_validation["missing_scene_count"],
            "usdz_file_count": source_cache["usdz_file_count"],
            "matching_scene_count": source_cache["matching_scene_count"],
            "nonmatching_usdz_file_count": source_cache["nonmatching_usdz_file_count"],
        }
        assert scale_status["source_usdz_cache"]["usdz_file_count"] == 0
        assert scale_status["source_usdz_cache"]["matching_scene_count"] == 0
        assert "x86_64 AlpaSim runner" in scale_status["remaining_runtime_requirement"]


def test_status_tracks_50_scene_local_probe_as_diagnostic_only() -> None:
    status = _read_json(ROOT / STATUS_RELATIVE)
    probe = _read_json(ROOT / PROBE_50_RELATIVE)

    public_probe = status["current_public_evidence"]["fifty_scene_local_probe"]
    assert public_probe["artifact"] == PROBE_50_RELATIVE.as_posix()
    assert public_probe["present"] is True
    assert public_probe["status"] == "tracked_public_probe_summary"
    assert public_probe["claim_scope"].startswith("Diagnostic one-scene probe")
    assert public_probe["schema"] == probe["schema"]
    assert public_probe["scene_preset"] == "front_camera_50scene_public2602"
    assert public_probe["planned_scene_count"] == 1
    assert public_probe["completed_scene_count"] == 1
    assert public_probe["sensor_failure_scene_count"] == 0
    assert (
        status["scale_status"]["front_camera_50scene_public2602"][
            "claim_valid_closed_loop_summary_tracked"
        ]
        is False
    )


def test_status_tracks_partial_50_scene_attempt_as_diagnostic_only() -> None:
    status = _read_json(ROOT / STATUS_RELATIVE)
    attempt = _read_json(ROOT / ATTEMPT_50_RELATIVE)

    public_attempt = status["current_public_evidence"]["fifty_scene_partial_attempt"]
    assert public_attempt["artifact"] == ATTEMPT_50_RELATIVE.as_posix()
    assert public_attempt["present"] is True
    assert public_attempt["status"] == "tracked_public_partial_attempt_summary"
    assert "not a claim-valid 50-scene" in public_attempt["claim_scope"]
    assert public_attempt["schema"] == attempt["schema"]
    assert public_attempt["scene_preset"] == "front_camera_50scene_public2602"
    assert public_attempt["planned_scene_count"] == 50
    assert public_attempt["observed_scene_count"] == 2
    assert public_attempt["completed_scene_count"] == 0
    assert public_attempt["failed_scene_count"] == 2
    assert public_attempt["sensor_failure_scene_count"] == 0
    assert (
        status["scale_status"]["front_camera_50scene_public2602"][
            "claim_valid_closed_loop_summary_tracked"
        ]
        is False
    )


def test_public_artifact_policy_excludes_heavy_or_gated_runtime_artifacts() -> None:
    status = _read_json(ROOT / STATUS_RELATIVE)
    untracked_policy = status["public_artifact_policy"]["untracked"].lower()

    for expected in (
        "raw alpasim media",
        "support bundles",
        "usdz scene assets",
        "hugging face caches",
        "docker layers",
        "gated scene-derived files",
    ):
        assert expected in untracked_policy


def test_readme_links_current_regeneration_status() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    compact_readme = " ".join(readme.split())

    assert STATUS_RELATIVE.as_posix() in readme
    assert HANDOFF_RELATIVE.as_posix() in readme
    assert PROBE_50_RELATIVE.as_posix() in readme
    assert ATTEMPT_50_RELATIVE.as_posix() in readme
    assert COMMANDS_RELATIVE.as_posix() in readme
    assert RESUME_COMMANDS_RELATIVE.as_posix() in readme
    assert OPERATOR_MATRIX_RELATIVE.as_posix() in readme
    assert EVIDENCE_MANIFEST_RELATIVE.as_posix() in readme
    assert "Open-repo readers can review the compact JSON summaries" in readme
    assert "`command_execution` counts" in readme
    assert "`execution_boundary_counts`" in readme
    assert "`private_execution_command_count`" in readme
    assert "`scale_status.<preset>.source_usdz_cache`" in readme
    assert "`matching_scene_count` of `0` for both presets" in readme
    assert "cache building, live shard execution, and claim promotion" in compact_readme
    assert "ARM/DGX Spark" in readme
    assert "| `wod2sim-benchmark-cleanup` |" in readme
    assert "| `wod2sim-benchmark-status` |" in readme


def test_public_handoff_doc_tracks_current_claim_gate() -> None:
    handoff = (ROOT / HANDOFF_RELATIVE).read_text(encoding="utf-8")
    evaluation_protocol = (ROOT / "docs/evaluation_protocol.md").read_text(encoding="utf-8")
    audit = _read_json(ROOT / AUDIT_RELATIVE)
    readiness = _read_json(ROOT / READINESS_RELATIVE)
    operator_matrix = _read_json(ROOT / OPERATOR_MATRIX_RELATIVE)

    assert HANDOFF_RELATIVE.as_posix() in evaluation_protocol
    assert STATUS_RELATIVE.as_posix() in handoff
    assert AUDIT_RELATIVE.as_posix() in handoff
    assert READINESS_RELATIVE.as_posix() in handoff
    assert OPERATOR_MATRIX_RELATIVE.as_posix() in handoff
    assert COMMANDS_RELATIVE.as_posix() in handoff
    assert RESUME_COMMANDS_RELATIVE.as_posix() in handoff
    assert "command execution counts by role" in handoff
    assert "execution-boundary and operator-role counts" in handoff
    assert "`scale_status.<preset>.source_usdz_cache`" in handoff
    assert "`scale_status.<preset>.source_usdz_cache`" in evaluation_protocol
    assert "wod2sim-benchmark-cleanup --json" in handoff
    assert "`execution_boundary_counts`" in evaluation_protocol
    assert "`matching_scene_count` of `0` for both 50/100 presets" in evaluation_protocol
    for missing in audit["missing_claim_valid_summaries"]:
        assert missing in handoff
    for blocker in readiness["blocking_requirements"]:
        assert blocker["id"] in handoff
    for group in operator_matrix["summary"]["next_command_groups"]:
        assert group in handoff
    for renderer_groups in operator_matrix["summary"]["next_command_renderer_groups"].values():
        for renderer_group in renderer_groups:
            assert f"`{renderer_group}`" in handoff
    assert "wod2sim-benchmark-commands --group shards" in handoff
    assert "valid=true" in handoff
    assert "claim_ready=false" in handoff
    assert "`scale_claim_gaps`" in handoff
    assert "`next_command_renderer_groups`" in handoff
    assert "Do not commit raw USDZ assets" in handoff


def test_status_links_current_public_evidence_chain() -> None:
    status = _read_json(ROOT / STATUS_RELATIVE)
    plan = _read_json(ROOT / PLAN_RELATIVE)
    readiness = _read_json(ROOT / READINESS_RELATIVE)
    audit = _read_json(ROOT / AUDIT_RELATIVE)

    assert status["evidence_artifacts"] == {
        "ten_scene_pilot": PILOT_RELATIVE.as_posix(),
        "fifty_scene_local_probe": PROBE_50_RELATIVE.as_posix(),
        "fifty_scene_partial_attempt": ATTEMPT_50_RELATIVE.as_posix(),
        "regeneration_plan": PLAN_RELATIVE.as_posix(),
        "readiness_snapshot": READINESS_RELATIVE.as_posix(),
        "regeneration_commands": COMMANDS_RELATIVE.as_posix(),
        "regeneration_resume_commands": RESUME_COMMANDS_RELATIVE.as_posix(),
        "operator_matrix": OPERATOR_MATRIX_RELATIVE.as_posix(),
        "public_evidence_manifest": EVIDENCE_MANIFEST_RELATIVE.as_posix(),
        "public_handoff_doc": HANDOFF_RELATIVE.as_posix(),
        "claim_audit": AUDIT_RELATIVE.as_posix(),
    }
    assert plan["status_artifact"] == STATUS_RELATIVE.as_posix()
    assert plan["readiness_artifact"] == READINESS_RELATIVE.as_posix()
    assert readiness["plan_artifact"] == PLAN_RELATIVE.as_posix()
    assert readiness["status_artifact"] == STATUS_RELATIVE.as_posix()
    assert audit["plan_artifact"] == PLAN_RELATIVE.as_posix()
    assert audit["status_artifact"] == STATUS_RELATIVE.as_posix()
    assert audit["readiness_artifact"] == READINESS_RELATIVE.as_posix()
    assert audit["valid"] is True
    assert audit["claim_ready"] is False


def test_status_generator_rebuilds_tracked_public_state() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_status")

    status = module.build_status(repo_root=ROOT, created_at="2026-07-06")
    tracked = _read_json(ROOT / STATUS_RELATIVE)

    assert status["schema"] == tracked["schema"]
    assert status["created_at"] == "2026-07-06"
    assert status["evidence_artifacts"] == tracked["evidence_artifacts"]
    assert status["current_public_evidence"] == tracked["current_public_evidence"]
    assert status["scale_status"] == tracked["scale_status"]
    assert status["completion_status"] == tracked["completion_status"]
    assert status["status_generator"]["command"] == "wod2sim-benchmark-status"
    assert status["status_generator"]["no_download_or_rollout_probes"] is True


def test_status_main_writes_json_without_runtime_probes() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_status")
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "status.json"

        with patch.object(
            sys,
            "argv",
            [
                "wod2sim-benchmark-status",
                "--repo-root",
                str(ROOT),
                "--created-at",
                "2026-07-06",
                "--output",
                str(output),
                "--json",
            ],
        ):
            returncode = module.main()

        payload = json.loads(output.read_text(encoding="utf-8"))

    assert returncode == 0
    assert payload["created_at"] == "2026-07-06"
    assert payload["current_local_runtime_state"]["derived_from"] == READINESS_RELATIVE.as_posix()
    assert "docker_containers" not in payload["current_local_runtime_state"]


def test_status_generator_does_not_require_existing_audit_artifact_for_completed_claims() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_regeneration_status")
    with TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        evidence = repo_root / "docs" / "evidence"
        evidence.mkdir(parents=True)
        _write_json(evidence / PLAN_RELATIVE.name, _read_json(ROOT / PLAN_RELATIVE))
        _write_json(evidence / READINESS_RELATIVE.name, _completed_readiness())
        for scene_count in (10, 50, 100):
            _write_json(
                evidence / f"closed_loop_spotlight_reflex_{scene_count}scene_batch.json",
                _batch_summary(scene_count),
            )

        status = module.build_status(
            repo_root=repo_root,
            audit_path=AUDIT_RELATIVE,
            created_at="2026-07-06",
        )

    assert status["completion_status"]["full_objective_complete"] is True
    assert status["status_generator"]["referenced_artifacts"] == {
        "regeneration_commands": COMMANDS_RELATIVE.as_posix(),
        "regeneration_resume_commands": RESUME_COMMANDS_RELATIVE.as_posix(),
        "operator_matrix": OPERATOR_MATRIX_RELATIVE.as_posix(),
        "public_evidence_manifest": EVIDENCE_MANIFEST_RELATIVE.as_posix(),
        "public_handoff_doc": HANDOFF_RELATIVE.as_posix(),
        "claim_audit": AUDIT_RELATIVE.as_posix(),
    }
    assert "claim_audit" not in status["status_generator"]["inputs"]
    assert all(
        row["claim_valid_closed_loop_summary_tracked"] for row in status["scale_status"].values()
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _batch_summary(scene_count: int) -> dict[str, Any]:
    return {
        "schema": "wod2sim_closed_loop_batch_summary_v1",
        "clean_closed_loop_batch": True,
        "aggregate": {
            "planned_scene_count": scene_count,
            "completed_scene_count": scene_count,
            "failed_scene_count": 0,
            "sensor_failure_scene_count": 0,
            "total_audited_frames": scene_count * 199,
        },
        "failure_taxonomy": {
            "collision_scene_count": 0,
            "at_fault_collision_scene_count": 0,
            "wrong_lane_scene_count": 0,
            "offroad_scene_count": 0,
            "low_progress_scene_count": 0,
            "high_plan_deviation_scene_count": 0,
        },
    }


def _completed_readiness() -> dict[str, Any]:
    readiness = _read_json(ROOT / READINESS_RELATIVE)
    readiness["readiness"]["all_scale_caches_valid"] = True
    readiness["readiness"]["claim_valid_scale_summaries_present"] = True
    for stage in readiness["stages"]:
        public_summary = stage["public_summary"]
        public_summary["present"] = True
        public_summary["claim_valid"] = True
        public_summary["errors"] = []
        for cache_name in ("local_usdz_cache", "source_usdz_cache"):
            cache = stage[cache_name]
            if cache["required"]:
                cache["validation"]["valid"] = True
                cache["validation"]["present_scene_count"] = cache["validation"][
                    "expected_scene_count"
                ]
                cache["validation"]["missing_scene_count"] = 0
                cache["matching_scene_count"] = cache["validation"]["present_scene_count"]
                cache["nonmatching_usdz_file_count"] = 0
    return readiness
