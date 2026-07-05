from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from wod2sim.simulator.environment import Actor, Obstacle, Scenario, scenario_at_state


def load_rollout_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"expected dict payload in {path}")
    for key in ("scenario", "architecture", "rollout"):
        if key not in payload:
            raise ValueError(f"missing {key!r} in rollout payload {path}")
    return payload


def reconstruct_scenario(payload: dict[str, Any]) -> Scenario:
    scenario = payload["scenario"]
    obstacles = [Obstacle(**item) for item in scenario.get("obstacles", [])]
    actors = [Actor(**item) for item in scenario.get("actors", [])]
    return Scenario(
        width=float(scenario["width"]),
        height=float(scenario["height"]),
        lane_center=[(float(x), float(y)) for x, y in scenario["lane_center"]],
        lane_half_width=float(scenario["lane_half_width"]),
        obstacles=obstacles,
        start=(float(scenario["start"][0]), float(scenario["start"][1])),
        goal=(float(scenario["goal"][0]), float(scenario["goal"][1])),
        seed=int(scenario["seed"]),
        cluster=str(scenario.get("cluster", "baseline")),
        tags=dict(scenario.get("tags", {})),
        actors=actors,
        map_features=list(scenario.get("map_features", [])),
        environment=dict(scenario.get("environment", {})),
    )


def build_audit_frames(payload: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = reconstruct_scenario(payload)
    steps = list(payload["rollout"].get("steps", []))
    runtime_state: dict[str, object] = {}
    frames: list[dict[str, Any]] = []
    for step in steps:
        tick = int(step["t"])
        ego_position = (float(step["x"]), float(step["y"]))
        active_scenario, runtime_state = scenario_at_state(scenario, tick=tick, position=ego_position, runtime_state=runtime_state)
        frames.append(
            {
                "frame_idx": tick,
                "timestamp_s": round(tick * 0.25, 3),
                "ego": {
                    "x": ego_position[0],
                    "y": ego_position[1],
                    "speed": float(step.get("speed", 0.0)),
                    "goal_distance": float(step.get("goal_distance", 0.0) or 0.0),
                },
                "route": {
                    "start": list(scenario.start),
                    "goal": list(scenario.goal),
                    "lane_center": [list(point) for point in scenario.lane_center],
                    "lane_half_width": float(scenario.lane_half_width),
                    "map_features": active_scenario.map_features,
                },
                "actors": [asdict(actor) for actor in scenario.actors],
                "active_obstacles": [asdict(obstacle) for obstacle in active_scenario.obstacles],
                "media": [],
                "step": step,
                "trigger_state": dict(active_scenario.environment.get("runtime_actor_windows", {})),
            }
        )
    return frames
