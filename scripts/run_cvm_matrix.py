from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import os
import signal
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from alpabridge.audit.trace_diagnostics import (
    diagnose_contract_trace,
    load_telemetry_trace,
    mutate_trace,
)
from alpabridge.simulator.lifecycle_service import run_synthetic_lifecycle_cycle

RUN_FIELDS = [
    "run_id",
    "matrix",
    "policy",
    "scene_id",
    "seed",
    "adapter_config",
    "status",
    "attempted",
    "completed",
    "blocked",
    "failure_layer",
    "failure_code",
    "detail",
    "claim_valid",
    "expected_layer",
    "observed_layer",
    "expected_code",
    "observed_code",
    "detected",
    "correctly_localized",
    "service_survived",
    "late_message_count",
]
SCENE_METADATA_FIELDS = (
    "scene_id",
    "category",
    "selection_rationale",
    "asset_availability",
    "expected_route_feature",
    "expected_interaction_feature",
    "license_gating_status",
)

FAULT_SERVICE_SURVIVAL = {
    "deployment.docker_unavailable": "false",
    "deployment.gpu_runtime_unavailable": "false",
    "deployment.scene_artifact_missing": "false",
}
REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Expand and record the contract-validation matrix."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Launch real closed-loop runs when all preconditions are satisfied. Not enabled by Make targets.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help=(
            "Python executable to record/use in generated closed-loop launch commands. "
            "Paths inside this repository are stored relative to the repository root."
        ),
    )
    parser.add_argument(
        "--refresh-manifests",
        action="store_true",
        help="Rewrite preserved run manifests with current schema/provenance without relaunching rows.",
    )
    args = parser.parse_args()

    config = _load_yaml(args.config)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    repository_state = _repository_state()

    rows = _expand_rows(config)
    existing_rows = _load_existing_rows(output) if args.resume else {}
    preserved_manifest_run_ids: set[str] = set()
    global_blockers = _global_precondition_blockers(config)
    if global_blockers:
        next_rows = []
        for row in rows:
            preserved = _resume_preserved_row(
                existing_rows,
                row,
                execute=args.execute,
                execution_mode=_execution_mode(config),
                output=output,
            )
            if preserved is not None:
                next_rows.append(preserved)
                preserved_manifest_run_ids.add(row["run_id"])
            else:
                next_rows.append(_blocked_row(row, global_blockers[0]))
        rows = next_rows
    else:
        next_rows = []
        mode = _execution_mode(config)
        for row in rows:
            preserved = _resume_preserved_row(
                existing_rows,
                row,
                execute=args.execute,
                execution_mode=mode,
                output=output,
            )
            if preserved is not None:
                next_rows.append(preserved)
                preserved_manifest_run_ids.add(row["run_id"])
                continue
            row_blocker = _row_precondition_blocker(config, row, execute=args.execute)
            if row_blocker is not None:
                next_rows.append(_blocked_row(row, row_blocker))
            elif not args.execute:
                next_rows.append(_planned_row(row))
            elif mode in {"synthetic_fault_injection", "synthetic_lifecycle_harness"}:
                next_rows.append(_execute_synthetic_row(config, row))
            elif mode.startswith("closed_loop"):
                next_rows.append(
                    _execute_closed_loop_row(
                        config,
                        row,
                        output=output,
                        python_executable=args.python,
                    )
                )
            else:
                next_rows.append(
                    _blocked_row(
                        row,
                        {
                            "layer": "deployment",
                            "code": "cvm_closed_loop_launch_not_implemented",
                            "detail": (
                                "Runner scaffolding is present, but per-run launch orchestration "
                                "still needs implementation."
                            ),
                        },
                    )
                )
        rows = next_rows
    for row in rows:
        if row["run_id"] in preserved_manifest_run_ids:
            manifest_path = _run_manifest_dir(output) / f"{_safe_filename(row['run_id'])}.json"
            if manifest_path.is_file() and not args.refresh_manifests:
                continue
        _write_run_manifest(
            _run_manifest_dir(output),
            row=row,
            config=config,
            config_path=args.config,
            python_executable=args.python,
            output=output,
            repository_state=repository_state,
        )
    exit_code = 0 if all(row["status"] == "completed" for row in rows) else 2

    _write_csv(output / "runs.csv", rows, RUN_FIELDS)
    _write_csv(
        output / "failures.csv",
        [row for row in rows if row["status"] != "completed"],
        RUN_FIELDS,
    )
    manifest_dir = _run_manifest_dir(output)
    summary = _summary(
        config=config,
        rows=rows,
        blockers=global_blockers,
        config_path=args.config,
        created_at=_summary_created_at(manifest_dir, rows),
    )
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    _write_csv(
        output / "summary.csv",
        [
            {
                "matrix": summary["matrix"],
                "expected_runs": summary["expected_runs"],
                "rows": summary["rows"],
                "planned": summary["planned"],
                "attempted": summary["attempted"],
                "completed": summary["completed"],
                "failed": summary["failed"],
                "blocked": summary["blocked"],
                "claim_valid": summary["claim_valid"],
            }
        ],
        [
            "matrix",
            "expected_runs",
            "rows",
            "planned",
            "attempted",
            "completed",
            "failed",
            "blocked",
            "claim_valid",
        ],
    )
    if config.get("name") == "fault_injection":
        _write_fault_injection(output / "fault_injection.csv", config, rows=rows)
    if config.get("name") == "lifecycle_stress":
        _write_lifecycle_stress(output / "lifecycle_stress.csv", rows)
    print(
        json.dumps(
            {
                "matrix": summary["matrix"],
                "rows": summary["rows"],
                "planned": summary["planned"],
                "attempted": summary["attempted"],
                "completed": summary["completed"],
                "blocked": summary["blocked"],
                "claim_valid": summary["claim_valid"],
                "summary": str(output / "summary.json"),
            },
            sort_keys=True,
        )
    )
    return exit_code


def _load_existing_rows(output: Path) -> dict[str, dict[str, str]]:
    path = output / "runs.csv"
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = {
            row.get("run_id", ""): row
            for row in csv.DictReader(handle)
            if row.get("run_id")
        }
    return rows


def _resume_preserved_row(
    existing_rows: dict[str, dict[str, str]],
    row: dict[str, str],
    *,
    execute: bool,
    execution_mode: str = "",
    output: Path | None = None,
) -> dict[str, str] | None:
    existing = existing_rows.get(row["run_id"])
    if existing is None:
        return None
    status = existing.get("status", "")
    if status == "completed" and existing.get("completed") == "true":
        if execute and execution_mode == "synthetic_fault_injection":
            return None
        if execution_mode.startswith("closed_loop"):
            if output is None:
                return None
            run_status = _load_json_dict(_run_output_dir(output, row) / "run-status.json")
            if not (
                run_status.get("state") == "completed"
                and run_status.get("aggregate_status") == "completed"
            ):
                return None
        return _normalized_existing_row(existing, row)
    if not execute and status in {"failed", "blocked"}:
        return _normalized_existing_row(existing, row)
    return None


def _normalized_existing_row(existing: dict[str, str], row: dict[str, str]) -> dict[str, str]:
    normalized = {field: existing.get(field, row.get(field, "")) for field in RUN_FIELDS}
    for field in ("run_id", "matrix", "policy", "scene_id", "seed", "adapter_config"):
        normalized[field] = row[field]
    return normalized


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"Config is not a YAML mapping: {path}")
    return payload


def _expand_rows(config: dict[str, Any]) -> list[dict[str, str]]:
    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    mode = str(execution.get("mode", ""))
    if mode == "synthetic_lifecycle_harness":
        return _expand_lifecycle_rows(config, execution)
    if mode == "synthetic_fault_injection":
        return _expand_fault_rows(config)

    scenes = _scenes(config)
    scene_limit = execution.get("scene_limit")
    if isinstance(scene_limit, int):
        scenes = scenes[:scene_limit]
    policies = [str(item) for item in config.get("policies", [])]
    seeds = [str(item) for item in config.get("seeds", [])]
    adapters = [str(item) for item in config.get("adapter_configs", [])]
    rows: list[dict[str, str]] = []
    for policy, scene_id, seed, adapter in itertools.product(policies, scenes, seeds, adapters):
        run_id = f"{config.get('name')}_{policy}_{scene_id}_{seed}_{adapter}"
        rows.append(
            {
                "run_id": run_id,
                "matrix": str(config.get("name", "")),
                "policy": policy,
                "scene_id": scene_id,
                "seed": seed,
                "adapter_config": adapter,
                "status": "planned",
                "attempted": "false",
                "completed": "false",
                "blocked": "false",
                "failure_layer": "",
                "failure_code": "",
                "detail": "",
                "claim_valid": "false",
                "expected_layer": "",
                "observed_layer": "",
                "expected_code": "",
                "observed_code": "",
                "detected": "",
                "correctly_localized": "",
                "service_survived": "",
                "late_message_count": "",
            }
        )
    return rows


def _expand_lifecycle_rows(config: dict[str, Any], execution: dict[str, Any]) -> list[dict[str, str]]:
    policies = [str(item) for item in config.get("policies", [])]
    seeds = [str(item) for item in config.get("seeds", [])]
    adapters = [str(item) for item in config.get("adapter_configs", [])]
    cycles = int(execution.get("cycles_per_config", 0))
    rows: list[dict[str, str]] = []
    for policy, seed, adapter, cycle in itertools.product(
        policies, seeds, adapters, range(1, cycles + 1)
    ):
        run_id = f"{config.get('name')}_{policy}_{seed}_{adapter}_cycle{cycle:02d}"
        rows.append(
            {
                "run_id": run_id,
                "matrix": str(config.get("name", "")),
                "policy": policy,
                "scene_id": "synthetic_lifecycle_harness",
                "seed": seed,
                "adapter_config": adapter,
                "status": "planned",
                "attempted": "false",
                "completed": "false",
                "blocked": "false",
                "failure_layer": "",
                "failure_code": "",
                "detail": "",
                "claim_valid": "false",
                "expected_layer": "",
                "observed_layer": "",
                "expected_code": "",
                "observed_code": "",
                "detected": "",
                "correctly_localized": "",
                "service_survived": "",
                "late_message_count": "",
            }
        )
    return rows


def _expand_fault_rows(config: dict[str, Any]) -> list[dict[str, str]]:
    policies = [str(item) for item in config.get("policies", [])]
    seeds = [str(item) for item in config.get("seeds", [])]
    faults = [str(item) for item in config.get("faults", [])]
    rows: list[dict[str, str]] = []
    for policy, seed, fault in itertools.product(policies, seeds, faults):
        run_id = f"{config.get('name')}_{policy}_{seed}_{fault.replace('.', '_')}"
        rows.append(
            {
                "run_id": run_id,
                "matrix": str(config.get("name", "")),
                "policy": policy,
                "scene_id": "synthetic_fault_harness",
                "seed": seed,
                "adapter_config": fault,
                "status": "planned",
                "attempted": "false",
                "completed": "false",
                "blocked": "false",
                "failure_layer": "",
                "failure_code": "",
                "detail": "",
                "claim_valid": "false",
                "expected_layer": "",
                "observed_layer": "",
                "expected_code": "",
                "observed_code": "",
                "detected": "",
                "correctly_localized": "",
                "service_survived": "",
                "late_message_count": "",
            }
        )
    return rows


def _scenes(config: dict[str, Any]) -> list[str]:
    manifest_path = Path(str(config.get("scene_manifest", "")))
    if not manifest_path.is_file():
        raise SystemExit(f"Missing scene manifest: {manifest_path}")
    manifest = _load_yaml(manifest_path)
    scenes = manifest.get("scenes", [])
    if not isinstance(scenes, list):
        raise SystemExit(f"Scene manifest has invalid scenes list: {manifest_path}")
    scene_ids = [str(item.get("scene_id", "")).strip() for item in scenes if isinstance(item, dict)]
    scene_ids = [scene_id for scene_id in scene_ids if scene_id]
    if not scene_ids:
        raise SystemExit(f"Scene manifest has no scene IDs: {manifest_path}")
    return scene_ids


def _scene_metadata(config: dict[str, Any], row: dict[str, str]) -> dict[str, str | bool]:
    scene_id = row.get("scene_id", "")
    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    mode = str(execution.get("mode", ""))
    if scene_id.startswith("synthetic_") or mode.startswith("synthetic_"):
        return {
            "scene_id": scene_id,
            "category": scene_id or "synthetic_harness",
            "scenario_category": scene_id or "synthetic_harness",
            "selection_rationale": "public deterministic service harness",
            "asset_availability": "public_synthetic",
            "expected_route_feature": "not_applicable",
            "expected_interaction_feature": "not_applicable",
            "license_gating_status": "public_synthetic",
            "categories_verified": True,
            "source_manifest": "",
        }

    manifest_path = Path(str(config.get("scene_manifest", "")))
    if not manifest_path.is_file():
        source_manifest = str(manifest_path) if str(manifest_path) != "." else ""
        return {
            "scene_id": scene_id,
            "category": "scene_metadata_unavailable",
            "scenario_category": "scene_metadata_unavailable",
            "selection_rationale": "scene manifest not configured or unavailable",
            "asset_availability": "unknown",
            "expected_route_feature": "unknown",
            "expected_interaction_feature": "unknown",
            "license_gating_status": "unknown",
            "categories_verified": False,
            "source_manifest": source_manifest,
        }

    manifest = _load_yaml(manifest_path)
    scenes = manifest.get("scenes", [])
    if isinstance(scenes, list):
        for item in scenes:
            if not isinstance(item, dict):
                continue
            if str(item.get("scene_id", "")).strip() != scene_id:
                continue
            metadata = {
                field: str(item.get(field, "")).strip()
                for field in SCENE_METADATA_FIELDS
            }
            category = metadata.get("category") or "unclassified"
            metadata["category"] = category
            metadata["scenario_category"] = category
            metadata["source_manifest"] = str(manifest_path)
            source = manifest.get("source", {})
            metadata["categories_verified"] = (
                bool(source.get("categories_verified", False))
                if isinstance(source, dict)
                else False
            )
            return metadata

    return {
        "scene_id": scene_id,
        "category": "scene_not_listed_in_manifest",
        "scenario_category": "scene_not_listed_in_manifest",
        "selection_rationale": "row scene ID was not present in the configured scene manifest",
        "asset_availability": "unknown",
        "expected_route_feature": "unknown",
        "expected_interaction_feature": "unknown",
        "license_gating_status": "unknown",
        "categories_verified": False,
        "source_manifest": str(manifest_path),
    }


def _global_precondition_blockers(config: dict[str, Any]) -> list[dict[str, str]]:
    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    blockers: list[dict[str, str]] = []
    mode = str(execution.get("mode", ""))
    if mode.startswith("closed_loop"):
        image = str(execution.get("required_docker_image", "")).strip()
        if image and _docker_image_missing(image):
            blockers.append(
                {
                    "layer": "deployment",
                    "code": "docker_image_missing",
                    "detail": f"Required Docker image not found: {image}",
                }
            )
        alpasim_root = Path(str(execution.get("alpasim_root", "")))
        if not alpasim_root.exists():
            blockers.append(
                {
                    "layer": "deployment",
                    "code": "alpasim_root_missing",
                    "detail": f"AlpaSim root does not exist: {alpasim_root}",
                }
            )
        local_usdz_dir = Path(str(execution.get("local_usdz_dir", "")))
        if not local_usdz_dir.is_dir():
            blockers.append(
                {
                    "layer": "deployment",
                    "code": "local_usdz_dir_missing",
                    "detail": f"Local USDZ cache does not exist: {local_usdz_dir}",
                }
            )
    return blockers


def _row_precondition_blocker(
    config: dict[str, Any], row: dict[str, str], *, execute: bool
) -> dict[str, str] | None:
    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    policy = row["policy"]
    if policy == "direct_actor_planner" and not execution.get("direct_actor_oracle_proxy"):
        return {
            "layer": "deployment",
            "code": "direct_actor_oracle_proxy_missing",
            "detail": "direct_actor_planner requires a recorded oracle actor-proxy JSON.",
        }
    if policy == "token_dagger_bc" and not execution.get("token_checkpoint"):
        return {
            "layer": "deployment",
            "code": "token_checkpoint_missing",
            "detail": "token_dagger_bc requires a legitimate local checkpoint hash.",
        }
    return _adapter_execution_blocker(config, row)


def _adapter_execution_blocker(
    config: dict[str, Any], row: dict[str, str]
) -> dict[str, str] | None:
    mode = _execution_mode(config)
    if not mode.startswith("closed_loop"):
        return None
    adapter = row["adapter_config"]
    if adapter in {"full_contract", "full_temporal_contract"}:
        return None
    if adapter == "command_only_route":
        if row.get("policy") == "route_following":
            return None
        return {
            "layer": "semantic",
            "code": "semantic_ablation_policy_not_supported",
            "detail": (
                "The command-only route ablation is currently implemented for the "
                "route_following baseline only."
            ),
        }
    if adapter == "naive_or_disabled_resampling":
        return {
            "layer": "temporal",
            "code": "temporal_ablation_runtime_flag_missing",
            "detail": (
                "The naive/disabled-resampling ablation is configured but no runtime-safe "
                "adapter flag currently switches the launcher into that ablated behavior."
            ),
        }
    return {
        "layer": "deployment",
        "code": "adapter_config_not_executable",
        "detail": f"No closed-loop launch mapping exists for adapter_config={adapter}.",
    }


def _docker_image_missing(image: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return True
    return result.returncode != 0


def _blocked_row(row: dict[str, str], reason: dict[str, str]) -> dict[str, str]:
    row = dict(row)
    row.update(
        {
            "status": "blocked",
            "attempted": "false",
            "completed": "false",
            "blocked": "true",
            "failure_layer": reason["layer"],
            "failure_code": reason["code"],
            "detail": reason["detail"],
            "claim_valid": "false",
        }
    )
    return row


def _planned_row(row: dict[str, str]) -> dict[str, str]:
    planned = dict(row)
    planned.update(
        {
            "status": "planned",
            "attempted": "false",
            "completed": "false",
            "blocked": "false",
            "failure_layer": "",
            "failure_code": "",
            "detail": (
                "Matrix row was expanded and recorded only; pass --execute for real rollout launch."
            ),
            "claim_valid": "false",
        }
    )
    return planned


def _execution_mode(config: dict[str, Any]) -> str:
    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    return str(execution.get("mode", ""))


def _execute_synthetic_row(config: dict[str, Any], row: dict[str, str]) -> dict[str, str]:
    mode = _execution_mode(config)
    if mode == "synthetic_fault_injection":
        return _execute_fault_row(config, row)
    if mode == "synthetic_lifecycle_harness":
        return _execute_lifecycle_row(config, row)
    raise SystemExit(f"Unsupported synthetic execution mode: {mode}")


def _execute_closed_loop_row(
    config: dict[str, Any],
    row: dict[str, str],
    *,
    output: Path,
    python_executable: str,
) -> dict[str, str]:
    plan = _closed_loop_launch_plan(
        config=config,
        row=row,
        output=output,
        python_executable=python_executable,
    )
    if plan is None or not plan["supported"]:
        reason = _unsupported_launch_reason(plan)
        return _blocked_row(row, reason)
    existing_status = _load_json_dict(_repo_path(plan["run_status"]))
    if (
        existing_status.get("state") == "completed"
        and existing_status.get("aggregate_status") == "completed"
    ):
        resumed = dict(row)
        resumed.update(
            {
                "status": "completed",
                "attempted": "true",
                "completed": "true",
                "blocked": "false",
                "failure_layer": "",
                "failure_code": "",
                "detail": "Closed-loop launch already completed; reused by --resume.",
                "claim_valid": "false",
            }
        )
        return resumed

    stdout_path = _repo_path(plan["logs"]["stdout"])
    stderr_path = _repo_path(plan["logs"]["stderr"])
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    timeout_seconds = int(execution.get("timeout_seconds", 900))
    started_at = datetime.now(timezone.utc).isoformat()
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr:
        process = subprocess.Popen(
            plan["command"],
            cwd=REPO_ROOT,
            stdout=stdout,
            stderr=stderr,
            text=True,
            start_new_session=True,
        )
        timed_out = False
        try:
            process.wait(timeout=timeout_seconds + 60)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_group(process)
        else:
            result_returncode = int(process.returncode)

    if timed_out:
        return _failed_row(
            row,
            layer="runtime",
            code="closed_loop_launch_timeout",
            detail=(
                f"Closed-loop launch exceeded timeout_seconds={timeout_seconds}; "
                f"stdout={plan['logs']['stdout']}; stderr={plan['logs']['stderr']}."
            ),
            started_at=started_at,
        )

    if result_returncode != 0:
        return _failed_row(
            row,
            layer="runtime",
            code="closed_loop_launch_failed",
            detail=(
                f"Closed-loop launch exited {result_returncode}; "
                f"stdout={plan['logs']['stdout']}; stderr={plan['logs']['stderr']}."
            ),
            started_at=started_at,
        )

    run_status = _load_json_dict(_repo_path(plan["run_status"]))
    aggregate_status = str(run_status.get("aggregate_status", "missing"))
    if aggregate_status != "completed":
        return _failed_row(
            row,
            layer="evidence",
            code="closed_loop_artifacts_incomplete",
            detail=(
                "Closed-loop launcher returned zero, but aggregate evidence is not complete "
                f"(aggregate_status={aggregate_status})."
            ),
            started_at=started_at,
        )

    row = dict(row)
    row.update(
        {
            "status": "completed",
            "attempted": "true",
            "completed": "true",
            "blocked": "false",
            "failure_layer": "",
            "failure_code": "",
            "detail": "Closed-loop launch completed; claim validity remains gated by audit aggregation.",
            "claim_valid": "false",
        }
    )
    return row


def _failed_row(
    row: dict[str, str], *, layer: str, code: str, detail: str, started_at: str
) -> dict[str, str]:
    failed = dict(row)
    failed.update(
        {
            "status": "failed",
            "attempted": "true",
            "completed": "false",
            "blocked": "false",
            "failure_layer": layer,
            "failure_code": code,
            "detail": f"{detail} started_at={started_at}",
            "claim_valid": "false",
        }
    )
    return failed


def _unsupported_launch_reason(plan: dict[str, Any] | None) -> dict[str, str]:
    if plan is None:
        return {
            "layer": "deployment",
            "code": "closed_loop_launch_plan_missing",
            "detail": "No closed-loop launch plan could be built for this row.",
        }
    missing_inputs = plan.get("missing_inputs") or []
    if missing_inputs:
        return {
            "layer": "deployment",
            "code": str(missing_inputs[0]),
            "detail": f"Missing launch input(s): {', '.join(str(item) for item in missing_inputs)}.",
        }
    unsupported = plan.get("unsupported_reasons") or []
    if unsupported:
        first = unsupported[0]
        if isinstance(first, dict):
            return {
                "layer": str(first.get("layer", "deployment")),
                "code": str(first.get("code", "closed_loop_launch_unsupported")),
                "detail": str(first.get("detail", "Closed-loop launch is unsupported for this row.")),
            }
    return {
        "layer": "deployment",
        "code": "closed_loop_launch_unsupported",
        "detail": "Closed-loop launch is unsupported for this row.",
    }


def _execute_fault_row(config: dict[str, Any], row: dict[str, str]) -> dict[str, str]:
    fault = row["adapter_config"]
    expected_layer = (
        "deployment" if fault.startswith("plugin.") else fault.split(".", 1)[0]
    )
    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    source_trace = str(execution.get("source_trace", ""))
    if not source_trace:
        raise SystemExit("synthetic_fault_injection requires execution.source_trace")
    events = load_telemetry_trace(_repo_path(source_trace))
    mutated_events, runtime_context = mutate_trace(events, fault)
    diagnostics = diagnose_contract_trace(mutated_events, context=runtime_context)
    observed_codes = [item.code for item in diagnostics]
    observed_layers = [item.layer for item in diagnostics]
    observed_code = ";".join(observed_codes)
    observed_layer = ";".join(observed_layers)
    detected = bool(observed_codes)
    correctly_localized = observed_codes == [fault]
    row = dict(row)
    row.update(
        {
            "status": "completed",
            "attempted": "true",
            "completed": "true",
            "blocked": "false",
            "failure_layer": observed_layer,
            "failure_code": observed_code,
            "detail": (
                "Controlled trace mutation was classified from mutated telemetry "
                f"without passing the expected label to the detector; source={source_trace}."
            ),
            "claim_valid": "false",
            "expected_layer": expected_layer,
            "observed_layer": observed_layer,
            "expected_code": fault,
            "observed_code": observed_code,
            "detected": "true" if detected else "false",
            "correctly_localized": "true" if correctly_localized else "false",
            "service_survived": FAULT_SERVICE_SURVIVAL.get(fault, "true"),
            "late_message_count": "",
        }
    )
    return row


def _execute_lifecycle_row(config: dict[str, Any], row: dict[str, str]) -> dict[str, str]:
    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    schedule = [str(item) for item in execution.get("fault_schedule", [])]
    hardened = row["adapter_config"] == "full_lifecycle_hardening"
    evidence = run_synthetic_lifecycle_cycle(
        hardened=hardened,
        schedule=schedule,
        session_id=row["run_id"],
    )
    service_survived = bool(evidence["service_survived"])
    observed_code = str(evidence["observed_code"])
    detail = (
        "Synthetic lifecycle service classified duplicate-close and late-message events."
        if service_survived
        else "Synthetic pre-hardening service stopped on duplicate close before late events."
    )
    row = dict(row)
    row.update(
        {
            "status": "completed",
            "attempted": "true",
            "completed": "true",
            "blocked": "false",
            "failure_layer": "" if service_survived else "lifecycle",
            "failure_code": "" if service_survived else observed_code,
            "detail": detail,
            "claim_valid": "false",
            "expected_layer": "lifecycle",
            "observed_layer": "lifecycle",
            "expected_code": "late_events_classified",
            "observed_code": observed_code,
            "detected": "true",
            "correctly_localized": "true" if evidence["correctly_localized"] else "false",
            "service_survived": "true" if service_survived else "false",
            "late_message_count": str(evidence["late_message_count"]),
        }
    )
    return row


def _closed_loop_launch_plan(
    *,
    config: dict[str, Any],
    row: dict[str, str],
    output: Path,
    python_executable: str,
) -> dict[str, Any] | None:
    mode = _execution_mode(config)
    if not mode.startswith("closed_loop"):
        return None

    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    alpasim_root = _path_arg(Path(str(execution.get("alpasim_root", ""))))
    scene_preset = _closed_loop_scene_preset(config)
    timeout_seconds = int(execution.get("timeout_seconds", 900))
    topology = str(execution.get("topology", "1gpu"))
    driver_warmup_seconds = str(execution.get("driver_warmup_seconds", 10.0))
    baseport = str(execution.get("baseport", 6000))
    port = str(execution.get("port", 6789))
    run_dir = _run_output_dir(output, row)
    stdout_path, stderr_path = _experiment_log_paths(output, row)
    local_usdz_value = _local_usdz_wizard_value(execution)

    missing_inputs: list[str] = []
    unsupported_reasons: list[dict[str, str]] = []
    if not alpasim_root:
        missing_inputs.append("alpasim_root_missing")
    if not scene_preset:
        missing_inputs.append("scene_preset_missing")
    if not local_usdz_value:
        missing_inputs.append("local_usdz_dir_missing")

    adapter_blocker = _adapter_execution_blocker(config, row)
    if adapter_blocker is not None:
        unsupported_reasons.append(adapter_blocker)

    policy = row["policy"]
    if policy == "direct_actor_planner" and not execution.get("direct_actor_oracle_proxy"):
        missing_inputs.append("direct_actor_oracle_proxy_missing")
    if policy == "token_dagger_bc" and not execution.get("token_checkpoint"):
        missing_inputs.append("token_checkpoint_missing")

    driver_env_overrides = _driver_env_overrides(row)
    command: list[str] | None = None
    if not missing_inputs and not unsupported_reasons:
        command = [
            _python_arg(python_executable),
            "-m",
            "alpabridge.cli.commands.run_alpasim_local_external",
            "--mode",
            "both",
            "--model",
            policy,
            "--scene-preset",
            scene_preset,
            "--scene-id",
            row["scene_id"],
            "--run-dir",
            _path_arg(run_dir),
            "--allow-existing-run-dir",
            "--baseport",
            baseport,
            "--port",
            port,
            "--timeout",
            str(timeout_seconds),
            "--topology",
            topology,
            "--driver-warmup-seconds",
            driver_warmup_seconds,
            "--alpasim-root",
            alpasim_root,
            "--wizard-arg",
            f"scenes.local_usdz_dir={local_usdz_value}",
        ]
        for wizard_arg in _execution_list(execution, "wizard_args"):
            command.extend(["--wizard-arg", wizard_arg])
        driver_env_overrides = _driver_env_overrides(row)
        for key, value in driver_env_overrides.items():
            command.extend(["--driver-env", f"{key}={value}"])
        checkpoint = execution.get("token_checkpoint")
        if policy == "token_dagger_bc" and checkpoint:
            command.extend(["--checkpoint", _path_arg(Path(str(checkpoint)))])
        oracle_actor_proxy = execution.get("direct_actor_oracle_proxy")
        if policy == "direct_actor_planner" and oracle_actor_proxy:
            command.extend(["--oracle-actor-proxy", _path_arg(Path(str(oracle_actor_proxy)))])

    readiness_command = [
        _python_arg(python_executable),
        "-m",
        "alpabridge.cli.commands.check_alpasim_readiness",
        "--alpasim-root",
        alpasim_root,
    ]
    if scene_preset:
        readiness_command.extend(["--scene-preset", scene_preset])
    readiness_command.extend(["--scene-id", row["scene_id"]])
    if local_usdz_value:
        readiness_command.extend(["--local-usdz-dir", local_usdz_value])

    return {
        "schema": "cvm_closed_loop_launch_plan_v1",
        "supported": command is not None,
        "cwd": ".",
        "command": command,
        "readiness_command": readiness_command,
        "run_dir": _path_arg(run_dir),
        "run_status": _path_arg(run_dir / "run-status.json"),
        "logs": {
            "stdout": _path_arg(stdout_path),
            "stderr": _path_arg(stderr_path),
        },
        "mode": "both",
        "scene_preset": scene_preset,
        "local_usdz_dir": local_usdz_value,
        "timeout_seconds": timeout_seconds,
        "topology": topology,
        "baseport": int(baseport),
        "port": int(port),
        "driver_env": driver_env_overrides if command is not None else {},
        "missing_inputs": missing_inputs,
        "unsupported_reasons": unsupported_reasons,
    }


def _closed_loop_scene_preset(config: dict[str, Any]) -> str:
    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    scene_preset = str(execution.get("scene_preset", "")).strip()
    if scene_preset:
        return scene_preset
    manifest_path = Path(str(config.get("scene_manifest", "")))
    if not manifest_path.is_file():
        return ""
    manifest = _load_yaml(manifest_path)
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return str(source.get("preset", "")).strip()


def _driver_env_overrides(row: dict[str, str]) -> dict[str, str]:
    if row.get("adapter_config") == "command_only_route":
        return {"ALPABRIDGE_ROUTE_CONTRACT_MODE": "command_only_route"}
    return {}


def _execution_list(execution: dict[str, Any], key: str) -> list[str]:
    raw_value = execution.get(key, [])
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise SystemExit(f"execution.{key} must be a list")
    return [str(item) for item in raw_value]


def _local_usdz_wizard_value(execution: dict[str, Any]) -> str:
    raw_local_usdz_dir = str(execution.get("local_usdz_dir", "")).strip()
    raw_alpasim_root = str(execution.get("alpasim_root", "")).strip()
    if not raw_local_usdz_dir:
        return ""
    local_path = Path(raw_local_usdz_dir)
    alpasim_root = Path(raw_alpasim_root) if raw_alpasim_root else None
    if alpasim_root is not None:
        local_resolved = _resolve_repo_path(local_path)
        root_resolved = _resolve_repo_path(alpasim_root)
        try:
            return local_resolved.relative_to(root_resolved).as_posix()
        except ValueError:
            pass
    return _path_arg(local_path)


def _run_output_dir(output: Path, row: dict[str, str]) -> Path:
    return output / "run_dirs" / _safe_filename(row["run_id"])


def _experiment_log_paths(output: Path, row: dict[str, str]) -> tuple[Path, Path]:
    safe = _safe_filename(row["run_id"])
    if output.parent.name == "results" and output.parent.parent.name == "cvm":
        log_dir = output.parent.parent / "logs" / "experiments" / row["matrix"]
    else:
        log_dir = output / "logs"
    return log_dir / f"{safe}.stdout.log", log_dir / f"{safe}.stderr.log"


def _python_arg(value: str) -> str:
    if "/" not in value and "\\" not in value:
        return value
    return _path_arg(Path(value).expanduser())


def _path_arg(path: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    absolute_repo = REPO_ROOT.absolute()
    absolute_path = path.absolute()
    try:
        return absolute_path.relative_to(absolute_repo).as_posix()
    except ValueError:
        return str(path)


def _resolve_repo_path(path: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def _repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=20)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=5)


def _run_manifest_dir(output: Path) -> Path:
    if output.parent.name == "results" and output.parent.parent.name == "cvm":
        return output.parent.parent / "manifests" / "run_manifests"
    return output / "run_manifests"


def _write_run_manifest(
    directory: Path,
    *,
    row: dict[str, str],
    config: dict[str, Any],
    config_path: Path,
    python_executable: str,
    output: Path,
    repository_state: dict[str, Any] | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_safe_filename(row['run_id'])}.json"
    existing_manifest = _load_json_dict(path)
    launch_plan = _closed_loop_launch_plan(
        config=config,
        row=row,
        output=output,
        python_executable=python_executable,
    )
    created_at = existing_manifest.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        created_at = datetime.now(timezone.utc).isoformat()
    scene = _scene_metadata(config, row)
    manifest = {
        "schema": "cvm_run_manifest_v1",
        "created_at": created_at,
        "run_id": row["run_id"],
        "matrix": row["matrix"],
        "scene_id": row["scene_id"],
        "scenario_category": scene["scenario_category"],
        "scene": scene,
        "seed": row["seed"],
        "policy": row["policy"],
        "adapter_config": row["adapter_config"],
        "status": row["status"],
        "attempted": row["attempted"] == "true",
        "completed": row["completed"] == "true",
        "blocked": row.get("blocked") == "true",
        "claim_valid": row.get("claim_valid") == "true",
        "failure_layer": row.get("failure_layer", ""),
        "failure_code": row.get("failure_code", ""),
        "detail": row.get("detail", ""),
        "execution_mode": _execution_mode(config),
        "config_path": str(config_path),
        "config_sha256": _sha256_path(config_path),
        "terminal_status": row["status"],
        "failure_attribution": _failure_attribution(row),
        "timestamps": _run_timestamps(launch_plan),
        "provenance": _manifest_provenance(
            config=config,
            row=row,
            config_path=config_path,
            python_executable=python_executable,
            launch_plan=launch_plan,
            repository_state=repository_state,
        ),
        "contract_expectations": _contract_expectations(config, row),
    }
    if launch_plan is not None:
        manifest["planned_launch"] = launch_plan
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_timestamps(launch_plan: dict[str, Any] | None) -> dict[str, str]:
    if launch_plan is None:
        return {"started_at": "", "ended_at": "", "source": "not_available"}
    run_status = _load_json_dict(_repo_path(str(launch_plan.get("run_status", ""))))
    started_at = str(run_status.get("created_at", "") or "")
    ended_at = str(run_status.get("completed_at", "") or run_status.get("updated_at", "") or "")
    return {
        "started_at": _redact_repo_path(started_at),
        "ended_at": _redact_repo_path(ended_at),
        "source": "run_status" if started_at or ended_at else "not_available",
    }


def _manifest_provenance(
    *,
    config: dict[str, Any],
    row: dict[str, str],
    config_path: Path,
    python_executable: str,
    launch_plan: dict[str, Any] | None,
    repository_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    checkpoint = execution.get("token_checkpoint") if row.get("policy") == "token_dagger_bc" else None
    required_image = str(execution.get("required_docker_image", "")).strip()
    return {
        "repository": repository_state or _repository_state(),
        "python": _python_state(python_executable),
        "alpasim": _alpasim_checkout_state(execution),
        "patches": _patch_hashes(),
        "docker_image": _docker_image_state(required_image),
        "gpu_runtime": _gpu_runtime_state(),
        "checkpoint": _checkpoint_state(checkpoint),
        "config": {
            "path": str(config_path),
            "sha256": _sha256_path(config_path),
        },
        "launch_plan_schema": "" if launch_plan is None else str(launch_plan.get("schema", "")),
    }


def _contract_expectations(config: dict[str, Any], row: dict[str, str]) -> dict[str, Any]:
    execution = config.get("execution") if isinstance(config.get("execution"), dict) else {}
    adapter_config = row.get("adapter_config", "")
    route_source = "command_proxy" if adapter_config == "command_only_route" else "alpasim_waypoints"
    return {
        "route_source": route_source,
        "claim_valid_requires_route_waypoints": route_source != "command_proxy",
        "source_horizon_seconds": float(execution.get("horizon_seconds", 5.0)),
        "target_runtime_frequency_hz": int(execution.get("output_frequency_hz", 4)),
        "target_runtime_samples": int(
            round(
                float(execution.get("horizon_seconds", 5.0))
                * float(execution.get("output_frequency_hz", 4))
            )
        ),
        "evidence_gate": "claim_valid_false_until_audit_aggregation",
    }


def _failure_attribution(row: dict[str, str]) -> dict[str, Any]:
    claim_valid = row.get("claim_valid") == "true"
    status = row.get("status", "")
    failure_layer = row.get("failure_layer", "")
    failure_code = row.get("failure_code", "")
    if claim_valid:
        category = "policy_attributable_behavior"
    elif status == "blocked":
        category = "integration_precondition_or_unsupported_contract"
    elif status == "failed":
        category = "integration_runtime_or_evidence_failure"
    elif status == "completed":
        category = "diagnostic_rollout_pending_claim_gate"
    else:
        category = "planned_not_launched"
    if claim_valid:
        interpretation = "policy_behavior_allowed"
    elif status == "blocked":
        interpretation = "integration_precondition_blocker_not_policy_failure"
    elif status == "failed":
        interpretation = "integration_runtime_or_evidence_failure_not_policy_failure"
    elif status == "completed" and failure_layer:
        interpretation = "controlled_contract_diagnostic_not_policy_failure"
    elif status == "completed":
        interpretation = "completed_diagnostic_pending_evidence_gate_not_policy_failure"
    else:
        interpretation = "planned_not_launched_not_policy_failure"
    return {
        "category": category,
        "policy_attributable": claim_valid,
        "policy_behavior_attributable": claim_valid,
        "policy_failure_attributable": claim_valid and failure_layer == "policy",
        "claim_valid_policy_benchmark": claim_valid,
        "integration_or_evidence_invalid": not claim_valid,
        "integration_failure_attributable": (
            not claim_valid and status in {"blocked", "failed"} and bool(failure_layer)
        ),
        "interpretation": interpretation,
        "failure_layer": failure_layer,
        "failure_code": failure_code,
        "rule": (
            "A behavior event, including a policy failure, is policy-attributable "
            "only after semantic, temporal, lifecycle, deployment, and evidence "
            "gates pass; otherwise the row remains an integration, precondition, "
            "evidence, or diagnostic record and cannot be counted as a policy failure. "
            "Passing the gate permits policy-behavior attribution; policy failure "
            "also requires the retained failure layer to be policy."
        ),
    }


def _repository_state() -> dict[str, Any]:
    pathspec = _source_state_pathspec()
    diff = _git_output(["diff", "--binary", "--", *pathspec])
    status = _git_output(["status", "--short", "--", *pathspec])
    return {
        "git_sha": _git_output(["rev-parse", "HEAD"]).strip(),
        "dirty": bool(status.strip()),
        "dirty_diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
    }


def _source_state_pathspec() -> list[str]:
    return [
        ".",
        ":(exclude)artifacts/cvm",
        ":(exclude)paper/cvm/generated",
        ":(exclude)paper/cvm/figures",
        ":(exclude)paper/cvm/main.aux",
        ":(exclude)paper/cvm/main.bbl",
        ":(exclude)paper/cvm/main.blg",
        ":(exclude)paper/cvm/main.log",
        ":(exclude)paper/cvm/main.out",
        ":(exclude)paper/cvm/paper.pdf",
        ":(exclude)alpabridge.pdf",
    ]


def _alpasim_checkout_state(execution: dict[str, Any]) -> dict[str, Any]:
    raw_alpasim_root = str(execution.get("alpasim_root", "")).strip()
    if not raw_alpasim_root:
        return _missing_git_checkout_state("")
    return _git_checkout_state(Path(raw_alpasim_root))


def _missing_git_checkout_state(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "present": False,
        "git_sha": "",
        "dirty": None,
        "dirty_diff_sha256": "",
        "status_paths": [],
    }


def _git_checkout_state(path: Path) -> dict[str, Any]:
    if not str(path):
        return _missing_git_checkout_state("")
    resolved = _resolve_repo_path(path)
    if not resolved.exists():
        return _missing_git_checkout_state(_path_arg(path))
    git_sha = _git_output(["-C", str(resolved), "rev-parse", "HEAD"]).strip()
    status = _git_output(["-C", str(resolved), "status", "--short"]).rstrip()
    diff = _git_output(["-C", str(resolved), "diff", "--binary"])
    return {
        "path": _path_arg(path),
        "present": bool(git_sha),
        "git_sha": git_sha,
        "dirty": bool(status) if git_sha else None,
        "dirty_diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest() if git_sha else "",
        "status_paths": _git_status_paths(status) if git_sha else [],
    }


def _git_status_paths(status: str) -> list[str]:
    paths: list[str] = []
    for line in status.splitlines():
        if len(line) > 2 and line[2] == " ":
            value = line[3:].strip()
        elif len(line) > 1 and line[1] == " ":
            value = line[2:].strip()
        else:
            value = line.strip()
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        if value:
            paths.append(value)
    return paths


def _patch_hashes() -> dict[str, str]:
    patch_dir = REPO_ROOT / "src" / "alpabridge" / "alpasim_overrides"
    hashes: dict[str, str] = {}
    for path in sorted(patch_dir.rglob("*")):
        if path.is_file() and path.suffix in {".patch", ".yaml", ".py", ".toml", ".Dockerfile"}:
            hashes[_path_arg(path)] = _sha256_path(path)
    for path in sorted(patch_dir.glob("Dockerfile*")):
        if path.is_file():
            hashes[_path_arg(path)] = _sha256_path(path)
    return hashes


def _docker_image_state(image: str) -> dict[str, Any]:
    if not image:
        return {"tag": "", "available": False, "id": "", "repo_digests": []}
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {"tag": image, "available": False, "id": "", "repo_digests": []}
    if result.returncode != 0:
        return {"tag": image, "available": False, "id": "", "repo_digests": []}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"tag": image, "available": True, "id": "", "repo_digests": []}
    item = payload[0] if isinstance(payload, list) and payload else {}
    return {
        "tag": image,
        "available": True,
        "id": str(item.get("Id", "")),
        "repo_digests": [str(value) for value in item.get("RepoDigests", []) if value],
    }


def _gpu_runtime_state() -> dict[str, str]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {"available": "false", "gpu": "", "driver": ""}
    if result.returncode != 0:
        return {"available": "false", "gpu": "", "driver": ""}
    first_line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    gpu, _, driver = first_line.partition(",")
    return {"available": "true", "gpu": gpu.strip(), "driver": driver.strip()}


def _checkpoint_state(checkpoint: object) -> dict[str, str]:
    if checkpoint in {None, ""}:
        return {"path": "", "sha256": "", "available": "false"}
    path = Path(str(checkpoint))
    resolved = _resolve_repo_path(path)
    if not resolved.is_file():
        return {"path": _path_arg(path), "sha256": "", "available": "false"}
    return {"path": _path_arg(path), "sha256": _sha256_path(resolved), "available": "true"}


def _python_state(python_executable: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            [_python_arg(python_executable), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )
    except FileNotFoundError:
        result = None
    return {
        "executable": _python_arg(python_executable),
        "version": result.stdout.strip() if result is not None and result.returncode == 0 else "",
    }


def _git_output(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _redact_repo_path(value: str) -> str:
    return value.replace(str(REPO_ROOT), "<repo>").replace(str(REPO_ROOT.resolve()), "<repo>")


def _safe_filename(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in value)


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _summary_created_at(manifest_dir: Path, rows: list[dict[str, str]]) -> str:
    timestamps: list[str] = []
    for row in rows:
        manifest = _load_json_dict(manifest_dir / f"{_safe_filename(row['run_id'])}.json")
        created_at = manifest.get("created_at")
        if isinstance(created_at, str) and created_at:
            timestamps.append(created_at)
    if timestamps:
        return max(timestamps)
    return datetime.fromtimestamp(0, timezone.utc).isoformat()


def _summary(
    *,
    config: dict[str, Any],
    rows: list[dict[str, str]],
    blockers: list[dict[str, str]],
    config_path: Path,
    created_at: str,
) -> dict[str, Any]:
    failure_code_counts = Counter(row.get("failure_code", "") for row in rows if row.get("failure_code"))
    blocker_counts = Counter(
        row.get("failure_code", "")
        for row in rows
        if row.get("status") == "blocked" and row.get("failure_code")
    )
    return {
        "schema": "cvm_matrix_summary_v1",
        "created_at": created_at,
        "matrix": str(config.get("name", "")),
        "config": str(config_path),
        "expected_runs": int(config.get("execution", {}).get("expected_runs", len(rows))),
        "rows": len(rows),
        "planned": sum(row["status"] == "planned" for row in rows),
        "attempted": sum(row["attempted"] == "true" for row in rows),
        "completed": sum(row["completed"] == "true" for row in rows),
        "failed": sum(row["status"] == "failed" for row in rows),
        "blocked": sum(row["blocked"] == "true" for row in rows),
        "claim_valid": False,
        "blockers": blockers,
        "failure_code_counts": dict(sorted(failure_code_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_fault_injection(
    path: Path, config: dict[str, Any], *, rows: list[dict[str, str]] | None = None
) -> None:
    fields = [
        "injection",
        "expected_layer",
        "observed_layer",
        "expected_code",
        "observed_code",
        "detected",
        "service_survived",
        "claim_valid",
        "status",
        "correctly_localized",
    ]
    if rows is None:
        table_rows = []
        for fault in config.get("faults", []):
            layer = str(fault).split(".", 1)[0]
            table_rows.append(
                {
                    "injection": fault,
                    "expected_layer": layer,
                    "observed_layer": "",
                    "expected_code": fault,
                    "observed_code": "",
                    "detected": "false",
                    "service_survived": "",
                    "claim_valid": "false",
                    "status": "blocked:not_implemented",
                    "correctly_localized": "false",
                }
            )
    else:
        table_rows = [
            {
                "injection": row["adapter_config"],
                "expected_layer": row.get("expected_layer", ""),
                "observed_layer": row.get("observed_layer", ""),
                "expected_code": row.get("expected_code", ""),
                "observed_code": row.get("observed_code", ""),
                "detected": row.get("detected", "false"),
                "service_survived": row.get("service_survived", ""),
                "claim_valid": row.get("claim_valid", "false"),
                "status": row.get("status", ""),
                "correctly_localized": row.get("correctly_localized", "false"),
            }
            for row in rows
        ]
    _write_csv(path, table_rows, fields)


def _write_lifecycle_stress(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "run_id",
        "adapter_config",
        "seed",
        "cycle",
        "late_message_count",
        "service_survived",
        "observed_code",
        "claim_valid",
        "status",
    ]
    table_rows = []
    for row in rows:
        cycle = row["run_id"].rsplit("cycle", 1)[-1] if "cycle" in row["run_id"] else ""
        table_rows.append(
            {
                "run_id": row["run_id"],
                "adapter_config": row["adapter_config"],
                "seed": row["seed"],
                "cycle": cycle,
                "late_message_count": row.get("late_message_count", ""),
                "service_survived": row.get("service_survived", ""),
                "observed_code": row.get("observed_code", ""),
                "claim_valid": row.get("claim_valid", "false"),
                "status": row.get("status", ""),
            }
        )
    _write_csv(path, table_rows, fields)


if __name__ == "__main__":
    raise SystemExit(main())
