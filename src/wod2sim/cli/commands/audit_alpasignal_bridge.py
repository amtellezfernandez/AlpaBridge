#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from wod2sim.cli.runtime_paths import workspace_path

from wod2sim.simulator.alpasim_signal import extract_alpasim_signal, scenario_from_command
from wod2sim.simulator.alpasim_spotlight import DriveCommand, SpotlightReflexAlpaSimModel


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the AlpaSignal-to-Spotlight Reflex adapter surface.")
    parser.add_argument("--output", type=Path, default=workspace_path("artifacts", "alpasignal_bridge_audit.json"))
    args = parser.parse_args()

    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 1


def build_report() -> dict[str, Any]:
    cases = [
        _run_case(
            "static_structured_hazard",
            command=DriveCommand.STRAIGHT,
            brightness=180,
            speed=6.0,
            acceleration=0.0,
            signal_attr="alpasignal",
            hazards=[
                {
                    "forward_m": 12.0,
                    "lateral_m": -1.5,
                    "radius_m": 1.25,
                    "type": "unknown_crate",
                    "id": "crate_0",
                }
            ],
        ),
        _run_case(
            "moving_crossing_hazard",
            command=DriveCommand.LEFT,
            brightness=160,
            speed=7.0,
            acceleration=0.0,
            signal_attr="traffic_hazards",
            hazards=[
                {
                    "x": 14.0,
                    "y": 2.0,
                    "radius": 1.0,
                    "kind": "pedestrian",
                    "label": "crossing_0",
                    "vx": 0.0,
                    "vy": -2.0,
                }
            ],
        ),
        _run_case(
            "low_visibility_braking",
            command=DriveCommand.RIGHT,
            brightness=8,
            speed=0.2,
            acceleration=-3.0,
            signal_attr=None,
            hazards=[],
        ),
    ]
    gates = {
        "all_cases_emit_finite_20_point_trajectories": all(case["finite_20_point_trajectory"] for case in cases),
        "all_cases_emit_reasoning_text": all(case["reasoning_has_signal"] for case in cases),
        "structured_hazard_consumed": cases[0]["signal_obstacle_count"] == 1,
        "moving_hazard_preserved_as_actor": cases[1]["signal_actor_count"] == 1,
        "low_visibility_adds_caution_zone": cases[2]["signal_obstacle_count"] == 1
        and cases[2]["visibility_risk"] >= 0.5,
    }
    return {
        "schema": "alpasignal_bridge_audit_v1",
        "valid": all(gates.values()),
        "adapter": "wod2sim.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel",
        "claim": (
            "The AlpaSignal/AlpaSim adapter converts route command, camera brightness, ego dynamics, "
            "and optional structured hazards into Spotlight Reflex simulator scenarios."
        ),
        "cases": cases,
        "gates": gates,
        "boundary": (
            "This is a trajectory-plugin and structured-signal adapter. It is not a full "
            "photorealistic sensor/perception simulation claim."
        ),
    }


def _run_case(
    name: str,
    *,
    command: int,
    brightness: int,
    speed: float,
    acceleration: float,
    signal_attr: str | None,
    hazards: list[dict[str, Any]],
) -> dict[str, Any]:
    model = SpotlightReflexAlpaSimModel()
    prediction_input = _prediction_input(
        command=command,
        brightness=brightness,
        speed=speed,
        acceleration=acceleration,
        signal_attr=signal_attr,
        hazards=hazards,
    )
    signal = extract_alpasim_signal(prediction_input)
    command_name = model._encode_command(command)
    scenario = scenario_from_command(command_name, signal)
    prediction = model.predict(prediction_input)
    reasoning = json.loads(prediction.reasoning_text or "{}")
    trajectory = np.asarray(prediction.trajectory_xy)
    headings = np.asarray(prediction.headings)
    return {
        "name": name,
        "command": command_name,
        "camera_count": signal["camera_count"],
        "pose_history_len": signal["pose_history_len"],
        "structured_hazard_count": len(signal["structured_hazards"]),
        "signal_obstacle_count": len(scenario.obstacles),
        "signal_actor_count": len(scenario.actors),
        "visibility_risk": signal["visibility_risk"],
        "dynamics_risk": signal["dynamics_risk"],
        "selected_maneuver": reasoning.get("selected_maneuver"),
        "candidate_count": reasoning.get("candidate_count"),
        "reference_count": reasoning.get("reference_count"),
        "reasoning_has_signal": "alpasim_signal" in reasoning,
        "finite_20_point_trajectory": trajectory.shape == (20, 2)
        and headings.shape == (20,)
        and bool(np.isfinite(trajectory).all())
        and bool(np.isfinite(headings).all()),
    }


def _prediction_input(
    *,
    command: int,
    brightness: int,
    speed: float,
    acceleration: float,
    signal_attr: str | None,
    hazards: list[dict[str, Any]],
) -> SimpleNamespace:
    payload: dict[str, Any] = {
        "camera_images": {
            "camera_front_wide_120fov": [
                SimpleNamespace(image=np.full((8, 8, 3), brightness, dtype=np.uint8)),
            ]
        },
        "command": command,
        "speed": speed,
        "acceleration": acceleration,
        "ego_pose_history": [object()],
    }
    if signal_attr == "alpasignal":
        payload[signal_attr] = {"hazards": hazards}
    elif signal_attr is not None:
        payload[signal_attr] = hazards
    return SimpleNamespace(**payload)


if __name__ == "__main__":
    raise SystemExit(main())
