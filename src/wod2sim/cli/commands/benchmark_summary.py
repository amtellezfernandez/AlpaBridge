from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

MANIFEST_NAME = "closed-loop-reproduction-manifest.json"
RUN_AUDIT_NAME = "run-audit.json"
SUPPORT_BUNDLE_REPORT_NAME = "support-bundle-report.json"
SUPPORT_BUNDLE_NAME = "support-bundle.tar.gz"
SUMMARY_SCHEMA = "wod2sim_benchmark_summary_v1"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate one or more wod2sim-reproduce evidence directories into a compact "
            "benchmark summary."
        )
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        action="append",
        default=[],
        help="Evidence directory containing closed-loop-reproduction-manifest.json.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        action="append",
        default=[],
        help="Explicit reproduction manifest path.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON summary output path.")
    parser.add_argument("--json", action="store_true", help="Print the benchmark summary as JSON.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero unless every input is valid executed closed-loop claim evidence.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = build_summary(evidence_dirs=args.evidence_dir, manifest_paths=args.manifest)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print_human_summary(summary)
    if args.strict and not summary["valid_claim_evidence"]:
        return 1
    return 0 if summary["valid"] else 1


def build_summary(
    *,
    evidence_dirs: list[Path] | None = None,
    manifest_paths: list[Path] | None = None,
) -> dict[str, Any]:
    inputs = _resolve_inputs(evidence_dirs or [], manifest_paths or [])
    runs = [_summarize_run(manifest_path) for manifest_path in inputs]
    aggregate = _aggregate_runs(runs)
    valid = bool(runs) and all(run["input_valid"] for run in runs)
    valid_claim_evidence = valid and bool(runs) and all(_run_is_claim_evidence(run) for run in runs)
    advice = _advice(runs=runs, valid=valid, valid_claim_evidence=valid_claim_evidence)
    return {
        "schema": SUMMARY_SCHEMA,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "valid": valid,
        "valid_claim_evidence": valid_claim_evidence,
        "claim_rule": (
            "Every included run must be an executed wod2sim-reproduce run with "
            "valid_claim_evidence=true, a valid run audit, zero sensor failures, and a valid "
            "support bundle report."
        ),
        "run_count": len(runs),
        "valid_input_count": sum(1 for run in runs if run["input_valid"]),
        "valid_claim_evidence_count": sum(1 for run in runs if _run_is_claim_evidence(run)),
        "aggregate": aggregate,
        "runs": runs,
        "advice": advice,
    }


def _resolve_inputs(evidence_dirs: list[Path], manifest_paths: list[Path]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for evidence_dir in evidence_dirs:
        path = (evidence_dir / MANIFEST_NAME).resolve()
        if path not in seen:
            seen.add(path)
            resolved.append(path)
    for manifest_path in manifest_paths:
        path = manifest_path.resolve()
        if path not in seen:
            seen.add(path)
            resolved.append(path)
    return resolved


def _summarize_run(manifest_path: Path) -> dict[str, Any]:
    evidence_dir = manifest_path.parent
    errors: list[str] = []
    manifest = _load_json(manifest_path, errors=errors, label="manifest", required=True)
    audit = _load_json(
        evidence_dir / RUN_AUDIT_NAME,
        errors=errors,
        label=RUN_AUDIT_NAME,
        required=False,
    )
    support_report = _load_json(
        evidence_dir / SUPPORT_BUNDLE_REPORT_NAME,
        errors=errors,
        label=SUPPORT_BUNDLE_REPORT_NAME,
        required=False,
    )
    support_bundle_path = _resolve_support_bundle_path(evidence_dir, support_report)
    support_bundle_sha256 = _sha256_if_file(support_bundle_path)

    audit_summary = _audit_summary(audit)
    support_bundle_summary = _support_bundle_summary(
        support_report,
        bundle_path=support_bundle_path,
        sha256=support_bundle_sha256,
    )
    scene_ids = _string_list(manifest.get("scene_ids") or audit.get("scene_ids"))
    run_id = _run_id(manifest=manifest, evidence_dir=evidence_dir)
    user_supplied_artifacts = manifest.get("user_supplied_artifacts")
    if not isinstance(user_supplied_artifacts, dict):
        user_supplied_artifacts = {}

    return {
        "run_id": run_id,
        "input_valid": not errors,
        "errors": errors,
        "status": manifest.get("status"),
        "mode": manifest.get("mode"),
        "valid_claim_evidence": bool(manifest.get("valid_claim_evidence")),
        "model": manifest.get("model") or audit.get("model"),
        "scene_preset": manifest.get("scene_preset") or audit.get("scene_preset"),
        "scene_ids": scene_ids,
        "scene_count": len(scene_ids),
        "requires_gated_or_user_assets": _dict_or_empty(
            manifest.get("requires_gated_or_user_assets")
        ),
        "user_supplied_artifact_kinds": sorted(
            key for key, value in user_supplied_artifacts.items() if value
        ),
        "provenance": _dict_or_empty(manifest.get("provenance")),
        "audit": audit_summary,
        "support_bundle": support_bundle_summary,
        "artifacts": {
            "manifest": MANIFEST_NAME if manifest_path.is_file() else None,
            "run_audit": RUN_AUDIT_NAME if (evidence_dir / RUN_AUDIT_NAME).is_file() else None,
            "support_bundle_report": SUPPORT_BUNDLE_REPORT_NAME
            if (evidence_dir / SUPPORT_BUNDLE_REPORT_NAME).is_file()
            else None,
            "support_bundle": SUPPORT_BUNDLE_NAME if support_bundle_path.is_file() else None,
        },
    }


def _audit_summary(audit: dict[str, Any]) -> dict[str, Any]:
    run_status = _dict_or_empty(audit.get("run_status"))
    driver_log = _dict_or_empty(audit.get("driver_log"))
    return {
        "present": bool(audit),
        "valid": _optional_bool(audit.get("valid")),
        "frame_count": _int_value(audit.get("frame_count")),
        "sensor_pipeline_ok": _optional_bool(audit.get("sensor_pipeline_ok")),
        "sensor_failure_count": _int_value(audit.get("sensor_failure_count")),
        "result_counts": _counter_dict(audit.get("result_counts")),
        "sensor_status_counts": _counter_dict(audit.get("sensor_status_counts")),
        "max_pose_camera_lag_us": _optional_int(audit.get("max_pose_camera_lag_us")),
        "run_status": {
            "state": run_status.get("state"),
            "phase": run_status.get("phase"),
            "driver_returncode": run_status.get("driver_returncode"),
            "wizard_returncode": run_status.get("wizard_returncode"),
            "aggregate_status": run_status.get("aggregate_status"),
        },
        "driver_log": {
            "kind": driver_log.get("kind"),
            "present": _optional_bool(driver_log.get("present")),
        },
    }


def _support_bundle_summary(
    support_report: dict[str, Any],
    *,
    bundle_path: Path,
    sha256: str | None,
) -> dict[str, Any]:
    run_audit = _dict_or_empty(support_report.get("run_audit"))
    return {
        "report_present": bool(support_report),
        "valid": _optional_bool(support_report.get("valid")),
        "bundle_present": bundle_path.is_file(),
        "sha256": sha256,
        "copied_file_count": _int_value(support_report.get("copied_file_count")),
        "missing_file_count": _int_value(support_report.get("missing_file_count")),
        "missing_files": _string_list(support_report.get("missing_files")),
        "run_audit": {
            "valid": _optional_bool(run_audit.get("valid")),
            "sensor_pipeline_ok": _optional_bool(run_audit.get("sensor_pipeline_ok")),
            "sensor_failure_count": _int_value(run_audit.get("sensor_failure_count")),
            "driver_log_kind": run_audit.get("driver_log_kind"),
        },
    }


def _aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    model_counts = Counter(str(run.get("model") or "unknown") for run in runs)
    status_counts = Counter(str(run.get("status") or "unknown") for run in runs)
    mode_counts = Counter(str(run.get("mode") or "unknown") for run in runs)
    run_state_counts = Counter(
        str(run["audit"]["run_status"].get("state") or "unknown") for run in runs
    )
    aggregate_status_counts = Counter(
        str(run["audit"]["run_status"].get("aggregate_status") or "unknown") for run in runs
    )
    result_counts: Counter[str] = Counter()
    sensor_status_counts: Counter[str] = Counter()
    scene_ids: set[str] = set()
    support_bundle_hashes: list[str] = []
    provenance_commits: set[str] = set()
    for run in runs:
        scene_ids.update(run.get("scene_ids", []))
        result_counts.update(run["audit"]["result_counts"])
        sensor_status_counts.update(run["audit"]["sensor_status_counts"])
        sha256 = run["support_bundle"].get("sha256")
        if sha256:
            support_bundle_hashes.append(str(sha256))
        commit = _dict_or_empty(run.get("provenance")).get("git", {})
        if isinstance(commit, dict) and commit.get("commit"):
            provenance_commits.add(str(commit["commit"]))

    return {
        "models": dict(sorted(model_counts.items())),
        "statuses": dict(sorted(status_counts.items())),
        "modes": dict(sorted(mode_counts.items())),
        "run_states": dict(sorted(run_state_counts.items())),
        "aggregate_statuses": dict(sorted(aggregate_status_counts.items())),
        "scene_count": len(scene_ids),
        "scene_ids": sorted(scene_ids),
        "total_frames": sum(int(run["audit"]["frame_count"]) for run in runs),
        "audit_valid_count": sum(1 for run in runs if run["audit"]["valid"] is True),
        "sensor_pipeline_ok_count": sum(
            1 for run in runs if run["audit"]["sensor_pipeline_ok"] is True
        ),
        "sensor_failure_count": sum(
            int(run["audit"]["sensor_failure_count"]) for run in runs
        ),
        "result_counts": dict(sorted(result_counts.items())),
        "sensor_status_counts": dict(sorted(sensor_status_counts.items())),
        "support_bundle_valid_count": sum(
            1 for run in runs if run["support_bundle"]["valid"] is True
        ),
        "support_bundle_hashes": sorted(support_bundle_hashes),
        "provenance_commits": sorted(provenance_commits),
    }


def _run_is_claim_evidence(run: dict[str, Any]) -> bool:
    return bool(
        run["input_valid"]
        and run["status"] == "completed"
        and run["mode"] == "execute"
        and run["valid_claim_evidence"]
        and run["audit"]["valid"] is True
        and run["audit"]["sensor_pipeline_ok"] is True
        and int(run["audit"]["sensor_failure_count"]) == 0
        and run["support_bundle"]["valid"] is True
        and run["support_bundle"]["bundle_present"] is True
    )


def _advice(
    *,
    runs: list[dict[str, Any]],
    valid: bool,
    valid_claim_evidence: bool,
) -> list[str]:
    if not runs:
        return ["Provide at least one --evidence-dir or --manifest input."]
    if valid_claim_evidence:
        return ["All included runs satisfy the closed-loop evidence rule."]
    advice: list[str] = []
    if not valid:
        advice.append("One or more inputs are missing required evidence JSON files.")
    planned = [run["run_id"] for run in runs if run.get("status") == "planned"]
    if planned:
        advice.append(
            "Plan-only runs are not closed-loop evidence. Rerun with --execute: "
            + ", ".join(planned)
        )
    failed = [run["run_id"] for run in runs if run.get("status") == "failed"]
    if failed:
        advice.append("Failed reproduction runs need triage before they support claims: " + ", ".join(failed))
    sensor_failed = [
        run["run_id"]
        for run in runs
        if int(run["audit"]["sensor_failure_count"]) > 0
        or run["audit"]["sensor_pipeline_ok"] is False
    ]
    if sensor_failed:
        advice.append(
            "Runs with sensor-pipeline failures are adapter/runtime triage evidence, not clean benchmark evidence: "
            + ", ".join(sensor_failed)
        )
    missing_bundle = [
        run["run_id"]
        for run in runs
        if run["support_bundle"]["valid"] is not True
        or run["support_bundle"]["bundle_present"] is not True
    ]
    if missing_bundle:
        advice.append("Create valid support bundles for: " + ", ".join(missing_bundle))
    return advice


def _load_json(
    path: Path,
    *,
    errors: list[str],
    label: str,
    required: bool,
) -> dict[str, Any]:
    if not path.is_file():
        if required:
            errors.append(f"missing {label}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"invalid {label}: {exc}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"invalid {label}: expected object")
        return {}
    return payload


def _resolve_support_bundle_path(evidence_dir: Path, support_report: dict[str, Any]) -> Path:
    local = evidence_dir / SUPPORT_BUNDLE_NAME
    if local.is_file():
        return local
    raw_bundle_path = support_report.get("bundle_path")
    if isinstance(raw_bundle_path, str) and raw_bundle_path:
        return Path(raw_bundle_path).expanduser().resolve()
    return local


def _sha256_if_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_id(*, manifest: dict[str, Any], evidence_dir: Path) -> str:
    run_dir = manifest.get("run_dir")
    if isinstance(run_dir, str) and run_dir:
        name = Path(run_dir).name
        if name and name not in {"run", "evidence"}:
            return name
    if evidence_dir.name and evidence_dir.name != "evidence":
        return evidence_dir.name
    if evidence_dir.parent.name:
        return evidence_dir.parent.name
    return evidence_dir.name or "unknown-run"


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _counter_dict(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counter: dict[str, int] = {}
    for key, raw in value.items():
        counter[str(key)] = _int_value(raw)
    return counter


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _int_value(value: Any) -> int:
    parsed = _optional_int(value)
    return 0 if parsed is None else parsed


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _print_human_summary(summary: dict[str, Any]) -> None:
    aggregate = summary["aggregate"]
    print("WOD2Sim benchmark summary")
    print(f"  valid: {summary['valid']}")
    print(f"  valid claim evidence: {summary['valid_claim_evidence']}")
    print(f"  runs: {summary['run_count']}")
    print(f"  claim-valid runs: {summary['valid_claim_evidence_count']}")
    print(f"  models: {aggregate['models']}")
    print(f"  scene count: {aggregate['scene_count']}")
    print(f"  total frames: {aggregate['total_frames']}")
    print(f"  sensor failures: {aggregate['sensor_failure_count']}")
    print(f"  result counts: {aggregate['result_counts']}")
    if summary["advice"]:
        print("  advice:")
        for item in summary["advice"]:
            print(f"    - {item}")


if __name__ == "__main__":
    raise SystemExit(main())
