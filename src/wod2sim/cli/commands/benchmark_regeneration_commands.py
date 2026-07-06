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
GROUPS = (
    "all",
    "readiness",
    "cache",
    "run",
    "shards",
    "merge",
    "promote",
    "post",
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render copyable benchmark regeneration commands from the tracked plan. "
            "This command only reads JSON and never executes runtime steps."
        )
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
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
        stages=args.stage,
        groups=args.group,
        shard_indexes=args.shard_index,
    )
    if args.output is not None:
        artifact = build_command_artifact(
            plan_path=args.plan,
            stages=args.stage,
            groups=args.group,
            shard_indexes=args.shard_index,
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
    stages: list[str] | tuple[str, ...] | None = None,
    groups: list[str] | tuple[str, ...] | None = None,
    shard_indexes: list[int] | tuple[int, ...] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    rows = render_commands(
        plan_path=plan_path,
        stages=stages,
        groups=groups,
        shard_indexes=shard_indexes,
    )
    group_counts = Counter(str(row.get("group") or "unknown") for row in rows)
    return {
        "schema": COMMANDS_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "plan_artifact": _display_path(plan_path),
        "renderer": {
            "command": "wod2sim-benchmark-commands",
            "no_runtime_execution": True,
        },
        "filters": {
            "stages": list(stages or []),
            "groups": list(groups or ["all"]),
            "shard_indexes": list(shard_indexes or []),
        },
        "row_count": len(rows),
        "group_counts": dict(sorted(group_counts.items())),
        "commands": rows,
    }


def render_commands(
    *,
    plan_path: Path = DEFAULT_PLAN,
    stages: list[str] | tuple[str, ...] | None = None,
    groups: list[str] | tuple[str, ...] | None = None,
    shard_indexes: list[int] | tuple[int, ...] | None = None,
) -> list[dict[str, Any]]:
    plan = _read_json(plan_path)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"plan schema must be {PLAN_SCHEMA}, got {plan.get('schema')!r}")
    all_mode = groups is None or "all" in groups
    selected_groups = tuple(groups or ("all",))
    if all_mode:
        selected_groups = ("readiness", "cache", "merge", "promote", "post")
    selected_stages = set(stages or [])
    selected_shard_indexes = set(shard_indexes or [])

    rows: list[dict[str, Any]] = []
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
            {
                "group": group,
                "stage": stage.get("stage") if stage is not None else None,
                "scene_preset": stage.get("scene_preset") if stage is not None else scene_preset,
                "command": command_name,
                "display": display,
            }
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
        {
            "group": "post",
            "stage": None,
            "scene_preset": None,
            "command": "refresh_status",
            "display": f"wod2sim-benchmark-status --output {status_artifact} --json",
        },
        {
            "group": "post",
            "stage": None,
            "scene_preset": None,
            "command": "verify_claim_gate",
            "display": "wod2sim-benchmark-audit --strict --json",
        },
    ]


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
