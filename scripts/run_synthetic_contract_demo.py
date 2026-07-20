from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpabridge.cli.commands.audit_run import build_report as build_audit_report
from alpabridge.cli.commands.support_bundle import build_report as build_support_bundle_report

DEFAULT_OUTPUT = ROOT / "demo" / "alpabridge-contract-demo"
SCENE_ID = "synthetic-route-001"
ROUTE_WAYPOINTS = [
    {"x": 0.0, "y": 0.0, "z": 0.0},
    {"x": 8.0, "y": 0.2, "z": 0.0},
    {"x": 16.0, "y": 0.7, "z": 0.0},
    {"x": 24.0, "y": 1.4, "z": 0.0},
    {"x": 32.0, "y": 2.2, "z": 0.0},
    {"x": 40.0, "y": 2.8, "z": 0.0},
]
EGO_POINTS = [
    (0.0, 0.0),
    (5.0, 0.1),
    (10.0, 0.35),
    (15.0, 0.65),
    (20.0, 1.05),
    (25.0, 1.55),
    (30.0, 2.05),
    (35.0, 2.45),
]
COMMAND_PROXY_CENTER_Y_M = 0.0
SYNTHETIC_ROAD_CENTER_Y_M = -3.5


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a synthetic AlpaBridge contract demo with audit and support-bundle "
            "artifacts. This is not an AlpaSim rollout or policy benchmark."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output run directory. Defaults to {DEFAULT_OUTPUT.relative_to(ROOT)}.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the output directory if it already exists.",
    )
    parser.add_argument("--json", action="store_true", help="Print the demo summary as JSON.")
    return parser.parse_args()


def generate_demo(*, output: Path, overwrite: bool = False) -> dict[str, Any]:
    run_dir = output.resolve()
    _prepare_output(run_dir, overwrite=overwrite)
    (run_dir / "driver").mkdir(parents=True)
    (run_dir / "controller").mkdir(parents=True)
    (run_dir / "aggregate").mkdir(parents=True)

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    _write_json(run_dir / "launch-metadata.json", _launch_metadata(run_dir, generated_at))
    _write_json(run_dir / "run-status.json", _run_status(generated_at))
    _write_driver_log(run_dir / "driver" / "baseline-log.jsonl")
    _write_controller_csv(run_dir / "controller" / "synthetic-controller.csv")
    _write_run_commands(run_dir)
    _write_text(run_dir / "driver.stdout.log", "synthetic contract demo driver completed\n")
    _write_text(run_dir / "driver.stderr.log", "")
    _write_text(run_dir / "synthetic-rollout.svg", _rollout_svg())

    audit_report = build_audit_report(run_dir=run_dir, audit_dir=run_dir / "audit")
    audit_report = _redact_paths(audit_report)
    _sanitize_json_files(run_dir / "audit")
    _write_json(run_dir / "run-audit.json", audit_report)

    metrics = _metrics(audit_report)
    _write_json(run_dir / "aggregate" / "synthetic-contract-metrics.json", metrics)
    _write_text(run_dir / "aggregate" / "synthetic-contract-metrics.csv", _metrics_csv(metrics))

    support_report = build_support_bundle_report(
        run_dir=run_dir,
        output=run_dir / "support-bundle.tar.gz",
        public_root=ROOT,
    )
    _write_json(run_dir / "support-bundle-report.json", support_report)

    summary = {
        "schema": "wod2sim_synthetic_contract_demo_v1",
        "artifact_valid": bool(audit_report.get("valid")) and bool(support_report.get("valid")),
        "benchmark_claim": False,
        "valid_claim_evidence": False,
        "public_assets_only": True,
        "output_dir": _public_path(run_dir),
        "scene_ids": [SCENE_ID],
        "claim_boundary": (
            "Synthetic contract demo only. It exercises audit and packaging formats "
            "without AlpaSim execution, gated scenes, private checkpoints, or policy "
            "quality metrics."
        ),
        "artifacts": {
            "launch_metadata": "launch-metadata.json",
            "run_status": "run-status.json",
            "driver_log": "driver/baseline-log.jsonl",
            "controller_trace": "controller/synthetic-controller.csv",
            "metrics": "aggregate/synthetic-contract-metrics.json",
            "visual": "synthetic-rollout.svg",
            "run_audit": "run-audit.json",
            "support_bundle": "support-bundle.tar.gz",
            "support_bundle_report": "support-bundle-report.json",
        },
        "run_audit": {
            "valid": bool(audit_report.get("valid")),
            "frame_count": int(audit_report.get("frame_count", 0)),
            "sensor_pipeline_ok": bool(audit_report.get("sensor_pipeline_ok")),
            "route_contract_ok": bool(audit_report.get("route_contract_ok")),
            "route_source_counts": audit_report.get("route_source_counts", {}),
        },
        "support_bundle": {
            "valid": bool(support_report.get("valid")),
            "copied_file_count": int(support_report.get("copied_file_count", 0)),
            "missing_file_count": int(support_report.get("missing_file_count", 0)),
        },
        "contract_diagnostics": {
            "benchmark_claim": False,
            "route_command_lateral_rmse_m": metrics["contract_diagnostics"][
                "route_command_information_loss"
            ]["same_x_lateral_rmse_m"],
            "road_center_mean_abs_lateral_offset_m": metrics["contract_diagnostics"][
                "road_center_vs_ego_route"
            ]["mean_abs_lateral_offset_m"],
        },
    }
    _write_json(run_dir / "demo-summary.json", summary)
    return summary


def _prepare_output(run_dir: Path, *, overwrite: bool) -> None:
    if run_dir.exists():
        if not overwrite:
            raise FileExistsError(f"{run_dir} already exists; pass --overwrite to replace it")
        if run_dir.is_dir():
            shutil.rmtree(run_dir)
        else:
            run_dir.unlink()
    run_dir.mkdir(parents=True, exist_ok=False)


def _launch_metadata(run_dir: Path, generated_at: str) -> dict[str, Any]:
    return {
        "schema": "wod2sim_synthetic_contract_demo_launch_v1",
        "model": "constant_velocity",
        "model_label": "synthetic_constant_velocity_stub",
        "scene_preset": "synthetic_contract_demo",
        "scene_ids": [SCENE_ID],
        "generated_at": generated_at,
        "run_dir": _public_path(run_dir),
        "valid_claim_evidence": False,
        "benchmark_claim": False,
        "public_assets_only": True,
        "gated_assets_used": False,
        "policy_quality_metrics": None,
        "route_contract_expected": "route_source=alpasim_waypoints on every driver-log frame",
        "claim_boundary": (
            "This generated run directory is a public format/conformance demo only. "
            "It is not an executed AlpaSim rollout and cannot support policy claims."
        ),
        "provenance": {
            "generator": "scripts/run_synthetic_contract_demo.py",
            "alpasim_checkout": None,
            "docker_image": None,
            "checkpoint": None,
        },
    }


def _run_status(generated_at: str) -> dict[str, Any]:
    return {
        "schema": "wod2sim_synthetic_contract_demo_status_v1",
        "state": "completed",
        "phase": "synthetic_contract_demo",
        "driver_returncode": 0,
        "wizard_returncode": None,
        "aggregate_status": "synthetic_contract_artifacts_written",
        "completed_at": generated_at,
        "valid_claim_evidence": False,
        "benchmark_claim": False,
    }


def _write_driver_log(path: Path) -> None:
    rows = []
    for index, (x, y) in enumerate(EGO_POINTS, start=1):
        timestamp_us = (index - 1) * 250_000
        rows.append(
            {
                "frame_index": index,
                "scene_id": SCENE_ID,
                "command": "straight",
                "selected_maneuver": "maintain",
                "decision_type": "synthetic_constant_velocity",
                "hybrid_token": "maintain",
                "geometric_token": "maintain",
                "candidate_count": 1,
                "reference_count": 1,
                "result": "ok",
                "route_source": "alpasim_waypoints",
                "route_waypoint_count": len(ROUTE_WAYPOINTS),
                "speed_mps": 5.0,
                "alpasim_signal": {
                    "route_source": "alpasim_waypoints",
                    "route_waypoint_count": len(ROUTE_WAYPOINTS),
                    "route_waypoints": ROUTE_WAYPOINTS,
                    "route_lane_half_width_m": 3.5,
                    "structured_hazards": [],
                    "visibility_risk": 0.0,
                    "dynamics_risk": 0.0,
                    "camera_count": 0,
                    "pose_history_len": index,
                    "oracle_actor_proxy_timestamp_us": timestamp_us,
                    "oracle_actor_proxy_current_ego_pose": {
                        "world_x": x,
                        "world_y": y,
                        "world_vx": 5.0,
                        "world_vy": 0.0,
                    },
                },
                "sensor_freshness": {
                    "status": "ok_initial" if index == 1 else "ok",
                    "pose_camera_lag_us": 0,
                },
            }
        )
    _write_text(path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _write_controller_csv(path: Path) -> None:
    lines = ["timestamp_us,x,y,qx,qy,qz,qw,vx,vy\n"]
    for index, (x, y) in enumerate(EGO_POINTS):
        lines.append(f"{index * 250_000},{x:.3f},{y:.3f},0.0,0.0,0.0,1.0,5.0,0.0\n")
    _write_text(path, "".join(lines))


def _write_run_commands(run_dir: Path) -> None:
    _write_text(
        run_dir / "driver-command.sh",
        "# Synthetic contract demo only; no AlpaSim driver process was launched.\n",
    )
    _write_text(
        run_dir / "wizard-command.sh",
        "# Synthetic contract demo only; no AlpaSim wizard process was launched.\n",
    )
    _write_text(
        run_dir / "external-driver-config.yaml",
        "\n".join(
            [
                "schema: alpabridge_synthetic_contract_demo_config_v1",
                "model: synthetic_constant_velocity_stub",
                "scene_preset: synthetic_contract_demo",
                "valid_claim_evidence: false",
                "benchmark_claim: false",
                "",
            ]
        ),
    )


def _metrics(audit_report: dict[str, Any]) -> dict[str, Any]:
    diagnostics = _contract_diagnostics()
    return {
        "schema": "wod2sim_synthetic_contract_metrics_v1",
        "benchmark_claim": False,
        "valid_claim_evidence": False,
        "policy_quality_metrics": None,
        "contract_diagnostics": diagnostics,
        "scene_ids": [SCENE_ID],
        "frame_count": int(audit_report.get("frame_count", 0)),
        "sensor_pipeline_ok": bool(audit_report.get("sensor_pipeline_ok")),
        "sensor_failure_count": int(audit_report.get("sensor_failure_count", 0)),
        "route_contract_ok": bool(audit_report.get("route_contract_ok")),
        "route_contract_failure_count": int(audit_report.get("route_contract_failure_count", 0)),
        "route_source_counts": audit_report.get("route_source_counts", {}),
        "result_counts": audit_report.get("result_counts", {}),
        "scope": (
            "Synthetic public artifact check. These values confirm route/audit plumbing "
            "only and must not be reported as closed-loop policy performance."
        ),
    }


def _metrics_csv(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "metric,value",
            f"benchmark_claim,{str(metrics['benchmark_claim']).lower()}",
            f"valid_claim_evidence,{str(metrics['valid_claim_evidence']).lower()}",
            f"frame_count,{metrics['frame_count']}",
            f"sensor_pipeline_ok,{str(metrics['sensor_pipeline_ok']).lower()}",
            f"route_contract_ok,{str(metrics['route_contract_ok']).lower()}",
            "route_command_lateral_rmse_m,"
            f"{metrics['contract_diagnostics']['route_command_information_loss']['same_x_lateral_rmse_m']}",
            "road_center_mean_abs_lateral_offset_m,"
            f"{metrics['contract_diagnostics']['road_center_vs_ego_route']['mean_abs_lateral_offset_m']}",
            "",
        ]
    )


def _contract_diagnostics() -> dict[str, Any]:
    samples = []
    command_errors = []
    road_center_offsets = []
    for x, _ in EGO_POINTS:
        route_y = _sample_route_y(ROUTE_WAYPOINTS, x)
        command_error = route_y - COMMAND_PROXY_CENTER_Y_M
        road_center_offset = route_y - SYNTHETIC_ROAD_CENTER_Y_M
        command_errors.append(command_error)
        road_center_offsets.append(road_center_offset)
        samples.append(
            {
                "x_m": round(x, 3),
                "preserved_route_y_m": round(route_y, 3),
                "command_proxy_y_m": round(COMMAND_PROXY_CENTER_Y_M, 3),
                "synthetic_road_center_y_m": round(SYNTHETIC_ROAD_CENTER_Y_M, 3),
                "command_proxy_lateral_error_m": round(command_error, 3),
                "road_center_lateral_offset_m": round(road_center_offset, 3),
            }
        )
    return {
        "schema": "wod2sim_synthetic_contract_diagnostics_v1",
        "benchmark_claim": False,
        "valid_claim_evidence": False,
        "sample_count": len(samples),
        "samples": samples,
        "route_command_information_loss": {
            "same_x_lateral_rmse_m": round(_rmse(command_errors), 3),
            "mean_abs_lateral_error_m": round(_mean_abs(command_errors), 3),
            "max_abs_lateral_error_m": round(max(abs(value) for value in command_errors), 3),
            "preserved_route_source": "alpasim_waypoints",
            "collapsed_route_source": "command_proxy",
            "interpretation": (
                "Synthetic geometry diagnostic only: collapsing route geometry to a straight "
                "command proxy loses lateral route information at the policy boundary."
            ),
        },
        "road_center_vs_ego_route": {
            "synthetic_road_center_y_m": SYNTHETIC_ROAD_CENTER_Y_M,
            "mean_abs_lateral_offset_m": round(_mean_abs(road_center_offsets), 3),
            "max_abs_lateral_offset_m": round(max(abs(value) for value in road_center_offsets), 3),
            "interpretation": (
                "Synthetic geometry diagnostic only: the ego route can be laterally offset "
                "from a visual road centerline, so scoring against road center is not "
                "equivalent to scoring against the policy route."
            ),
        },
    }


def _sample_route_y(route_waypoints: list[dict[str, float]], x: float) -> float:
    points = [(float(item["x"]), float(item["y"])) for item in route_waypoints]
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            span = x1 - x0
            if span <= 0.0:
                return y1
            alpha = (x - x0) / span
            return y0 + alpha * (y1 - y0)
    return points[-1][1]


def _rmse(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(value * value for value in values) / len(values))


def _mean_abs(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(abs(value) for value in values) / len(values)


def _rollout_svg() -> str:
    route_points = " ".join(_svg_point(x, y) for x, y, _ in _route_xyz())
    ego_circles = "\n".join(
        f'<circle cx="{80 + x * 10:.1f}" cy="{230 - y * 24:.1f}" r="7" '
        f'fill="#0f766e" opacity="{0.35 + index * 0.07:.2f}"/>'
        for index, (x, y) in enumerate(EGO_POINTS)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 320" role="img" aria-labelledby="title desc">
  <title id="title">Synthetic AlpaBridge Contract Demo</title>
  <desc id="desc">Public synthetic route and audited driver frames without gated scene media.</desc>
  <rect width="560" height="320" rx="28" fill="#f5f1e8"/>
  <rect x="28" y="28" width="504" height="264" rx="22" fill="#12343b"/>
  <text x="54" y="70" fill="#f4f1de" font-family="serif" font-size="24" font-weight="700">Synthetic contract demo</text>
  <text x="54" y="96" fill="#9fc7c1" font-family="monospace" font-size="13">not AlpaSim execution | not policy metrics | route_source=alpasim_waypoints</text>
  <path d="M54 236 C150 208 232 226 320 183 S438 145 498 128" fill="none" stroke="#6b7c85" stroke-width="38" stroke-linecap="round"/>
  <polyline points="{route_points}" fill="none" stroke="#f2cc8f" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
  {ego_circles}
  <rect x="54" y="112" width="170" height="72" rx="12" fill="#0a252b" stroke="#2a9d8f"/>
  <text x="70" y="140" fill="#f4f1de" font-family="monospace" font-size="13">frames: 8</text>
  <text x="70" y="160" fill="#f4f1de" font-family="monospace" font-size="13">sensor: ok</text>
  <text x="70" y="180" fill="#f4f1de" font-family="monospace" font-size="13">audit: format only</text>
  <rect x="330" y="214" width="168" height="42" rx="10" fill="#f2cc8f"/>
  <text x="348" y="240" fill="#12343b" font-family="monospace" font-size="13" font-weight="700">valid_claim_evidence=false</text>
</svg>
"""


def _route_xyz() -> list[tuple[float, float, float]]:
    return [(float(item["x"]), float(item["y"]), float(item["z"])) for item in ROUTE_WAYPOINTS]


def _svg_point(x: float, y: float) -> str:
    return f"{80 + x * 10:.1f},{230 - y * 24:.1f}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _sanitize_json_files(root_dir: Path) -> None:
    for path in sorted(root_dir.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        _write_json(path, _redact_paths(payload))


def _redact_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_paths(item) for item in value]
    if isinstance(value, str):
        text = value.replace(str(ROOT), "<repo>")
        home = str(Path.home())
        if home != str(ROOT):
            text = text.replace(home, "~")
        return text
    return value


def _public_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _print_human(summary: dict[str, Any]) -> None:
    print("AlpaBridge synthetic contract demo")
    print(f"  artifact valid: {summary['artifact_valid']}")
    print(f"  output dir: {summary['output_dir']}")
    print(f"  benchmark claim: {summary['benchmark_claim']}")
    print(f"  valid claim evidence: {summary['valid_claim_evidence']}")
    run_audit = summary["run_audit"]
    print(f"  audited frames: {run_audit['frame_count']}")
    print(f"  route contract ok: {run_audit['route_contract_ok']}")
    print(f"  support bundle: {summary['artifacts']['support_bundle']}")


def main() -> int:
    args = _parse_args()
    try:
        summary = generate_demo(output=args.output, overwrite=args.overwrite)
    except Exception as exc:
        print(f"alpabridge synthetic contract demo failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print_human(summary)
    return 0 if summary["artifact_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
