from __future__ import annotations

import math
from typing import Any

import numpy as np

from .environment import Actor, Obstacle, Scenario


def scenario_from_command(command: str, signal: dict[str, Any] | None = None) -> Scenario:
    signal = signal or {}
    lateral_goal = {"left": 16.0, "straight": 0.0, "right": -16.0}[command]
    route_waypoints = route_waypoints_from_signal(signal)
    real_route = len(route_waypoints) >= 2
    if real_route:
        lane_center = _lane_center_from_route_waypoints(route_waypoints)
        lane_half_width = float(signal.get("route_lane_half_width_m", 3.5))
        goal = lane_center[-1]
        max_x = max(abs(point[0]) for point in lane_center)
        max_y = max(abs(point[1]) for point in lane_center)
        width = max(100.0, max_x + 18.0)
        height = max(60.0, max_y * 2.0 + 18.0)
        route_source = "alpasim_waypoints"
    else:
        lane_center = [
            (0.0, 0.0),
            (18.0, lateral_goal * 0.12),
            (38.0, lateral_goal * 0.45),
            (62.0, lateral_goal * 0.82),
            (82.0, lateral_goal),
        ]
        lane_half_width = 6.0
        goal = (86.0, lateral_goal)
        width = 100.0
        height = 60.0
        route_source = "command_proxy"
    obstacles = signal_obstacles(signal)
    actors = signal_actors(signal)
    return Scenario(
        width=width,
        height=height,
        lane_center=lane_center,
        lane_half_width=lane_half_width,
        obstacles=obstacles,
        start=(0.0, 0.0),
        goal=goal,
        seed=0,
        cluster="alpasim_route_command",
        tags={
            "source": "alpasim_adapter",
            "route_command": command,
            "route_source": route_source,
            "route_waypoint_count": str(len(route_waypoints)),
            "signal_obstacle_count": str(len(obstacles)),
            "signal_actor_count": str(len(actors)),
            "visibility_risk": f"{float(signal.get('visibility_risk', 0.0)):.3f}",
            "dynamics_risk": f"{float(signal.get('dynamics_risk', 0.0)):.3f}",
        },
        actors=actors,
    )


def extract_alpasim_signal(prediction_input: Any) -> dict[str, Any]:
    structured_hazards = structured_hazards_from_input(prediction_input)
    route_waypoints = route_waypoints_from_input(prediction_input)
    visibility_risk = visibility_risk_from_cameras(prediction_input.camera_images)
    dynamics_risk_value = dynamics_risk(float(prediction_input.speed), float(prediction_input.acceleration))
    return {
        "structured_hazards": structured_hazards,
        "route_waypoints": route_waypoints,
        "route_waypoint_count": len(route_waypoints),
        "visibility_risk": round(visibility_risk, 6),
        "dynamics_risk": round(dynamics_risk_value, 6),
        "camera_count": len(prediction_input.camera_images),
        "pose_history_len": len(prediction_input.ego_pose_history),
    }


def route_waypoints_from_input(prediction_input: Any) -> list[dict[str, float]]:
    raw = _first_present_attr(
        prediction_input,
        ("route_waypoints", "route_path", "navigation_waypoints", "route"),
    )
    if raw is None:
        return []
    if hasattr(raw, "waypoints"):
        raw = getattr(raw, "waypoints")
    if isinstance(raw, dict):
        raw = raw.get("waypoints", raw.get("route_waypoints", []))
    if not isinstance(raw, (list, tuple)):
        try:
            raw = list(raw)
        except TypeError:
            return []
    waypoints: list[dict[str, float]] = []
    for item in raw:
        waypoint = _route_waypoint_from_item(item)
        if waypoint is not None:
            waypoints.append(waypoint)
    return waypoints


def route_waypoints_from_signal(signal: dict[str, Any]) -> list[dict[str, float]]:
    raw = signal.get("route_waypoints", [])
    if not isinstance(raw, list):
        return []
    waypoints: list[dict[str, float]] = []
    for item in raw:
        waypoint = _route_waypoint_from_item(item)
        if waypoint is not None:
            waypoints.append(waypoint)
    return waypoints


def _route_waypoint_from_item(item: Any) -> dict[str, float] | None:
    if isinstance(item, dict):
        x = item.get("x", item.get("forward_m", item.get("longitudinal_m")))
        y = item.get("y", item.get("left_m", item.get("lateral_m", 0.0)))
        z = item.get("z", 0.0)
    else:
        x = getattr(item, "x", getattr(item, "forward_m", getattr(item, "longitudinal_m", None)))
        y = getattr(item, "y", getattr(item, "left_m", getattr(item, "lateral_m", 0.0)))
        z = getattr(item, "z", 0.0)
    if x is None:
        return None
    x_f = float(x)
    y_f = float(y)
    z_f = float(z)
    if not (math.isfinite(x_f) and math.isfinite(y_f) and math.isfinite(z_f)):
        return None
    return {"x": round(x_f, 6), "y": round(y_f, 6), "z": round(z_f, 6)}


def _lane_center_from_route_waypoints(route_waypoints: list[dict[str, float]]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = [(0.0, 0.0)]
    for waypoint in route_waypoints:
        x = float(waypoint["x"])
        y = float(waypoint["y"])
        if x < -5.0:
            continue
        if math.hypot(x, y) > 140.0:
            continue
        if math.dist(points[-1], (x, y)) < 0.5:
            continue
        points.append((x, y))
    if len(points) < 2:
        return [(0.0, 0.0), (24.0, 0.0)]
    return points


def structured_hazards_from_input(prediction_input: Any) -> list[dict[str, float | str]]:
    raw = _first_present_attr(prediction_input, ("structured_hazards", "hazards", "traffic_hazards", "alpasignal"))
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = raw.get("hazards", raw.get("objects", []))
    hazards: list[dict[str, float | str]] = []
    if not isinstance(raw, list):
        return hazards
    for index, item in enumerate(raw):
        hazard = _hazard_from_item(item, index)
        if hazard is not None:
            hazards.append(hazard)
    return hazards


def visibility_risk_from_cameras(camera_images: dict[str, list[Any]]) -> float:
    means: list[float] = []
    for frames in camera_images.values():
        if not frames:
            continue
        image = getattr(frames[-1], "image", None)
        if image is None:
            continue
        array = np.asarray(image)
        if array.size == 0:
            continue
        means.append(float(array.mean()) / 255.0)
    if not means:
        return 0.0
    brightness = sum(means) / len(means)
    return max(0.0, min(1.0, (0.35 - brightness) / 0.35))


def dynamics_risk(speed_mps: float, acceleration_mps2: float) -> float:
    braking_risk = max(0.0, min(1.0, -acceleration_mps2 / 4.0))
    low_speed_risk = max(0.0, min(1.0, (1.5 - speed_mps) / 1.5))
    return max(braking_risk, low_speed_risk)


def signal_obstacles(signal: dict[str, Any]) -> list[Obstacle]:
    obstacles = [
        Obstacle(
            x=float(hazard["x"]),
            y=float(hazard["y"]),
            radius=float(hazard["radius"]),
            kind=str(hazard["kind"]),
            label=str(hazard["label"]),
            length=float(hazard["length"]) if "length" in hazard else None,
            heading=float(hazard.get("heading", 0.0)),
        )
        for hazard in signal.get("structured_hazards", [])
        if not _is_moving_hazard(hazard)
    ]
    visibility_risk = float(signal.get("visibility_risk", 0.0))
    dynamics_risk_value = float(signal.get("dynamics_risk", 0.0))
    if max(visibility_risk, dynamics_risk_value) >= 0.5 and not obstacles and not signal_actors(signal):
        obstacles.append(
            Obstacle(
                x=10.0 + 8.0 * dynamics_risk_value,
                y=0.0,
                radius=1.0 + 1.5 * max(visibility_risk, dynamics_risk_value),
                kind="caution_zone",
                label="alpasim_signal_caution",
            )
        )
    return obstacles


def signal_actors(signal: dict[str, Any]) -> list[Actor]:
    actors: list[Actor] = []
    for index, hazard in enumerate(signal.get("structured_hazards", [])):
        if not _is_moving_hazard(hazard):
            continue
        vx = float(hazard.get("vx", 0.0))
        vy = float(hazard.get("vy", 0.0))
        speed = math.hypot(vx, vy)
        radius = float(hazard["radius"])
        width = float(hazard.get("width", radius * 2.0))
        length = float(hazard.get("length", radius * 2.0))
        behavior = _hazard_behavior(hazard)
        heading = _hazard_heading(hazard, speed=speed, width=width, length=length, behavior=behavior)
        actors.append(
            Actor(
                actor_id=str(hazard.get("label", f"alpasignal_actor_{index}")),
                kind=str(hazard.get("kind", "signal_hazard")),
                x=float(hazard["x"]),
                y=float(hazard["y"]),
                width=width,
                length=length,
                heading=heading,
                speed=speed,
                vx=vx,
                vy=vy,
                behavior=behavior,
                role=str(hazard.get("label", f"alpasignal_actor_{index}")),
            )
        )
    return actors


def _hazard_from_item(item: Any, index: int) -> dict[str, float | str] | None:
    if isinstance(item, dict):
        x = item.get("x", item.get("forward_m", item.get("longitudinal_m")))
        y = item.get("y", item.get("left_m", item.get("lateral_m", 0.0)))
        radius = item.get("radius", item.get("radius_m", item.get("extent_m", 1.25)))
        width = item.get("width", item.get("width_m"))
        length = item.get("length", item.get("length_m"))
        heading = item.get("heading", item.get("heading_rad", item.get("yaw_rad", 0.0)))
        behavior = item.get("behavior", item.get("motion_behavior", item.get("intent")))
        acceleration = item.get("acceleration", item.get("acceleration_mps2", item.get("longitudinal_acceleration_mps2")))
        kind = item.get("kind", item.get("type", "signal_hazard"))
        label = item.get("label", item.get("id", f"alpasignal_{index}"))
        vx = item.get("vx", item.get("velocity_x_mps", item.get("forward_velocity_mps", 0.0)))
        vy = item.get("vy", item.get("velocity_y_mps", item.get("lateral_velocity_mps", 0.0)))
    else:
        x = getattr(item, "x", getattr(item, "forward_m", getattr(item, "longitudinal_m", None)))
        y = getattr(item, "y", getattr(item, "left_m", getattr(item, "lateral_m", 0.0)))
        radius = getattr(item, "radius", getattr(item, "radius_m", getattr(item, "extent_m", 1.25)))
        width = getattr(item, "width", getattr(item, "width_m", None))
        length = getattr(item, "length", getattr(item, "length_m", None))
        heading = getattr(item, "heading", getattr(item, "heading_rad", getattr(item, "yaw_rad", 0.0)))
        behavior = getattr(item, "behavior", getattr(item, "motion_behavior", getattr(item, "intent", None)))
        acceleration = getattr(
            item,
            "acceleration",
            getattr(item, "acceleration_mps2", getattr(item, "longitudinal_acceleration_mps2", None)),
        )
        kind = getattr(item, "kind", getattr(item, "type", "signal_hazard"))
        label = getattr(item, "label", getattr(item, "id", f"alpasignal_{index}"))
        vx = getattr(item, "vx", getattr(item, "velocity_x_mps", getattr(item, "forward_velocity_mps", 0.0)))
        vy = getattr(item, "vy", getattr(item, "velocity_y_mps", getattr(item, "lateral_velocity_mps", 0.0)))
    if x is None:
        return None
    hazard = {
        "x": float(x),
        "y": float(y),
        "radius": max(0.25, float(radius)),
        "kind": str(kind),
        "label": str(label),
        "vx": float(vx),
        "vy": float(vy),
    }
    if width is not None:
        hazard["width"] = max(0.25, float(width))
    if length is not None:
        hazard["length"] = max(0.25, float(length))
    if heading is not None:
        hazard["heading"] = float(heading)
    if behavior is not None:
        hazard["behavior"] = str(behavior)
    if acceleration is not None:
        hazard["acceleration"] = float(acceleration)
    return hazard


def _is_moving_hazard(hazard: dict[str, float | str]) -> bool:
    return abs(float(hazard.get("vx", 0.0))) > 1e-6 or abs(float(hazard.get("vy", 0.0))) > 1e-6


def _hazard_behavior(hazard: dict[str, float | str]) -> str:
    explicit = str(hazard.get("behavior", "")).strip().lower().replace("-", "_").replace(" ", "_")
    if explicit in {
        "linear",
        "cut_in",
        "swerve",
        "darting",
        "erratic_pedestrian",
        "sudden_brake",
        "hesitating",
        "wrong_way",
    }:
        return explicit

    signal = " ".join(
        str(hazard.get(key, ""))
        for key in ("label", "kind")
    ).lower().replace("-", "_").replace(" ", "_")
    if "wrong_way" in signal:
        return "wrong_way"
    if "cut_in" in signal or "cutin" in signal:
        return "cut_in"
    if "erratic_pedestrian" in signal or ("pedestrian" in signal and "erratic" in signal):
        return "erratic_pedestrian"
    if "dart" in signal or "animal" in signal:
        return "darting"
    if float(hazard.get("acceleration", 0.0)) <= -2.0:
        return "sudden_brake"
    if "sudden_brake" in signal or "hard_brake" in signal or "braking" in signal:
        return "sudden_brake"
    if (
        str(hazard.get("kind", "")).lower() == "pedestrian"
        and math.hypot(float(hazard.get("vx", 0.0)), float(hazard.get("vy", 0.0))) <= 0.6
    ):
        return "hesitating"
    if "hesitating" in signal or ("pedestrian" in signal and "crossing" in signal):
        return "hesitating"
    return "linear"


def _hazard_heading(
    hazard: dict[str, float | str],
    *,
    speed: float,
    width: float,
    length: float,
    behavior: str,
) -> float:
    explicit_heading = float(hazard.get("heading", 0.0))
    if speed <= 1e-6:
        return explicit_heading
    velocity_heading = math.atan2(float(hazard.get("vy", 0.0)), float(hazard.get("vx", 0.0)))
    if "heading" not in hazard:
        return velocity_heading
    elongated = length > width * 1.25
    if behavior in {"wrong_way", "cut_in", "sudden_brake"} or elongated:
        return explicit_heading
    return velocity_heading


def _first_present_attr(value: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None
