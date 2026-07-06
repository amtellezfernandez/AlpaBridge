from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from wod2sim.cli.commands.benchmark_regeneration_plan import (
    DEFAULT_MODEL,
    DEFAULT_PILOT_PRESET,
    DEFAULT_SCALE_PRESETS,
    STATUS_ARTIFACT,
    build_plan,
)
from wod2sim.cli.commands.build_alpasim_local_usdz_cache import (
    DEFAULT_HF_REVISION,
    validate_local_usdz_cache,
)

READINESS_SCHEMA = "wod2sim_benchmark_regeneration_readiness_v1"
PLAN_ARTIFACT = "docs/evidence/benchmark_regeneration_plan_20260706.json"
DEFAULT_OUTPUT = Path("docs/evidence/benchmark_regeneration_readiness_20260706.json")
DEFAULT_MIN_FREE_DISK_GB = 200
_GPU_UUID_RE = re.compile(r"\(UUID: [^)]+\)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Emit a no-download, no-rollout readiness report for the WOD2Sim "
            "10/50/100 benchmark regeneration plan."
        )
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--pilot-preset", default=DEFAULT_PILOT_PRESET)
    parser.add_argument(
        "--scale-preset",
        action="append",
        default=None,
        help="Scale preset to include. Defaults to the 50/100 public 26.02 presets.",
    )
    parser.add_argument(
        "--alpasim-root",
        type=Path,
        default=None,
        help="Local AlpaSim checkout root. Defaults to $ALPASIM_ROOT or ./workspace/alpasim.",
    )
    parser.add_argument("--runs-root", default="runs")
    parser.add_argument("--hf-revision", default=DEFAULT_HF_REVISION)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--min-free-disk-gb", type=int, default=DEFAULT_MIN_FREE_DISK_GB)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    report = build_readiness_report(
        model=args.model,
        pilot_preset=args.pilot_preset,
        scale_presets=args.scale_preset,
        alpasim_root=args.alpasim_root,
        runs_root=args.runs_root,
        hf_revision=args.hf_revision,
        repo_root=args.repo_root,
        created_at=args.created_at,
        min_free_disk_gb=args.min_free_disk_gb,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human_summary(report)
    return 0 if report["valid"] else 1


def build_readiness_report(
    *,
    model: str = DEFAULT_MODEL,
    pilot_preset: str = DEFAULT_PILOT_PRESET,
    scale_presets: list[str] | tuple[str, ...] | None = None,
    alpasim_root: Path | None = None,
    runs_root: str = "runs",
    hf_revision: str = DEFAULT_HF_REVISION,
    repo_root: Path = Path.cwd(),
    created_at: str | None = None,
    min_free_disk_gb: int = DEFAULT_MIN_FREE_DISK_GB,
    env: dict[str, str] | None = None,
    command_runner: Callable[[list[str]], dict[str, Any]] | None = None,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> dict[str, Any]:
    env_map = dict(os.environ if env is None else env)
    repo_root = repo_root.resolve()
    resolved_alpasim_root = _resolve_alpasim_root(alpasim_root, env=env_map)
    selected_scale_presets = tuple(scale_presets or DEFAULT_SCALE_PRESETS)
    plan = build_plan(
        model=model,
        pilot_preset=pilot_preset,
        scale_presets=selected_scale_presets,
        alpasim_root=str(resolved_alpasim_root),
        runs_root=runs_root,
        hf_revision=hf_revision,
        created_at=created_at,
    )

    runner = command_runner or _run_probe_command
    host = _host_report(env=env_map)
    probes = _runtime_probes(env=env_map, command_runner=runner)
    disk = _disk_report(
        path=_disk_probe_path(repo_root=repo_root, alpasim_root=resolved_alpasim_root),
        repo_root=repo_root,
        min_free_disk_gb=min_free_disk_gb,
        disk_usage=disk_usage,
    )
    stages = [
        _stage_readiness(stage, repo_root=repo_root, hf_revision=hf_revision)
        for stage in plan["stages"]
    ]
    scale_stages = [stage for stage in stages if stage["requires_local_usdz_cache"]]
    all_scale_caches_valid = all(
        stage["local_usdz_cache"]["validation"]["valid"] for stage in scale_stages
    )
    docker_nvidia_runtime = probes["docker_nvidia_runtime"]["declares_nvidia_runtime"]
    closed_loop_runner_ready = all(
        (
            host["closed_loop_runner_supported"],
            probes["docker_daemon"]["ok"],
            probes["alpasim_base_image"]["ok"],
            probes["nvidia_smi"]["ok"],
            docker_nvidia_runtime is True,
            all_scale_caches_valid,
            disk["meets_min_free_disk_gb"],
        )
    )
    cache_build_ready = all(
        (
            bool(env_map.get("HF_TOKEN", "").strip()),
            disk["meets_min_free_disk_gb"],
            resolved_alpasim_root.is_dir(),
        )
    )
    blocking_requirements = _blocking_requirements(
        env=env_map,
        host=host,
        probes=probes,
        disk=disk,
        stages=stages,
    )

    return {
        "schema": READINESS_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "valid": True,
        "plan_artifact": PLAN_ARTIFACT,
        "status_artifact": STATUS_ARTIFACT,
        "no_download_or_rollout_probes": True,
        "alpasim_root": _display_path(resolved_alpasim_root, repo_root=repo_root),
        "host": host,
        "disk": disk,
        "credentials": {
            "hf_token_present": bool(env_map.get("HF_TOKEN", "").strip()),
            "hf_token_required_for_cache_build": True,
        },
        "runtime_probes": probes,
        "readiness": {
            "cache_build_ready": cache_build_ready,
            "closed_loop_runner_ready": closed_loop_runner_ready,
            "all_scale_caches_valid": all_scale_caches_valid,
            "claim_valid_scale_summaries_present": all(
                stage["public_summary"]["claim_valid"] for stage in scale_stages
            ),
        },
        "blocking_requirements": blocking_requirements,
        "next_command_groups": _next_command_groups(
            plan=plan,
            stages=stages,
            repo_root=repo_root,
        ),
        "stages": stages,
    }


def _resolve_alpasim_root(alpasim_root: Path | None, *, env: dict[str, str]) -> Path:
    if alpasim_root is not None:
        return alpasim_root.expanduser().resolve()
    env_root = env.get("ALPASIM_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path("workspace/alpasim").resolve()


def _host_report(*, env: dict[str, str]) -> dict[str, Any]:
    system = platform.system()
    machine = platform.machine()
    normalized_machine = machine.lower()
    is_arm = normalized_machine in {"aarch64", "arm64"}
    is_x86_64 = normalized_machine in {"x86_64", "amd64"}
    override_enabled = env.get("WAYSPAN_ALLOW_UNSUPPORTED_ALPASIM_ARM", "").strip() == "1"
    closed_loop_supported = system == "Linux" and is_x86_64
    notes: list[str] = []
    if is_arm and not override_enabled:
        notes.append("ARM hosts can build caches or run diagnostics, but live rollouts are blocked by default.")
    if override_enabled:
        notes.append("Unsupported ARM rollout override is enabled; this does not make the host claim-supported.")
    return {
        "system": system,
        "machine": machine,
        "python_version": platform.python_version(),
        "closed_loop_runner_supported": closed_loop_supported,
        "arm_host": is_arm,
        "unsupported_arm_rollout_override_enabled": override_enabled,
        "notes": notes,
    }


def _runtime_probes(
    *,
    env: dict[str, str],
    command_runner: Callable[[list[str]], dict[str, Any]],
) -> dict[str, Any]:
    image_tag = env.get("ALPASIM_BASE_IMAGE_TAG", "").strip() or "alpasim-base:0.66.0"
    docker_daemon = command_runner(["docker", "info", "--format", "{{.ServerVersion}}"])
    docker_nvidia_runtime_raw = command_runner(
        ["docker", "info", "--format", "{{range $name, $_ := .Runtimes}}{{println $name}}{{end}}"]
    )
    docker_runtime_names = _docker_runtime_names(docker_nvidia_runtime_raw)
    alpasim_base_image = command_runner(
        ["docker", "image", "inspect", image_tag, "--format", "{{.Id}}"]
    )
    nvidia_smi = _sanitize_nvidia_smi(command_runner(["nvidia-smi", "-L"]))
    return {
        "docker_daemon": docker_daemon,
        "docker_nvidia_runtime": {
            **docker_nvidia_runtime_raw,
            "stdout": "",
            "runtime_names": docker_runtime_names,
            "declares_nvidia_runtime": "nvidia" in docker_runtime_names
            if docker_runtime_names is not None
            else None,
        },
        "alpasim_base_image": {**alpasim_base_image, "image_tag": image_tag},
        "nvidia_smi": nvidia_smi,
    }


def _docker_runtime_names(report: dict[str, Any]) -> list[str] | None:
    if not report.get("ok"):
        return None
    stdout = str(report.get("stdout", ""))
    try:
        runtimes = json.loads(stdout)
    except json.JSONDecodeError:
        return sorted({part.strip().lower() for part in stdout.split() if part.strip()})
    if isinstance(runtimes, dict):
        return sorted({str(key).lower() for key in runtimes})
    return sorted({part.strip().lower() for part in stdout.split() if part.strip()})


def _sanitize_nvidia_smi(report: dict[str, Any]) -> dict[str, Any]:
    stdout = str(report.get("stdout", ""))
    sanitized_lines = [_GPU_UUID_RE.sub("(UUID: redacted)", line) for line in stdout.splitlines()]
    return {
        **report,
        "stdout": "\n".join(sanitized_lines[:8]),
        "gpu_count": len([line for line in sanitized_lines if line.strip()]),
    }


def _disk_probe_path(*, repo_root: Path, alpasim_root: Path) -> Path:
    if alpasim_root.exists():
        return alpasim_root
    return repo_root


def _disk_report(
    *,
    path: Path,
    repo_root: Path,
    min_free_disk_gb: int,
    disk_usage: Callable[[Path], Any],
) -> dict[str, Any]:
    usage = disk_usage(path)
    free_gib = _bytes_to_gib(int(usage.free))
    return {
        "path": _display_path(path, repo_root=repo_root),
        "free_bytes": int(usage.free),
        "free_gib": round(free_gib, 2),
        "total_gib": round(_bytes_to_gib(int(usage.total)), 2),
        "min_free_disk_gb": min_free_disk_gb,
        "meets_min_free_disk_gb": free_gib >= float(min_free_disk_gb),
    }


def _stage_readiness(
    stage: dict[str, Any],
    *,
    repo_root: Path,
    hf_revision: str,
) -> dict[str, Any]:
    scene_preset = str(stage["scene_preset"])
    scene_count = int(stage["scene_count"])
    requires_cache = bool(stage["requires_local_usdz_cache"])
    local_cache = _local_cache_status(stage=stage, hf_revision=hf_revision, repo_root=repo_root)
    public_summary = _public_summary_status(
        repo_root / str(stage["public_summary_target"]),
        repo_root=repo_root,
        expected_scene_count=scene_count,
    )
    return {
        "stage": stage["stage"],
        "scene_preset": scene_preset,
        "scene_count": scene_count,
        "requires_local_usdz_cache": requires_cache,
        "local_usdz_cache": local_cache,
        "public_summary": public_summary,
        "run_dir": stage["run_dir"],
        "public_summary_target": stage["public_summary_target"],
    }


def _blocking_requirements(
    *,
    env: dict[str, str],
    host: dict[str, Any],
    probes: dict[str, Any],
    disk: dict[str, Any],
    stages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    if not env.get("HF_TOKEN", "").strip():
        requirements.append(
            {
                "id": "hf_token_missing",
                "blocks": "scale_cache_build",
                "detail": "HF_TOKEN is required before running scale-stage build_local_cache commands.",
                "plan_command_groups": ["stages[].commands.build_local_cache"],
            }
        )
    if not disk["meets_min_free_disk_gb"]:
        requirements.append(
            {
                "id": "free_disk_below_threshold",
                "blocks": "cache_build_and_rollout",
                "detail": (
                    f"{disk['free_gib']} GiB free is below the configured "
                    f"{disk['min_free_disk_gb']} GB threshold."
                ),
                "plan_command_groups": ["commands.check_readiness"],
            }
        )
    if not host["closed_loop_runner_supported"]:
        requirements.append(
            {
                "id": "unsupported_closed_loop_host",
                "blocks": "closed_loop_rollout",
                "detail": "Live rollouts require a supported x86_64 Linux AlpaSim runner.",
                "plan_command_groups": ["stages[].commands.run_batch"],
            }
        )
    _append_probe_requirement(
        requirements,
        probe=probes["docker_daemon"],
        requirement_id="docker_daemon_unavailable",
        blocks="closed_loop_rollout",
        plan_command_groups=["commands.check_readiness", "stages[].commands.run_batch"],
    )
    _append_probe_requirement(
        requirements,
        probe=probes["alpasim_base_image"],
        requirement_id="alpasim_base_image_missing",
        blocks="closed_loop_rollout",
        plan_command_groups=["stages[].commands.run_batch"],
    )
    _append_probe_requirement(
        requirements,
        probe=probes["nvidia_smi"],
        requirement_id="nvidia_gpu_unavailable",
        blocks="closed_loop_rollout",
        plan_command_groups=["stages[].commands.run_batch"],
    )
    if probes["docker_nvidia_runtime"].get("declares_nvidia_runtime") is not True:
        requirements.append(
            {
                "id": "docker_nvidia_runtime_unavailable",
                "blocks": "closed_loop_rollout",
                "detail": "Docker does not currently report an NVIDIA runtime.",
                "plan_command_groups": ["commands.check_readiness", "stages[].commands.run_batch"],
            }
        )

    for stage in stages:
        if not stage["requires_local_usdz_cache"]:
            continue
        cache_validation = stage["local_usdz_cache"]["validation"]
        if not cache_validation["valid"]:
            requirements.append(
                {
                    "id": f"{stage['scene_preset']}_cache_invalid",
                    "stage": stage["stage"],
                    "scene_preset": stage["scene_preset"],
                    "blocks": "closed_loop_rollout",
                    "detail": (
                        f"Local USDZ cache is not valid: "
                        f"{cache_validation.get('present_scene_count', 0)}/"
                        f"{cache_validation.get('expected_scene_count', stage['scene_count'])} scenes present."
                    ),
                    "plan_command_groups": [
                        f"stages[{stage['stage']}].commands.build_local_cache",
                        f"stages[{stage['stage']}].commands.validate_local_cache",
                    ],
                }
            )
        if not stage["public_summary"]["claim_valid"]:
            requirements.append(
                {
                    "id": f"{stage['scene_preset']}_claim_summary_missing",
                    "stage": stage["stage"],
                    "scene_preset": stage["scene_preset"],
                    "blocks": "full_benchmark_claim",
                    "detail": f"Claim-valid public summary is not present: {stage['public_summary_target']}.",
                    "plan_command_groups": [
                        f"stages[{stage['stage']}].commands.run_batch",
                        f"stages[{stage['stage']}].commands.write_batch_summary",
                        f"stages[{stage['stage']}].commands.merge_shard_summaries",
                        f"stages[{stage['stage']}].commands.promote_public_summary",
                    ],
                }
            )
    return requirements


def _append_probe_requirement(
    requirements: list[dict[str, Any]],
    *,
    probe: dict[str, Any],
    requirement_id: str,
    blocks: str,
    plan_command_groups: list[str],
) -> None:
    if probe.get("ok") is True:
        return
    stderr = str(probe.get("stderr", "") or "").strip()
    status = str(probe.get("status", "") or "failed")
    detail = stderr or f"Probe status: {status}"
    requirements.append(
        {
            "id": requirement_id,
            "blocks": blocks,
            "detail": detail,
            "plan_command_groups": plan_command_groups,
        }
    )


def _next_command_groups(
    *,
    plan: dict[str, Any],
    stages: list[dict[str, Any]],
    repo_root: Path,
) -> list[dict[str, Any]]:
    check_readiness = _dict_or_empty(_dict_or_empty(plan.get("commands")).get("check_readiness"))
    groups: list[dict[str, Any]] = [
        {
            "order": 1,
            "name": "refresh_readiness",
            "plan_command_group": "commands.check_readiness",
            "commands": _resolved_command_rows(
                stage=None,
                scene_preset=None,
                command_name="check_readiness",
                command=check_readiness,
                repo_root=repo_root,
            ),
        }
    ]
    scale_stages = [stage for stage in stages if stage["requires_local_usdz_cache"]]
    plan_stages_by_stage = {
        str(stage.get("stage") or ""): stage
        for stage in _list_or_empty(plan.get("stages"))
        if isinstance(stage, dict)
    }
    if any(not stage["local_usdz_cache"]["validation"]["valid"] for stage in scale_stages):
        cache_commands: list[dict[str, Any]] = []
        for stage in scale_stages:
            if stage["local_usdz_cache"]["validation"]["valid"]:
                continue
            plan_stage = _dict_or_empty(plan_stages_by_stage.get(str(stage["stage"])))
            commands = _dict_or_empty(plan_stage.get("commands"))
            for command_name in ("build_local_cache", "validate_local_cache"):
                cache_commands.extend(
                    _resolved_command_rows(
                        stage=str(stage["stage"]),
                        scene_preset=str(stage["scene_preset"]),
                        command_name=command_name,
                        command=_dict_or_empty(commands.get(command_name)),
                        repo_root=repo_root,
                    )
                )
        groups.append(
            {
                "order": len(groups) + 1,
                "name": "build_and_validate_scale_caches",
                "plan_command_groups": [
                    f"stages[{stage['stage']}].commands.build_local_cache"
                    for stage in scale_stages
                    if not stage["local_usdz_cache"]["validation"]["valid"]
                ]
                + [
                    f"stages[{stage['stage']}].commands.validate_local_cache"
                    for stage in scale_stages
                    if not stage["local_usdz_cache"]["validation"]["valid"]
                ],
                "commands": cache_commands,
            }
        )
    if any(not stage["public_summary"]["claim_valid"] for stage in scale_stages):
        missing_summary_stages = [
            stage for stage in scale_stages if not stage["public_summary"]["claim_valid"]
        ]
        groups.append(
            {
                "order": len(groups) + 1,
                "name": "run_scale_shards_and_promote_summaries",
                "plan_command_groups": [
                    "stages[].shards[].commands.run_batch",
                    "stages[].shards[].commands.write_batch_summary",
                    "stages[].commands.merge_shard_summaries",
                    "stages[].commands.promote_public_summary",
                ],
                "stage_command_counts": [
                    _stage_command_count(
                        stage=stage,
                        plan_stage=plan_stages_by_stage[str(stage["stage"])],
                    )
                    for stage in missing_summary_stages
                    if str(stage["stage"]) in plan_stages_by_stage
                ],
            }
        )
    groups.append(
        {
            "order": len(groups) + 1,
            "name": "refresh_status",
            "command": (
                "wod2sim-benchmark-status "
                "--output docs/evidence/benchmark_regeneration_status_20260706.json --json"
            ),
            "expected_before_scale_completion": "records_missing_50_100_summaries_until_scale_completion",
        }
    )
    groups.append(
        {
            "order": len(groups) + 1,
            "name": "verify_claim_gate",
            "command": "wod2sim-benchmark-audit --strict --json",
            "expected_before_scale_completion": "exit_1_until_50_100_summaries_are_claim_valid",
        }
    )
    return groups


def _stage_command_count(
    *,
    stage: dict[str, Any],
    plan_stage: dict[str, Any],
) -> dict[str, Any]:
    planned_shards = len(_list_or_empty(plan_stage.get("shards")))
    return {
        "stage": stage["stage"],
        "scene_preset": stage["scene_preset"],
        "planned_shards": planned_shards,
        "minimum_commands": planned_shards * 2 + 2,
    }


def _resolved_command_rows(
    *,
    stage: str | None,
    scene_preset: str | None,
    command_name: str,
    command: dict[str, Any],
    repo_root: Path,
) -> list[dict[str, Any]]:
    display = _sanitize_display_command(str(command.get("display") or "").strip(), repo_root=repo_root)
    if not display:
        return []
    row: dict[str, Any] = {
        "command": command_name,
        "display": display,
    }
    if stage is not None:
        row["stage"] = stage
    if scene_preset is not None:
        row["scene_preset"] = scene_preset
    return [row]


def _sanitize_display_command(display: str, *, repo_root: Path) -> str:
    root_prefix = str(repo_root.resolve()).rstrip("/") + "/"
    return display.replace(root_prefix, "")


def _local_cache_status(
    *,
    stage: dict[str, Any],
    hf_revision: str,
    repo_root: Path,
) -> dict[str, Any]:
    if not stage["requires_local_usdz_cache"]:
        return {
            "required": False,
            "local_usdz_dir": None,
            "validation": {"valid": True, "status": "not_required"},
        }
    local_usdz_dir = Path(str(stage["local_usdz_dir"]))
    validation = validate_local_usdz_cache(
        scene_preset=str(stage["scene_preset"]),
        scene_ids=[str(scene_id) for scene_id in stage.get("scene_ids", [])] or _stage_scene_ids(stage),
        local_usdz_dir=local_usdz_dir,
        hf_revision=hf_revision,
    )
    return {
        "required": True,
        "local_usdz_dir": _display_path(local_usdz_dir, repo_root=repo_root),
        "usdz_file_count": len(list(local_usdz_dir.glob("*.usdz"))) if local_usdz_dir.is_dir() else 0,
        "validation": _compact_cache_validation(validation),
    }


def _stage_scene_ids(stage: dict[str, Any]) -> list[str]:
    from wod2sim.cli.commands.run_alpasim_local_external import _scene_ids

    return _scene_ids(str(stage["scene_preset"]), [])


def _compact_cache_validation(validation: dict[str, Any]) -> dict[str, Any]:
    missing_scene_ids = [str(item) for item in validation.get("missing_scene_ids", [])]
    invalid_revision_scene_ids = [
        str(item) for item in validation.get("invalid_revision_scene_ids", [])
    ]
    invalid_cache_files = [
        item for item in validation.get("invalid_cache_files", []) if isinstance(item, dict)
    ]
    duplicate_uuids = [str(item) for item in validation.get("duplicate_uuids", [])]
    return {
        "schema": validation["schema"],
        "valid": bool(validation["valid"]),
        "expected_scene_count": int(validation["expected_scene_count"]),
        "present_scene_count": int(validation["present_scene_count"]),
        "missing_scene_count": len(missing_scene_ids),
        "missing_scene_ids_sample": missing_scene_ids[:10],
        "invalid_revision_scene_count": len(invalid_revision_scene_ids),
        "invalid_revision_scene_ids_sample": invalid_revision_scene_ids[:10],
        "invalid_cache_file_count": len(invalid_cache_files),
        "invalid_cache_files_sample": invalid_cache_files[:5],
        "duplicate_uuid_count": len(duplicate_uuids),
        "duplicate_uuids_sample": duplicate_uuids[:10],
    }


def _public_summary_status(
    path: Path,
    *,
    repo_root: Path,
    expected_scene_count: int,
) -> dict[str, Any]:
    display_path = _display_path(path, repo_root=repo_root)
    if not path.is_file():
        return {
            "present": False,
            "claim_valid": False,
            "path": display_path,
            "errors": ["summary_missing"],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "present": True,
            "claim_valid": False,
            "path": display_path,
            "errors": [f"summary_invalid_json:{exc}"],
        }
    aggregate = payload.get("aggregate") if isinstance(payload, dict) else {}
    aggregate = aggregate if isinstance(aggregate, dict) else {}
    errors: list[str] = []
    if payload.get("schema") != "wod2sim_closed_loop_batch_summary_v1":
        errors.append("summary_schema_mismatch")
    if payload.get("clean_closed_loop_batch") is not True:
        errors.append("clean_closed_loop_batch_not_true")
    if _int_value(aggregate.get("planned_scene_count")) != expected_scene_count:
        errors.append("planned_scene_count_mismatch")
    if _int_value(aggregate.get("completed_scene_count")) != expected_scene_count:
        errors.append("completed_scene_count_mismatch")
    if _int_value(aggregate.get("failed_scene_count")) != 0:
        errors.append("failed_scene_count_nonzero")
    if _int_value(aggregate.get("sensor_failure_scene_count")) != 0:
        errors.append("sensor_failure_scene_count_nonzero")
    return {
        "present": True,
        "claim_valid": not errors,
        "path": display_path,
        "errors": errors,
        "observed": {
            "schema": payload.get("schema"),
            "clean_closed_loop_batch": payload.get("clean_closed_loop_batch"),
            "planned_scene_count": _optional_int(aggregate.get("planned_scene_count")),
            "completed_scene_count": _optional_int(aggregate.get("completed_scene_count")),
            "failed_scene_count": _optional_int(aggregate.get("failed_scene_count")),
            "sensor_failure_scene_count": _optional_int(aggregate.get("sensor_failure_scene_count")),
        },
    }


def _run_probe_command(argv: list[str]) -> dict[str, Any]:
    if shutil.which(argv[0]) is None:
        return {
            "ok": False,
            "status": "missing_executable",
            "argv": argv,
            "returncode": None,
            "stdout": "",
            "stderr": f"{argv[0]} not found on PATH",
        }
    try:
        result = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=8,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "status": "timeout",
            "argv": argv,
            "returncode": None,
            "stdout": _truncate(_decode_output(exc.stdout)),
            "stderr": _truncate(_decode_output(exc.stderr)),
        }
    return {
        "ok": result.returncode == 0,
        "status": "ok" if result.returncode == 0 else "failed",
        "argv": argv,
        "returncode": result.returncode,
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
    }


def _decode_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _truncate(value: str, *, limit: int = 500) -> str:
    stripped = value.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "...[truncated]"


def _int_value(value: object) -> int:
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
            return 0
    return 0


def _list_or_empty(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _int_value(value)


def _display_path(path: Path, *, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _bytes_to_gib(value: int) -> float:
    return value / (1024**3)


def _print_human_summary(report: dict[str, Any]) -> None:
    readiness = report["readiness"]
    print(f"{report['schema']}:")
    print(f"  cache_build_ready={readiness['cache_build_ready']}")
    print(f"  closed_loop_runner_ready={readiness['closed_loop_runner_ready']}")
    print(f"  all_scale_caches_valid={readiness['all_scale_caches_valid']}")
    for stage in report["stages"]:
        summary = stage["public_summary"]
        cache = stage["local_usdz_cache"]["validation"]
        print(
            f"- {stage['scene_preset']}: summary_present={summary['present']} "
            f"summary_claim_valid={summary['claim_valid']} cache_valid={cache['valid']}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
