from __future__ import annotations

from dataclasses import asdict, dataclass, field
import argparse
import csv
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_ALPASIM_METRIC_ALIASES = {
    "collision": ("collision_at_fault", "offroad_or_collision_at_fault", "collision_any"),
    "offroad": ("offroad",),
    "route_deviation_m": ("dist_to_gt_trajectory", "plan_deviation"),
    "safety_monitor": ("safety_monitor_triggered",),
}


@dataclass(frozen=True)
class AlpaSimEvidenceThresholds:
    max_collision_rate: float = 0.01
    max_offroad_rate: float = 0.01
    max_route_deviation_m: float = 3.0
    max_safety_monitor_rate: float = 0.05


@dataclass(frozen=True)
class AlpaSimEvidenceConfig:
    thresholds: AlpaSimEvidenceThresholds = field(default_factory=AlpaSimEvidenceThresholds)
    metric_aliases: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_ALPASIM_METRIC_ALIASES))


@dataclass(frozen=True)
class AlpaSimEvidence:
    source: str
    metrics_path: str
    metrics: dict[str, float]
    run_count: int | None
    thresholds: dict[str, float]
    gates: dict[str, bool | None]
    sensor_realistic: bool
    official_compass_score: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_METRIC_LINE_RE = re.compile(
    r"^\s*[\u2500-\u257f| ]*\s*([A-Za-z_][A-Za-z0-9_]*)\s*[\u2500-\u257f| ]+(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
)
_COUNT_RE = re.compile(r"n_clips:\s*(\d+),\s*n_rollouts/clip:\s*(\d+)")


def load_alpasim_metrics(path: str | Path) -> tuple[Path, dict[str, float], int | None]:
    metrics_path = _resolve_metrics_path(Path(path))
    suffix = metrics_path.suffix.lower()
    if suffix == ".csv":
        metrics, run_count = _load_csv_metrics(metrics_path)
    elif suffix == ".json":
        metrics, run_count = _load_json_metrics(metrics_path)
    else:
        metrics, run_count = _load_text_metrics(metrics_path)
    if not metrics:
        raise ValueError(f"No numeric AlpaSim metrics found in {metrics_path}")
    return metrics_path, metrics, run_count


def build_alpasim_evidence(path: str | Path, config: AlpaSimEvidenceConfig | None = None) -> AlpaSimEvidence:
    config = config or AlpaSimEvidenceConfig()
    metrics_path, metrics, run_count = load_alpasim_metrics(path)
    gates = _metric_gates(metrics, config)
    notes = [
        "AlpaSim evidence is sensor-realistic closed-loop evidence, not an official COMPASS score.",
        "Use this as a validation tier alongside the abstract COMPASS benchmark.",
    ]
    missing = [name for name, value in gates.items() if value is None]
    if missing:
        notes.append(f"Missing gate metrics: {', '.join(sorted(missing))}.")
    return AlpaSimEvidence(
        source="alpasim",
        metrics_path=str(metrics_path),
        metrics=metrics,
        run_count=run_count,
        thresholds=asdict(config.thresholds),
        gates=gates,
        sensor_realistic=True,
        official_compass_score=False,
        notes=notes,
    )


def _resolve_metrics_path(path: Path) -> Path:
    if path.is_file():
        return path
    candidates = [
        path / "aggregate" / "metrics_results.csv",
        path / "aggregate" / "metrics_results.txt",
        path / "aggregate" / "metrics_results.json",
        path / "metrics_results.csv",
        path / "metrics_results.txt",
        path / "metrics_results.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    recursive = sorted(path.glob("**/metrics_results.csv")) + sorted(path.glob("**/metrics_results.txt")) + sorted(
        path.glob("**/metrics_results.json")
    )
    if recursive:
        return recursive[0]
    raise FileNotFoundError(f"No AlpaSim metrics_results file found under {path}")


def _load_json_metrics(path: Path) -> tuple[dict[str, float], int | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    run_count = _json_run_count(payload)
    if isinstance(payload, list):
        metrics, table_run_count = _load_table_metrics(payload)
        return metrics, run_count or table_run_count
    if isinstance(payload, dict) and isinstance(payload.get("runs"), list):
        metrics, table_run_count = _load_table_metrics(payload["runs"])
        return metrics, run_count or table_run_count
    metrics = _flatten_json_metrics(payload)
    return metrics, run_count


def _load_csv_metrics(path: Path) -> tuple[dict[str, float], int | None]:
    with path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    return _load_table_metrics(rows)


def _load_table_metrics(rows: list[dict[str, Any]]) -> tuple[dict[str, float], int | None]:
    if not rows:
        return {}, None
    run_count = _table_run_count(rows)
    if {"name", "value"}.issubset(rows[0].keys()):
        return _long_metric_table(rows), run_count
    return _wide_metric_table(rows), run_count


def _table_run_count(rows: list[dict[str, Any]]) -> int | None:
    if {"n_clips", "n_rollouts"}.issubset(rows[0].keys()):
        count = 0
        found = False
        for row in rows:
            n_clips = _to_float(row.get("n_clips"))
            n_rollouts = _to_float(row.get("n_rollouts"))
            if n_clips is not None and n_rollouts is not None:
                count += int(n_clips * n_rollouts)
                found = True
        if found:
            return count
    if "run_uuid" in rows[0]:
        return len({str(row.get("run_uuid")) for row in rows if row.get("run_uuid") not in (None, "")})
    if "rollout_uuid" in rows[0]:
        return len({str(row.get("rollout_uuid")) for row in rows if row.get("rollout_uuid") not in (None, "")})
    return len(rows)


def _long_metric_table(rows: list[dict[str, Any]]) -> dict[str, float]:
    values_by_name: dict[str, list[float]] = {}
    for row in rows:
        name = row.get("name")
        value = _to_float(row.get("value"))
        if name is not None and value is not None:
            values_by_name.setdefault(str(name), []).append(value)
    return {name: sum(values) / len(values) for name, values in values_by_name.items() if values}


def _wide_metric_table(rows: list[dict[str, Any]]) -> dict[str, float]:
    excluded = {
        "run_name",
        "run_uuid",
        "rollout_uuid",
        "trajectory_uid",
        "clip_id",
        "scene_id",
        "n_clips",
        "n_rollouts",
    }
    metrics: dict[str, float] = {}
    for column in rows[0].keys():
        column_name = str(column)
        if column_name in excluded or column_name.endswith("_std"):
            continue
        values = [_to_float(row.get(column_name)) for row in rows]
        numeric_values = [value for value in values if value is not None]
        if numeric_values:
            metrics[column_name] = sum(numeric_values) / len(numeric_values)
    return metrics


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _flatten_json_metrics(payload: Any, prefix: str = "") -> dict[str, float]:
    if isinstance(payload, dict):
        out: dict[str, float] = {}
        for key, value in payload.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[str(key)] = float(value)
            elif isinstance(value, dict):
                child = _flatten_json_metrics(value, name)
                out.update(child)
                if "mean" in value and isinstance(value["mean"], (int, float)):
                    out[str(key)] = float(value["mean"])
        return out
    return {}


def _json_run_count(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("run_count", "n_runs", "n_rollouts"):
        value = payload.get(key)
        if isinstance(value, int):
            return value
    n_clips = payload.get("n_clips")
    n_rollouts = payload.get("n_rollouts")
    if isinstance(n_clips, int) and isinstance(n_rollouts, int):
        return n_clips * n_rollouts
    return None


def _load_text_metrics(path: Path) -> tuple[dict[str, float], int | None]:
    metrics: dict[str, float] = {}
    run_count: int | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        count_match = _COUNT_RE.search(line)
        if count_match:
            run_count = int(count_match.group(1)) * int(count_match.group(2))
        metric_match = _METRIC_LINE_RE.match(line)
        if metric_match:
            metrics[metric_match.group(1)] = float(metric_match.group(2))
    return metrics, run_count


def _metric_gates(metrics: dict[str, float], config: AlpaSimEvidenceConfig) -> dict[str, bool | None]:
    thresholds = config.thresholds
    collision = _first_metric(metrics, config.metric_aliases["collision"])
    offroad = _first_metric(metrics, config.metric_aliases["offroad"])
    route_deviation = _first_metric(metrics, config.metric_aliases["route_deviation_m"])
    safety_monitor = _first_metric(metrics, config.metric_aliases["safety_monitor"])
    return {
        "collision_rate": None if collision is None else collision <= thresholds.max_collision_rate,
        "offroad_rate": None if offroad is None else offroad <= thresholds.max_offroad_rate,
        "route_deviation_m": None if route_deviation is None else route_deviation <= thresholds.max_route_deviation_m,
        "safety_monitor_rate": None if safety_monitor is None else safety_monitor <= thresholds.max_safety_monitor_rate,
    }


def _first_metric(metrics: dict[str, float], names: tuple[str, ...]) -> float | None:
    for name in names:
        if name in metrics:
            return metrics[name]
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Import AlpaSim aggregate metrics as COMPASS-side evidence.")
    parser.add_argument("path", help="AlpaSim run directory or metrics_results file path.")
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args()

    evidence = build_alpasim_evidence(args.path).to_dict()
    payload = json.dumps(evidence, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
