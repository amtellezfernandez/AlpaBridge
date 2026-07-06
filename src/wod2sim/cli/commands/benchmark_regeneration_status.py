from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from wod2sim.cli.commands.benchmark_regeneration_audit import audit_stage_claim

STATUS_SCHEMA = "wod2sim_benchmark_regeneration_status_v1"
BATCH_SCHEMA = "wod2sim_closed_loop_batch_summary_v1"
PLAN_SCHEMA = "wod2sim_benchmark_regeneration_plan_v1"
READINESS_SCHEMA = "wod2sim_benchmark_regeneration_readiness_v1"
DEFAULT_STATUS = Path("docs/evidence/benchmark_regeneration_status_20260706.json")
DEFAULT_PILOT = Path("docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json")
DEFAULT_PLAN = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
DEFAULT_READINESS = Path("docs/evidence/benchmark_regeneration_readiness_20260706.json")
DEFAULT_AUDIT = Path("docs/evidence/benchmark_regeneration_audit_20260706.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate the public WOD2Sim benchmark status from tracked compact "
            "evidence artifacts. This command does not probe Docker, GPUs, or caches."
        )
    )
    parser.add_argument("--pilot-summary", type=Path, default=DEFAULT_PILOT)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    parser.add_argument(
        "--audit",
        type=Path,
        default=DEFAULT_AUDIT,
        help="Audit artifact path to reference in the status evidence chain. The file is not read.",
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    status = build_status(
        pilot_path=args.pilot_summary,
        plan_path=args.plan,
        readiness_path=args.readiness,
        audit_path=args.audit,
        repo_root=args.repo_root,
        created_at=args.created_at,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        _print_human_summary(status)
    return 0


def build_status(
    *,
    pilot_path: Path = DEFAULT_PILOT,
    plan_path: Path = DEFAULT_PLAN,
    readiness_path: Path = DEFAULT_READINESS,
    audit_path: Path = DEFAULT_AUDIT,
    repo_root: Path = Path.cwd(),
    created_at: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    pilot = _read_json(_resolve_path(repo_root, pilot_path))
    plan = _read_json(_resolve_path(repo_root, plan_path))
    readiness = _read_json(_resolve_path(repo_root, readiness_path))

    _require_schema(pilot, BATCH_SCHEMA, "pilot summary")
    _require_schema(plan, PLAN_SCHEMA, "plan")
    _require_schema(readiness, READINESS_SCHEMA, "readiness")

    evidence_artifacts = {
        "ten_scene_pilot": _display_path(pilot_path),
        "regeneration_plan": _display_path(plan_path),
        "readiness_snapshot": _display_path(readiness_path),
        "claim_audit": _display_path(audit_path),
    }
    stage_reports = [
        audit_stage_claim(stage, repo_root=repo_root) for stage in _list_of_dicts(plan.get("stages"))
    ]
    scale_status = _scale_status(plan=plan, readiness=readiness, stage_reports=stage_reports)
    claim_ready = bool(stage_reports) and all(stage["claim_valid"] for stage in stage_reports)

    return {
        "schema": STATUS_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "objective": (
            "Regenerate WOD2Sim closed-loop benchmark artifacts from scratch, validate "
            "10-scene pilot evidence, scale to 50/100 scenes when runtime prerequisites "
            "are available, and track only public-safe artifacts."
        ),
        "evidence_artifacts": evidence_artifacts,
        "status_generator": {
            "command": "wod2sim-benchmark-status",
            "inputs": {
                "ten_scene_pilot": _display_path(pilot_path),
                "regeneration_plan": _display_path(plan_path),
                "readiness_snapshot": _display_path(readiness_path),
            },
            "referenced_artifacts": {
                "claim_audit": _display_path(audit_path),
            },
            "no_download_or_rollout_probes": True,
        },
        "public_artifact_policy": {
            "tracked": "Compact JSON summaries, documentation, commands, tests, and public-safe hashes/metrics.",
            "untracked": (
                "Raw AlpaSim media, support bundles, USDZ scene assets, Hugging Face "
                "caches, Docker layers, and gated scene-derived files."
            ),
        },
        "current_public_evidence": {
            "ten_scene_pilot": _pilot_status(pilot=pilot, pilot_path=pilot_path)
        },
        "current_local_runtime_state": _runtime_state_from_readiness(
            readiness=readiness,
            readiness_path=readiness_path,
        ),
        "scale_status": scale_status,
        "completion_status": {
            "full_objective_complete": claim_ready,
            "reason": _completion_reason(claim_ready=claim_ready, scale_status=scale_status),
        },
    }


def _pilot_status(*, pilot: dict[str, Any], pilot_path: Path) -> dict[str, Any]:
    aggregate = _dict_or_empty(pilot.get("aggregate"))
    failure_taxonomy = _dict_or_empty(pilot.get("failure_taxonomy"))
    return {
        "artifact": _display_path(pilot_path),
        "schema": pilot.get("schema"),
        "clean_closed_loop_batch": pilot.get("clean_closed_loop_batch"),
        "planned_scene_count": _optional_int(aggregate.get("planned_scene_count")),
        "completed_scene_count": _optional_int(aggregate.get("completed_scene_count")),
        "failed_scene_count": _optional_int(aggregate.get("failed_scene_count")),
        "sensor_failure_scene_count": _optional_int(aggregate.get("sensor_failure_scene_count")),
        "total_audited_frames": _optional_int(aggregate.get("total_audited_frames")),
        "failure_taxonomy": {
            "collision_scene_count": _optional_int(failure_taxonomy.get("collision_scene_count")),
            "at_fault_collision_scene_count": _optional_int(
                failure_taxonomy.get("at_fault_collision_scene_count")
            ),
            "wrong_lane_scene_count": _optional_int(failure_taxonomy.get("wrong_lane_scene_count")),
            "offroad_scene_count": _optional_int(failure_taxonomy.get("offroad_scene_count")),
            "low_progress_scene_count": _optional_int(
                failure_taxonomy.get("low_progress_scene_count")
            ),
            "high_plan_deviation_scene_count": _optional_int(
                failure_taxonomy.get("high_plan_deviation_scene_count")
            ),
        },
        "status": "tracked_public_summary",
    }


def _runtime_state_from_readiness(
    *,
    readiness: dict[str, Any],
    readiness_path: Path,
) -> dict[str, Any]:
    runtime_probes = _dict_or_empty(readiness.get("runtime_probes"))
    readiness_flags = _dict_or_empty(readiness.get("readiness"))
    host = _dict_or_empty(readiness.get("host"))
    disk = _dict_or_empty(readiness.get("disk"))
    docker_nvidia_runtime = _dict_or_empty(runtime_probes.get("docker_nvidia_runtime"))
    return {
        "derived_from": _display_path(readiness_path),
        "host_machine": host.get("machine"),
        "closed_loop_runner_supported": host.get("closed_loop_runner_supported"),
        "docker_daemon_ok": _probe_ok(runtime_probes.get("docker_daemon")),
        "docker_nvidia_runtime_present": docker_nvidia_runtime.get("declares_nvidia_runtime"),
        "alpasim_base_image_present": _probe_ok(runtime_probes.get("alpasim_base_image")),
        "nvidia_smi_ok": _probe_ok(runtime_probes.get("nvidia_smi")),
        "all_scale_caches_valid": readiness_flags.get("all_scale_caches_valid"),
        "claim_valid_scale_summaries_present": readiness_flags.get(
            "claim_valid_scale_summaries_present"
        ),
        "disk_free_gib_at_readiness": disk.get("free_gib"),
        "disk_meets_min_free_disk_gb": disk.get("meets_min_free_disk_gb"),
    }


def _scale_status(
    *,
    plan: dict[str, Any],
    readiness: dict[str, Any],
    stage_reports: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    readiness_by_preset = _by_preset(_list_of_dicts(readiness.get("stages")))
    reports_by_preset = _by_preset(stage_reports)
    rows: dict[str, dict[str, Any]] = {}
    for stage in _list_of_dicts(plan.get("stages")):
        if not stage.get("requires_local_usdz_cache"):
            continue
        preset = str(stage.get("scene_preset") or "")
        readiness_stage = readiness_by_preset.get(preset, {})
        stage_report = reports_by_preset.get(preset, {})
        local_usdz_cache = _dict_or_empty(readiness_stage.get("local_usdz_cache"))
        validation = _dict_or_empty(local_usdz_cache.get("validation"))
        claim_valid = bool(stage_report.get("claim_valid"))
        rows[preset] = {
            "stage": stage.get("stage"),
            "scene_count": _optional_int(stage.get("scene_count")),
            "preset_tracked": True,
            "cache_builder_workflow_tracked": _has_command(stage, "build_local_cache"),
            "local_usdz_cache_valid": validation.get("valid"),
            "summary_artifact": stage.get("public_summary_target"),
            "summary_present": bool(stage_report.get("summary_present")),
            "claim_valid_closed_loop_summary_tracked": claim_valid,
            "remaining_runtime_requirement": _scale_runtime_requirement(claim_valid=claim_valid),
        }
    return rows


def _scale_runtime_requirement(*, claim_valid: bool) -> str:
    if claim_valid:
        return (
            "No remaining runtime requirement for the tracked public claim; rerunning still "
            "requires an x86_64 AlpaSim runner with Docker/NVIDIA runtime images installed."
        )
    return (
        "Rebuild the local 26.02 USDZ cache and rerun on an x86_64 AlpaSim runner "
        "with Docker/NVIDIA runtime images installed."
    )


def _completion_reason(
    *,
    claim_ready: bool,
    scale_status: dict[str, dict[str, Any]],
) -> str:
    if claim_ready:
        return (
            "The repository tracks claim-valid public summaries for every planned stage "
            "in the regeneration plan."
        )
    missing = [
        row["summary_artifact"]
        for row in scale_status.values()
        if not row["claim_valid_closed_loop_summary_tracked"]
    ]
    missing_text = ", ".join(missing) if missing else "scale summaries"
    return (
        "The repository tracks a valid 10-scene public summary plus a plan, readiness "
        "snapshot, and audit gate, but fresh regenerated claim-valid scale summaries "
        f"are not currently present: {missing_text}."
    )


def _has_command(stage: dict[str, Any], name: str) -> bool:
    commands = _dict_or_empty(stage.get("commands"))
    return isinstance(commands.get(name), dict)


def _by_preset(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("scene_preset") or ""): row for row in rows}


def _probe_ok(value: object) -> bool | None:
    if not isinstance(value, dict):
        return None
    ok = value.get("ok")
    return ok if isinstance(ok, bool) else None


def _require_schema(payload: dict[str, Any], schema: str, label: str) -> None:
    actual = payload.get("schema")
    if actual != schema:
        raise ValueError(f"{label} schema must be {schema}, got {actual!r}")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON at {path}")
    return payload


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _resolve_path(repo_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return repo_root / path


def _display_path(path: Path) -> str:
    return str(path) if path.is_absolute() else path.as_posix()


def _print_human_summary(status: dict[str, Any]) -> None:
    completion = status["completion_status"]
    marker = "complete" if completion["full_objective_complete"] else "incomplete"
    print(f"{status['schema']}: {marker}")
    print(f"- ten_scene_pilot: {status['current_public_evidence']['ten_scene_pilot']['artifact']}")
    for preset, row in status["scale_status"].items():
        claim = "claim-valid" if row["claim_valid_closed_loop_summary_tracked"] else "not-ready"
        print(f"- {preset}: {claim} -> {row['summary_artifact']}")


if __name__ == "__main__":
    raise SystemExit(main())
