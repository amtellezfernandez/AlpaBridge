from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

PLAN_SCHEMA = "wod2sim_benchmark_regeneration_plan_v1"
COMMANDS_SCHEMA = "wod2sim_benchmark_regeneration_commands_v1"
DEFAULT_PLAN = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
DEFAULT_AUDIT = Path("docs/evidence/benchmark_regeneration_audit_20260706.json")
AUDIT_SCHEMA = "wod2sim_benchmark_regeneration_audit_v1"
GROUPS = (
    "all",
    "cleanup",
    "readiness",
    "cache",
    "run",
    "shards",
    "merge",
    "promote",
    "post",
)
COMMAND_BOUNDARIES = {
    "cleanup": {
        "execution_boundary": "public_metadata_review",
        "operator_role": "open_repo_reviewer",
        "requires_private_execution_context": False,
    },
    "readiness": {
        "execution_boundary": "public_metadata_review",
        "operator_role": "open_repo_reviewer",
        "requires_private_execution_context": False,
    },
    "cache": {
        "execution_boundary": "private_cache_preparation",
        "operator_role": "cache_builder",
        "requires_private_execution_context": True,
    },
    "run": {
        "execution_boundary": "live_closed_loop_rollout",
        "operator_role": "closed_loop_runner",
        "requires_private_execution_context": True,
    },
    "shards": {
        "execution_boundary": "live_closed_loop_rollout",
        "operator_role": "closed_loop_runner",
        "requires_private_execution_context": True,
    },
    "merge": {
        "execution_boundary": "claim_summary_merge",
        "operator_role": "claim_promoter",
        "requires_private_execution_context": True,
    },
    "promote": {
        "execution_boundary": "claim_summary_promotion",
        "operator_role": "claim_promoter",
        "requires_private_execution_context": True,
    },
    "post": {
        "execution_boundary": "public_metadata_review",
        "operator_role": "open_repo_reviewer",
        "requires_private_execution_context": False,
    },
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render copyable benchmark regeneration commands from the tracked plan. "
            "This command only reads JSON and never executes runtime steps."
        )
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument(
        "--stage",
        action="append",
        default=None,
        help="Stage name or scene preset to render. Defaults to all stages.",
    )
    parser.add_argument(
        "--group",
        choices=GROUPS,
        action="append",
        default=None,
        help="Command group to render. Defaults to all.",
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        action="append",
        default=None,
        help="1-based shard index to render when --group shards is selected.",
    )
    parser.add_argument(
        "--resume-missing-shards-from-audit",
        action="store_true",
        help=(
            "Use the audit's planned shard-summary statuses to render only missing or "
            "invalid scale-stage shard commands, plus merge/promote/post commands by default."
        ),
    )
    parser.add_argument("--created-at", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Write a machine-readable command artifact. Stdout behavior is unchanged: "
            "--json still prints the selected command rows."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print command rows as JSON.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    rows = render_commands(
        plan_path=args.plan,
        audit_path=args.audit,
        stages=args.stage,
        groups=args.group,
        shard_indexes=args.shard_index,
        resume_missing_shards_from_audit=args.resume_missing_shards_from_audit,
    )
    if args.output is not None:
        artifact = build_command_artifact(
            plan_path=args.plan,
            audit_path=args.audit,
            stages=args.stage,
            groups=args.group,
            shard_indexes=args.shard_index,
            resume_missing_shards_from_audit=args.resume_missing_shards_from_audit,
            created_at=args.created_at,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(artifact, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(row["display"])
    return 0


def build_command_artifact(
    *,
    plan_path: Path = DEFAULT_PLAN,
    audit_path: Path = DEFAULT_AUDIT,
    stages: list[str] | tuple[str, ...] | None = None,
    groups: list[str] | tuple[str, ...] | None = None,
    shard_indexes: list[int] | tuple[int, ...] | None = None,
    resume_missing_shards_from_audit: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    rows = render_commands(
        plan_path=plan_path,
        audit_path=audit_path,
        stages=stages,
        groups=groups,
        shard_indexes=shard_indexes,
        resume_missing_shards_from_audit=resume_missing_shards_from_audit,
    )
    group_counts = Counter(str(row.get("group") or "unknown") for row in rows)
    execution_boundary_counts = Counter(
        str(row.get("execution_boundary") or "unknown") for row in rows
    )
    operator_role_counts = Counter(str(row.get("operator_role") or "unknown") for row in rows)
    filters = {
        "stages": list(stages or []),
        "groups": list(groups or ["all"]),
        "shard_indexes": list(shard_indexes or []),
    }
    if resume_missing_shards_from_audit:
        filters["resume_missing_shards_from_audit"] = True
        filters["audit_artifact"] = _display_path(audit_path)
    artifact = {
        "schema": COMMANDS_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "plan_artifact": _display_path(plan_path),
        "renderer": {
            "command": "wod2sim-benchmark-commands",
            "no_runtime_execution": True,
        },
        "filters": filters,
        "row_count": len(rows),
        "group_counts": dict(sorted(group_counts.items())),
        "execution_boundary_counts": dict(sorted(execution_boundary_counts.items())),
        "operator_role_counts": dict(sorted(operator_role_counts.items())),
        "private_execution_command_count": sum(
            1 for row in rows if bool(row.get("requires_private_execution_context"))
        ),
        "public_review_command_count": sum(
            1 for row in rows if not bool(row.get("requires_private_execution_context"))
        ),
        "commands": rows,
    }
    if resume_missing_shards_from_audit:
        artifact["resume_plan"] = build_resume_plan_summary(
            plan=_read_json(plan_path),
            audit=_read_json(audit_path),
            audit_path=audit_path,
            stages=stages,
            groups=groups,
            shard_indexes=shard_indexes,
            rows=rows,
        )
    return artifact


def render_commands(
    *,
    plan_path: Path = DEFAULT_PLAN,
    audit_path: Path = DEFAULT_AUDIT,
    stages: list[str] | tuple[str, ...] | None = None,
    groups: list[str] | tuple[str, ...] | None = None,
    shard_indexes: list[int] | tuple[int, ...] | None = None,
    resume_missing_shards_from_audit: bool = False,
) -> list[dict[str, Any]]:
    plan = _read_json(plan_path)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"plan schema must be {PLAN_SCHEMA}, got {plan.get('schema')!r}")
    all_mode = groups is None or "all" in groups
    selected_groups = tuple(groups or ("all",))
    if resume_missing_shards_from_audit:
        audit = _read_json(audit_path)
        return render_resume_commands_from_audit(
            plan=plan,
            audit=audit,
            audit_path=audit_path,
            stages=stages,
            groups=groups,
            shard_indexes=shard_indexes,
        )
    if all_mode:
        selected_groups = ("cleanup", "readiness", "cache", "merge", "promote", "post")
    selected_stages = set(stages or [])
    selected_shard_indexes = set(shard_indexes or [])

    rows: list[dict[str, Any]] = []
    if "cleanup" in selected_groups:
        rows.append(
            _command_row(
                group="cleanup",
                stage=None,
                scene_preset=None,
                command="cleanup_ignored_benchmark_artifacts",
                display="wod2sim-benchmark-cleanup --json",
            )
        )

    if "readiness" in selected_groups:
        check_readiness = _dict_or_empty(
            _dict_or_empty(plan.get("commands")).get("check_readiness")
        )
        rows.extend(
            _command_rows(
                stage=None,
                scene_preset=None,
                group="readiness",
                commands={"check_readiness": check_readiness},
            )
        )

    for stage in _matching_stages(plan, selected_stages=selected_stages):
        commands = _dict_or_empty(stage.get("commands"))
        if "cache" in selected_groups:
            rows.extend(
                _command_rows(
                    stage=stage,
                    group="cache",
                    commands={
                        "link_local_cache_from_all_usdzs": commands.get(
                            "link_local_cache_from_all_usdzs"
                        ),
                        "build_local_cache": commands.get("build_local_cache"),
                        "validate_local_cache": commands.get("validate_local_cache"),
                    },
                )
            )
        render_full_run = "run" in selected_groups or (
            all_mode and not _list_of_dicts(stage.get("shards"))
        )
        if render_full_run:
            rows.extend(
                _command_rows(
                    stage=stage,
                    group="run",
                    commands={
                        "run_batch": commands.get("run_batch"),
                        "write_batch_summary": commands.get("write_batch_summary"),
                    },
                )
            )
        render_shards = "shards" in selected_groups or (
            all_mode and bool(_list_of_dicts(stage.get("shards")))
        )
        if render_shards:
            rows.extend(
                _shard_command_rows(
                    stage=stage,
                    selected_shard_indexes=selected_shard_indexes,
                )
            )
        if "merge" in selected_groups:
            rows.extend(
                _command_rows(
                    stage=stage,
                    group="merge",
                    commands={"merge_shard_summaries": commands.get("merge_shard_summaries")},
                )
            )
        if "promote" in selected_groups:
            rows.extend(
                _command_rows(
                    stage=stage,
                    group="promote",
                    commands={"promote_public_summary": commands.get("promote_public_summary")},
                )
            )

    if "post" in selected_groups:
        rows.extend(_post_command_rows(plan))

    return rows


def render_resume_commands_from_audit(
    *,
    plan: dict[str, Any],
    audit: dict[str, Any],
    audit_path: Path = DEFAULT_AUDIT,
    stages: list[str] | tuple[str, ...] | None = None,
    groups: list[str] | tuple[str, ...] | None = None,
    shard_indexes: list[int] | tuple[int, ...] | None = None,
) -> list[dict[str, Any]]:
    if audit.get("schema") != AUDIT_SCHEMA:
        raise ValueError(f"audit schema must be {AUDIT_SCHEMA}, got {audit.get('schema')!r}")
    return _resume_missing_shard_command_rows(
        plan=plan,
        audit=audit,
        audit_path=audit_path,
        selected_stages=set(stages or []),
        selected_groups=_resume_selected_groups(groups),
        selected_shard_indexes=set(shard_indexes or []),
    )


def build_resume_plan_summary(
    *,
    plan: dict[str, Any],
    audit: dict[str, Any],
    audit_path: Path = DEFAULT_AUDIT,
    stages: list[str] | tuple[str, ...] | None = None,
    groups: list[str] | tuple[str, ...] | None = None,
    shard_indexes: list[int] | tuple[int, ...] | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected_stages = set(stages or [])
    selected_groups = _resume_selected_groups(groups)
    selected_shard_indexes = set(shard_indexes or [])
    missing_statuses_by_preset = _missing_shard_summary_statuses_by_preset(audit)
    stage_rows: list[dict[str, Any]] = []

    for stage in _matching_stages(plan, selected_stages=selected_stages):
        scene_preset = str(stage.get("scene_preset") or "")
        missing_statuses = missing_statuses_by_preset.get(scene_preset, {})
        if not missing_statuses:
            continue
        shard_outputs = _shard_summary_outputs_by_index(stage)
        missing_shard_indexes = sorted(
            index for index, output in shard_outputs.items() if output in missing_statuses
        )
        if selected_shard_indexes:
            missing_shard_indexes = [
                index for index in missing_shard_indexes if index in selected_shard_indexes
            ]
        if not missing_shard_indexes:
            continue
        missing_paths = [shard_outputs[index] for index in missing_shard_indexes]
        errors_by_path = {
            path: [
                str(error)
                for error in _list_or_empty(
                    _dict_or_empty(missing_statuses.get(path)).get("errors")
                )
                if isinstance(error, str)
            ]
            for path in missing_paths
        }
        stage_rows.append(
            {
                "stage": stage.get("stage"),
                "scene_preset": scene_preset,
                "scene_count": _int_or_none(stage.get("scene_count")),
                "public_summary_target": stage.get("public_summary_target"),
                "missing_shard_indexes": missing_shard_indexes,
                "missing_shard_summary_count": len(missing_paths),
                "missing_shard_summary_paths": missing_paths,
                "missing_summary_errors_by_path": errors_by_path,
                "merge_command_included": "merge" in selected_groups,
                "promote_command_included": "promote" in selected_groups,
                "post_review_commands_included": "post" in selected_groups,
            }
        )

    row_list = rows or []
    command_group_counts = dict(
        sorted(Counter(str(row.get("group") or "unknown") for row in row_list).items())
    )
    return {
        "audit_artifact": _display_path(audit_path),
        "claim_boundary": (
            "Audit-derived resume rows are operational repair inputs only; the strict "
            "claim gate remains false until full 50/100 summaries are merged, promoted, "
            "and claim-valid."
        ),
        "selected_stage_filters": list(stages or []),
        "selected_shard_indexes": list(shard_indexes or []),
        "included_groups": list(selected_groups),
        "affected_stage_count": len(stage_rows),
        "missing_shard_summary_count": sum(
            int(stage["missing_shard_summary_count"]) for stage in stage_rows
        ),
        "command_group_counts": command_group_counts,
        "stages": stage_rows,
    }


def _resume_selected_groups(groups: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    selected_groups = tuple(groups or ("all",))
    if groups is None or "all" in selected_groups:
        return ("shards", "merge", "promote", "post")
    return selected_groups


def _matching_stages(
    plan: dict[str, Any],
    *,
    selected_stages: set[str],
) -> list[dict[str, Any]]:
    stages = _list_of_dicts(plan.get("stages"))
    if not selected_stages:
        return stages
    return [
        stage
        for stage in stages
        if str(stage.get("stage") or "") in selected_stages
        or str(stage.get("scene_preset") or "") in selected_stages
    ]


def _resume_missing_shard_command_rows(
    *,
    plan: dict[str, Any],
    audit: dict[str, Any],
    audit_path: Path,
    selected_stages: set[str],
    selected_groups: tuple[str, ...],
    selected_shard_indexes: set[int],
) -> list[dict[str, Any]]:
    missing_statuses_by_preset = _missing_shard_summary_statuses_by_preset(audit)
    rows: list[dict[str, Any]] = []
    affected_stage_count = 0

    for stage in _matching_stages(plan, selected_stages=selected_stages):
        scene_preset = str(stage.get("scene_preset") or "")
        missing_statuses = missing_statuses_by_preset.get(scene_preset, {})
        if not missing_statuses:
            continue
        shard_outputs = _shard_summary_outputs_by_index(stage)
        missing_shard_indexes = {
            index for index, output in shard_outputs.items() if output in missing_statuses
        }
        if selected_shard_indexes:
            missing_shard_indexes &= selected_shard_indexes
        if not missing_shard_indexes:
            continue
        affected_stage_count += 1
        commands = _dict_or_empty(stage.get("commands"))

        if "cache" in selected_groups:
            rows.extend(
                _annotate_resume_rows(
                    _command_rows(
                        stage=stage,
                        group="cache",
                        commands={
                            "link_local_cache_from_all_usdzs": commands.get(
                                "link_local_cache_from_all_usdzs"
                            ),
                            "build_local_cache": commands.get("build_local_cache"),
                            "validate_local_cache": commands.get("validate_local_cache"),
                        },
                    ),
                    audit_path=audit_path,
                )
            )
        if "shards" in selected_groups:
            shard_rows = _shard_command_rows(
                stage=stage,
                selected_shard_indexes=missing_shard_indexes,
            )
            for row in shard_rows:
                shard_index = _int_or_none(row.get("shard_index"))
                summary_path = shard_outputs.get(shard_index) if shard_index is not None else None
                status = _dict_or_empty(missing_statuses.get(summary_path or ""))
                row["resume_from_audit"] = _display_path(audit_path)
                row["resume_summary_path"] = summary_path
                row["resume_summary_errors"] = [
                    str(error)
                    for error in _list_or_empty(status.get("errors"))
                    if isinstance(error, str)
                ]
            rows.extend(shard_rows)
        if "merge" in selected_groups:
            rows.extend(
                _annotate_resume_rows(
                    _command_rows(
                        stage=stage,
                        group="merge",
                        commands={"merge_shard_summaries": commands.get("merge_shard_summaries")},
                    ),
                    audit_path=audit_path,
                )
            )
        if "promote" in selected_groups:
            rows.extend(
                _annotate_resume_rows(
                    _command_rows(
                        stage=stage,
                        group="promote",
                        commands={"promote_public_summary": commands.get("promote_public_summary")},
                    ),
                    audit_path=audit_path,
                )
            )

    if affected_stage_count and "post" in selected_groups:
        rows.extend(_annotate_resume_rows(_post_command_rows(plan), audit_path=audit_path))
    return rows


def _missing_shard_summary_statuses_by_preset(
    audit: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    by_preset: dict[str, dict[str, dict[str, Any]]] = {}
    for stage in _list_of_dicts(audit.get("stages")):
        scene_preset = str(stage.get("scene_preset") or "")
        statuses = _list_of_dicts(
            _dict_or_empty(stage.get("merge_provenance")).get("expected_input_summary_statuses")
        )
        if not scene_preset or not statuses:
            continue
        missing = {
            str(status.get("path") or ""): status
            for status in statuses
            if status.get("claim_valid") is not True and status.get("path")
        }
        if missing:
            by_preset[scene_preset] = missing
    return by_preset


def _shard_summary_outputs_by_index(stage: dict[str, Any]) -> dict[int, str]:
    outputs: dict[int, str] = {}
    for shard in _list_of_dicts(stage.get("shards")):
        shard_index = _int_or_none(shard.get("index"))
        if shard_index is None:
            continue
        output = _shard_summary_output(shard)
        if output:
            outputs[shard_index] = output
    return outputs


def _shard_summary_output(shard: dict[str, Any]) -> str | None:
    write_command = _dict_or_empty(_dict_or_empty(shard.get("commands")).get("write_batch_summary"))
    output = _argv_value(write_command, "--output")
    if output:
        return output
    run_dir = shard.get("run_dir")
    if isinstance(run_dir, str) and run_dir:
        return (Path(run_dir) / "wod2sim-batch-summary.json").as_posix()
    return None


def _argv_value(command: dict[str, Any], option: str) -> str | None:
    argv = _list_or_empty(command.get("argv"))
    for index, value in enumerate(argv):
        if value == option and index + 1 < len(argv) and isinstance(argv[index + 1], str):
            return str(argv[index + 1])
    return None


def _annotate_resume_rows(
    rows: list[dict[str, Any]],
    *,
    audit_path: Path,
) -> list[dict[str, Any]]:
    for row in rows:
        row["resume_from_audit"] = _display_path(audit_path)
    return rows


def _command_rows(
    *,
    stage: dict[str, Any] | None,
    group: str,
    commands: dict[str, object],
    scene_preset: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for command_name, command in commands.items():
        command_map = _dict_or_empty(command)
        if not command_map:
            continue
        display = str(command_map.get("display") or "").strip()
        if not display:
            continue
        rows.append(
            _command_row(
                group=group,
                stage=stage.get("stage") if stage is not None else None,
                scene_preset=stage.get("scene_preset") if stage is not None else scene_preset,
                command=command_name,
                display=display,
            )
        )
    return rows


def _shard_command_rows(
    *,
    stage: dict[str, Any],
    selected_shard_indexes: set[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for shard in _list_of_dicts(stage.get("shards")):
        shard_index = _int_or_none(shard.get("index"))
        if selected_shard_indexes and shard_index not in selected_shard_indexes:
            continue
        for row in _command_rows(
            stage=stage,
            group="shards",
            commands=_dict_or_empty(shard.get("commands")),
        ):
            row["shard_index"] = shard_index
            row["run_dir"] = shard.get("run_dir")
            rows.append(row)
    return rows


def _post_command_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    status_artifact = str(
        plan.get("status_artifact") or "docs/evidence/benchmark_regeneration_status_20260706.json"
    )
    return [
        _command_row(
            group="post",
            stage=None,
            scene_preset=None,
            command="refresh_status",
            display=f"wod2sim-benchmark-status --output {status_artifact} --json",
        ),
        _command_row(
            group="post",
            stage=None,
            scene_preset=None,
            command="verify_claim_gate",
            display="wod2sim-benchmark-audit --strict --json",
        ),
    ]


def _command_row(
    *,
    group: str,
    stage: object,
    scene_preset: object,
    command: str,
    display: str,
) -> dict[str, Any]:
    boundary = _dict_or_empty(COMMAND_BOUNDARIES.get(group))
    return {
        "group": group,
        "stage": stage,
        "scene_preset": scene_preset,
        "command": command,
        "display": display,
        "execution_boundary": boundary.get("execution_boundary", "unknown"),
        "operator_role": boundary.get("operator_role", "unknown"),
        "requires_private_execution_context": bool(
            boundary.get("requires_private_execution_context", True)
        ),
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON at {path}")
    return payload


def _display_path(path: Path) -> str:
    return str(path) if path.is_absolute() else path.as_posix()


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_or_empty(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
