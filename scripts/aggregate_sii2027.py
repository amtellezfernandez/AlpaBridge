from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate SII 2027 run rows.")
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    rows = _load_run_rows(args.inputs)
    duplicate_completed = _duplicate_completed_run_ids(rows)
    if duplicate_completed:
        raise SystemExit(f"Duplicate completed run IDs: {', '.join(duplicate_completed[:5])}")

    rows = sorted(rows, key=lambda row: (row.get("matrix", ""), row.get("run_id", "")))
    failures = [row for row in rows if row.get("status") != "completed"]
    summary = _summary(rows=rows, failures=failures)

    _write_csv(args.output / "runs.csv", rows, _fields(rows))
    _write_csv(args.output / "failures.csv", failures, _fields(rows))
    _write_summary_csv(args.output / "summary.csv", summary)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    _write_empty_frames(args.output / "frames.csv")
    _write_fault_rollup(args.inputs, args.output / "fault_injection.csv")
    _write_tables(args.output, summary, rows)
    return 0


def _load_run_rows(inputs: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(inputs.rglob("runs.csv")):
        if path.parent == inputs:
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row["_source"] = str(path)
                rows.append(row)
    return rows


def _duplicate_completed_run_ids(rows: list[dict[str, str]]) -> list[str]:
    counts = Counter(row["run_id"] for row in rows if row.get("status") == "completed")
    return sorted(run_id for run_id, count in counts.items() if count > 1)


def _summary(*, rows: list[dict[str, str]], failures: list[dict[str, str]]) -> dict[str, Any]:
    status_counts = Counter(row.get("status", "") for row in rows)
    matrix_counts = Counter(row.get("matrix", "") for row in rows)
    failure_code_counts = Counter(
        row.get("failure_code", "") for row in rows if row.get("failure_code")
    )
    blocker_counts = Counter(
        row.get("failure_code", "")
        for row in rows
        if row.get("status") == "blocked" and row.get("failure_code")
    )
    return {
        "schema": "sii2027_aggregate_summary_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_hash": _hash_rows(rows),
        "attempted_runs": sum(row.get("attempted") == "true" for row in rows),
        "completed_runs": sum(row.get("completed") == "true" for row in rows),
        "failed_runs": status_counts.get("failed", 0),
        "blocked_runs": status_counts.get("blocked", 0),
        "total_rows": len(rows),
        "failure_rows": len(failures),
        "claim_valid": False,
        "status_counts": dict(sorted(status_counts.items())),
        "matrix_counts": dict(sorted(matrix_counts.items())),
        "failure_code_counts": dict(sorted(failure_code_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
    }


def _hash_rows(rows: list[dict[str, str]]) -> str:
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _fields(rows: list[dict[str, str]]) -> list[str]:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    return fields or ["run_id", "status"]


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_summary_csv(path: Path, summary: dict[str, Any]) -> None:
    fields = [
        "total_rows",
        "attempted_runs",
        "completed_runs",
        "failed_runs",
        "blocked_runs",
        "claim_valid",
        "data_hash",
    ]
    _write_csv(path, [{field: str(summary[field]) for field in fields}], fields)


def _write_empty_frames(path: Path) -> None:
    _write_csv(
        path,
        [],
        [
            "run_id",
            "frame_index",
            "sim_timestamp",
            "observation_timestamp",
            "observation_age_ms",
            "route_source",
            "trajectory_valid",
        ],
    )


def _write_fault_rollup(inputs: Path, output: Path) -> None:
    rows: list[dict[str, str]] = []
    for path in sorted(inputs.rglob("fault_injection.csv")):
        if path == output:
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    fields = list(rows[0].keys()) if rows else ["injection", "status"]
    _write_csv(output, rows, fields)


def _write_tables(output: Path, summary: dict[str, Any], rows: list[dict[str, str]]) -> None:
    tables = output.parent / "tables" if output.name == "results" else output / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    data_hash = summary["data_hash"]
    lifecycle_full_total = sum(
        row.get("matrix") == "lifecycle_stress"
        and row.get("adapter_config") == "full_lifecycle_hardening"
        for row in rows
    )
    lifecycle_full_survived = sum(
        row.get("matrix") == "lifecycle_stress"
        and row.get("adapter_config") == "full_lifecycle_hardening"
        and row.get("service_survived") == "true"
        for row in rows
    )
    lifecycle_strict_total = sum(
        row.get("matrix") == "lifecycle_stress"
        and row.get("adapter_config") == "strict_or_pre_hardening_behavior"
        for row in rows
    )
    lifecycle_strict_survived = sum(
        row.get("matrix") == "lifecycle_stress"
        and row.get("adapter_config") == "strict_or_pre_hardening_behavior"
        and row.get("service_survived") == "true"
        for row in rows
    )
    fault_total = sum(row.get("matrix") == "fault_injection" for row in rows)
    fault_detected = sum(
        row.get("matrix") == "fault_injection" and row.get("detected") == "true"
        for row in rows
    )
    fault_localized = sum(
        row.get("matrix") == "fault_injection"
        and row.get("correctly_localized") == "true"
        for row in rows
    )
    (tables / "contract_map.tex").write_text(
        "% generated by scripts/aggregate_sii2027.py; data_hash="
        + data_hash
        + "\n"
        + "\\begin{tabular}{llll}\n"
        + "\\toprule\nMismatch & Contract & Mechanism & Validation \\\\\n"
        + "\\midrule\n"
        + "Command-only route & Semantic & Preserve route geometry & route-source audit \\\\\n"
        + "Policy horizon/runtime grid & Temporal & Deterministic resampling & cadence tests \\\\\n"
        + "Script flow/session service & Lifecycle & Idempotent late-event handling & lifecycle tests \\\\\n"
        + "Implicit host state & Deployment & Materialized manifests & readiness checks \\\\\n"
        + "Process exit/evidence & Evidence & Audit-valid summaries & claim gate \\\\\n"
        + "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    (tables / "main_results.tex").write_text(
        "% generated by scripts/aggregate_sii2027.py; data_hash="
        + data_hash
        + "\n"
        + "\\begin{tabular}{lrrr}\n"
        + "\\toprule\nStatus & Rows & Attempted & Completed \\\\\n"
        + "\\midrule\n"
        + f"All configured & {summary['total_rows']} & {summary['attempted_runs']} & {summary['completed_runs']} \\\\\n"
        + f"Blocked & {summary['blocked_runs']} & 0 & 0 \\\\\n"
        + "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    (tables / "ablations.tex").write_text(
        "% generated by scripts/aggregate_sii2027.py; data_hash="
        + data_hash
        + "\n"
        + "\\begin{tabular}{lrr}\n"
        + "\\toprule\nSynthetic lifecycle configuration & Survived & Total \\\\\n"
        + "\\midrule\n"
        + f"Full lifecycle hardening & {lifecycle_full_survived} & {lifecycle_full_total} \\\\\n"
        + f"Strict/pre-hardening behavior & {lifecycle_strict_survived} & {lifecycle_strict_total} \\\\\n"
        + "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    (tables / "fault_localization.tex").write_text(
        "% generated by scripts/aggregate_sii2027.py; data_hash="
        + data_hash
        + "\n"
        + "\\begin{tabular}{lrr}\n"
        + "\\toprule\nSynthetic diagnostic & Count & Total \\\\\n"
        + "\\midrule\n"
        + f"Lifecycle hardening survived & {lifecycle_full_survived} & {lifecycle_full_total} \\\\\n"
        + f"Pre-hardening survived & {lifecycle_strict_survived} & {lifecycle_strict_total} \\\\\n"
        + f"Faults detected & {fault_detected} & {fault_total} \\\\\n"
        + f"Faults localized & {fault_localized} & {fault_total} \\\\\n"
        + "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    matrix_counts = summary.get("matrix_counts", {})
    (tables / "paper_numbers.tex").write_text(
        "% generated by scripts/aggregate_sii2027.py; data_hash="
        + data_hash
        + "\n"
        + f"\\newcommand{{\\SIITotalRows}}{{{summary['total_rows']}}}\n"
        + f"\\newcommand{{\\SIIAttemptedRuns}}{{{summary['attempted_runs']}}}\n"
        + f"\\newcommand{{\\SIICompletedRuns}}{{{summary['completed_runs']}}}\n"
        + f"\\newcommand{{\\SIIFailedRuns}}{{{summary['failed_runs']}}}\n"
        + f"\\newcommand{{\\SIIBlockedRuns}}{{{summary['blocked_runs']}}}\n"
        + f"\\newcommand{{\\SIISyntheticRuns}}{{{summary['completed_runs']}}}\n"
        + f"\\newcommand{{\\SIICoreRows}}{{{matrix_counts.get('core', 0)}}}\n"
        + f"\\newcommand{{\\SIISemanticRows}}{{{matrix_counts.get('semantic_ablation', 0)}}}\n"
        + f"\\newcommand{{\\SIITemporalRows}}{{{matrix_counts.get('temporal_ablation', 0)}}}\n"
        + f"\\newcommand{{\\SIILifecycleRows}}{{{matrix_counts.get('lifecycle_stress', 0)}}}\n"
        + f"\\newcommand{{\\SIIFaultRows}}{{{matrix_counts.get('fault_injection', 0)}}}\n"
        + f"\\newcommand{{\\SIILifecycleFullSurvived}}{{{lifecycle_full_survived}}}\n"
        + f"\\newcommand{{\\SIILifecycleFullTotal}}{{{lifecycle_full_total}}}\n"
        + f"\\newcommand{{\\SIILifecycleStrictSurvived}}{{{lifecycle_strict_survived}}}\n"
        + f"\\newcommand{{\\SIILifecycleStrictTotal}}{{{lifecycle_strict_total}}}\n"
        + f"\\newcommand{{\\SIIFaultDetected}}{{{fault_detected}}}\n"
        + f"\\newcommand{{\\SIIFaultLocalized}}{{{fault_localized}}}\n"
        + f"\\newcommand{{\\SIIFaultTotal}}{{{fault_total}}}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
