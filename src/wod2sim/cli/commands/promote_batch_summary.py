from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from wod2sim.cli.commands.batch_summary import SUMMARY_SCHEMA

PROMOTION_SCHEMA = "wod2sim_batch_summary_promotion_v1"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a compact wod2sim-batch-summary JSON and promote it into the "
            "tracked public evidence path."
        )
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-scene-count", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--scene-preset", required=True)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing public evidence summary.",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    report = promote_summary(
        summary_path=args.summary,
        output_path=args.output,
        expected_scene_count=args.expected_scene_count,
        model=args.model,
        scene_preset=args.scene_preset,
        overwrite=args.overwrite,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human_summary(report)
    return 0 if report["promoted"] else 1


def promote_summary(
    *,
    summary_path: Path,
    output_path: Path,
    expected_scene_count: int,
    model: str,
    scene_preset: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    summary_path = summary_path.resolve()
    output_path = output_path.resolve()
    errors: list[str] = []
    summary = _load_summary(summary_path, errors=errors)
    if summary:
        errors.extend(
            _summary_errors(
                summary=summary,
                expected_scene_count=expected_scene_count,
                model=model,
                scene_preset=scene_preset,
            )
        )
    if output_path.exists() and not overwrite:
        errors.append(f"output_exists:{output_path}")

    promoted = not errors
    if promoted:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(summary_path, output_path)

    return {
        "schema": PROMOTION_SCHEMA,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "promoted": promoted,
        "summary": str(summary_path),
        "output": str(output_path),
        "expected_scene_count": expected_scene_count,
        "model": model,
        "scene_preset": scene_preset,
        "overwrite": overwrite,
        "errors": errors,
    }


def _load_summary(path: Path, *, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"summary_missing:{path}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"summary_invalid_json:{exc}")
        return {}
    if not isinstance(payload, dict):
        errors.append("summary_root_not_object")
        return {}
    return payload


def _summary_errors(
    *,
    summary: dict[str, Any],
    expected_scene_count: int,
    model: str,
    scene_preset: str,
) -> list[str]:
    errors: list[str] = []
    aggregate = _dict_or_empty(summary.get("aggregate"))
    run_config = _dict_or_empty(summary.get("run_config"))
    if summary.get("schema") != SUMMARY_SCHEMA:
        errors.append(f"schema_mismatch:{summary.get('schema')}")
    if summary.get("valid") is not True:
        errors.append("summary_not_valid")
    if summary.get("clean_closed_loop_batch") is not True:
        errors.append("clean_closed_loop_batch_not_true")
    if _int_value(aggregate.get("planned_scene_count")) != expected_scene_count:
        errors.append("planned_scene_count_mismatch")
    if _int_value(aggregate.get("completed_scene_count")) != expected_scene_count:
        errors.append("completed_scene_count_mismatch")
    if _int_value(aggregate.get("failed_scene_count")) != 0:
        errors.append("failed_scene_count_nonzero")
    if _int_value(aggregate.get("sensor_failure_scene_count")) != 0:
        errors.append("sensor_failure_scene_count_nonzero")
    if run_config.get("model") != model:
        errors.append(f"model_mismatch:{run_config.get('model')}")
    if run_config.get("scene_preset") != scene_preset:
        errors.append(f"scene_preset_mismatch:{run_config.get('scene_preset')}")
    return errors


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _print_human_summary(report: dict[str, Any]) -> None:
    print(f"{report['schema']}: promoted={report['promoted']}")
    print(f"  summary: {report['summary']}")
    print(f"  output: {report['output']}")
    if report["errors"]:
        print(f"  errors: {report['errors']}")


if __name__ == "__main__":
    raise SystemExit(main())
