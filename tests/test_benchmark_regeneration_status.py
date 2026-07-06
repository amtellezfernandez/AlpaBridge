from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATUS_RELATIVE = Path("docs/evidence/benchmark_regeneration_status_20260706.json")
PILOT_RELATIVE = Path("docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json")


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

    for preset in (
        "front_camera_50scene_public2602",
        "front_camera_100scene_public2602",
    ):
        scale_status = status["scale_status"][preset]
        assert scale_status["preset_tracked"] is True
        assert scale_status["cache_builder_workflow_tracked"] is True
        assert scale_status["claim_valid_closed_loop_summary_tracked"] is False
        assert "x86_64 AlpaSim runner" in scale_status["remaining_runtime_requirement"]


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

    assert STATUS_RELATIVE.as_posix() in readme
    assert "Open-repo readers can review the compact JSON summaries" in readme
    assert "ARM/DGX Spark" in readme


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
