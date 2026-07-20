from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from wod2sim.audit.diagnostic_experiment import run_diagnostic_experiment
from wod2sim.audit.diagnostic_trace_generation import generate_protocol_trace

DEFAULT_TRACE = Path("artifacts/cvm/inputs/diagnostic_protocol_sessions.jsonl")
DEFAULT_JSON_OUTPUT = Path("artifacts/cvm/results/diagnostic_experiment.json")
DEFAULT_CSV_OUTPUT = Path("artifacts/cvm/results/diagnostic_experiment_cases.csv")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate contract diagnostics against paired current-instrumentation "
            "protocol sessions and controlled mutations."
        )
    )
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument(
        "--reuse-trace",
        action="store_true",
        help="Use the existing trace instead of regenerating the default protocol sessions.",
    )
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--timing-iterations", type=int, default=200)
    parser.add_argument("--timing-batch-size", type=int, default=5)
    parser.add_argument("--adapter-iterations", type=int, default=1000)
    parser.add_argument("--adapter-batch-size", type=int, default=20)
    parser.add_argument("--random-seed", type=int, default=2027)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.trace == DEFAULT_TRACE and not args.reuse_trace:
        generate_protocol_trace(args.trace)
    result = run_diagnostic_experiment(
        args.trace,
        timing_iterations=args.timing_iterations,
        timing_batch_size=args.timing_batch_size,
        adapter_iterations=args.adapter_iterations,
        adapter_batch_size=args.adapter_batch_size,
        random_seed=args.random_seed,
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_cases(args.csv_output, result["cases"])
    print(json.dumps(_console_summary(result), indent=2, sort_keys=True))
    return 0


def _write_cases(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "case_id",
        "pair_id",
        "event_count",
        "expected_valid",
        "expected_fault_code",
        "wod2sim_valid",
        "wod2sim_observed_codes",
        "wod2sim_fault_detected",
        "wod2sim_classification_correct",
        "wod2sim_localization_correct",
        "status_only_valid",
        "status_only_fault_detected",
        "status_only_classification_correct",
        "status_only_localization_correct",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            serialized = dict(row)
            serialized["wod2sim_observed_codes"] = ";".join(serialized["wod2sim_observed_codes"])
            writer.writerow({field: serialized.get(field, "") for field in fields})


def _console_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "classification": result["classification"],
        "timing": result["timing"],
        "adapter_guard_path_timing": result["adapter_guard_path_timing"],
        "source_trace": result["source_trace"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
