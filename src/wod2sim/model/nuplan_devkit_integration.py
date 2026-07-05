from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any
from typing import Iterable


DATABASE_INTERVAL_S = 0.05


@dataclass(frozen=True)
class NuPlanSceneFilter:
    db_files: tuple[str, ...] = ()
    log_names: tuple[str, ...] = ()
    map_names: tuple[str, ...] = ()
    scenario_tokens: tuple[str, ...] = ()
    scenario_types: tuple[str, ...] = ()
    limit: int | None = None


def load_nuplan_scenes(
    *,
    data_root: Path,
    scene_filter: NuPlanSceneFilter,
    future_horizon_s: float = 4.0,
    future_interval_s: float = 0.5,
) -> list[dict[str, Any]]:
    imports = _nuplan_imports()
    discovered = _discover_db_files(data_root=data_root, db_files=scene_filter.db_files)
    scenes: list[dict[str, Any]] = []
    sample_indexes = _future_sample_indexes(future_horizon_s=future_horizon_s, future_interval_s=future_interval_s)
    for log_file in discovered:
        if scene_filter.log_names and Path(log_file).name not in scene_filter.log_names:
            continue
        rows = imports["get_scenarios_from_db"](
            log_file,
            list(scene_filter.scenario_tokens) or None,
            list(scene_filter.scenario_types) or None,
            list(scene_filter.map_names) or None,
            True,
            False,
        )
        for row in rows:
            token = str(row["token"].hex())
            ego = imports["get_ego_state_for_lidarpc_token_from_db"](log_file, token)
            if ego is None:
                continue
            mission_goal = imports["get_mission_goal_for_sensor_data_token_from_db"](
                log_file,
                imports["get_lidarpc_sensor_data"](),
                token,
            )
            future_states = list(
                imports["get_sampled_ego_states_from_db"](
                    log_file,
                    token,
                    imports["get_lidarpc_sensor_data"](),
                    sample_indexes,
                    True,
                )
            )
            if not future_states:
                continue
            tracked_objects = list(imports["get_tracked_objects_for_lidarpc_token_from_db"](log_file, token))
            sensor_timestamp_us = int(
                imports["get_sensor_data_token_timestamp_from_db"](
                    log_file,
                    imports["get_lidarpc_sensor_data"](),
                    token,
                )
                or 0
            )
            scenes.append(
                build_nuplan_scene_summary(
                    log_file=log_file,
                    token=token,
                    scenario_type=str(row["scenario_type"] or "unknown"),
                    map_name=str(row["map_name"]),
                    sensor_timestamp_us=sensor_timestamp_us,
                    ego=ego,
                    mission_goal=mission_goal,
                    future_states=future_states,
                    tracked_objects=tracked_objects,
                )
            )
            if scene_filter.limit is not None and len(scenes) >= scene_filter.limit:
                return scenes
    return scenes


def build_nuplan_scene_summary(
    *,
    log_file: str,
    token: str,
    scenario_type: str,
    map_name: str,
    sensor_timestamp_us: int,
    ego: Any,
    mission_goal: Any,
    future_states: list[Any],
    tracked_objects: list[Any],
) -> dict[str, Any]:
    route_command, heading_error_rad, route_remaining_m = _route_features_from_goal(
        ego=ego,
        mission_goal=mission_goal,
        future_states=future_states,
    )
    actors = [_actor_row(ego=ego, tracked_object=obj) for obj in tracked_objects]
    expert_trajectory = [_ego_future_row(ego=ego, state=state) for state in future_states]
    return {
        "scene_id": f"{Path(log_file).stem}:{token}",
        "source_db_file": str(log_file),
        "log_name": Path(log_file).name,
        "scenario_token": token,
        "scenario_type": scenario_type,
        "map_name": map_name,
        "sensor_timestamp_us": int(sensor_timestamp_us),
        "ego_state": {
            "speed_mps": _speed_mps(ego),
            "x_m": float(ego.rear_axle.x),
            "y_m": float(ego.rear_axle.y),
            "heading_rad": float(ego.rear_axle.heading),
        },
        "route": {
            "command": route_command,
            "heading_error_rad": heading_error_rad,
            "lane_offset_m": 0.0,
            "remaining_distance_m": route_remaining_m,
        },
        "actors": actors,
        "expert_trajectory": expert_trajectory,
    }


def _route_features_from_goal(*, ego: Any, mission_goal: Any, future_states: list[Any]) -> tuple[str, float, float]:
    if mission_goal is not None:
        goal_x, goal_y = _global_to_local(
            x=float(mission_goal.x),
            y=float(mission_goal.y),
            origin_x=float(ego.rear_axle.x),
            origin_y=float(ego.rear_axle.y),
            origin_heading=float(ego.rear_axle.heading),
        )
        heading_error_rad = math.atan2(goal_y, max(1.0e-6, goal_x))
        route_remaining_m = math.hypot(goal_x, goal_y)
        command = _turn_command(goal_y)
        return command, float(heading_error_rad), float(route_remaining_m)
    if not future_states:
        return "straight", 0.0, 0.0
    final_local = _ego_future_row(ego=ego, state=future_states[-1])
    heading_error_rad = math.atan2(float(final_local["y_m"]), max(1.0e-6, float(final_local["x_m"])))
    route_remaining_m = math.hypot(float(final_local["x_m"]), float(final_local["y_m"]))
    return _turn_command(float(final_local["y_m"])), float(heading_error_rad), float(route_remaining_m)


def _actor_row(*, ego: Any, tracked_object: Any) -> dict[str, Any]:
    center = tracked_object.center
    x_local, y_local = _global_to_local(
        x=float(center.x),
        y=float(center.y),
        origin_x=float(ego.rear_axle.x),
        origin_y=float(ego.rear_axle.y),
        origin_heading=float(ego.rear_axle.heading),
    )
    vx_local, vy_local = _rotate_into_local(
        x=float(getattr(tracked_object.velocity, "x", 0.0)),
        y=float(getattr(tracked_object.velocity, "y", 0.0)),
        heading=float(ego.rear_axle.heading),
    )
    box = tracked_object.box
    radius = 0.5 * math.hypot(float(box.width), float(box.length))
    return {
        "token": str(tracked_object.metadata.track_token or tracked_object.metadata.token),
        "type": str(tracked_object.tracked_object_type.name).lower(),
        "x_m": float(x_local),
        "y_m": float(y_local),
        "vx_mps": float(vx_local),
        "vy_mps": float(vy_local),
        "radius_m": float(radius),
        "visible": True,
    }


def _ego_future_row(*, ego: Any, state: Any) -> dict[str, float]:
    x_local, y_local = _global_to_local(
        x=float(state.rear_axle.x),
        y=float(state.rear_axle.y),
        origin_x=float(ego.rear_axle.x),
        origin_y=float(ego.rear_axle.y),
        origin_heading=float(ego.rear_axle.heading),
    )
    heading_local = _normalize_angle(float(state.rear_axle.heading) - float(ego.rear_axle.heading))
    return {
        "x_m": float(x_local),
        "y_m": float(y_local),
        "heading_rad": float(heading_local),
    }


def _future_sample_indexes(*, future_horizon_s: float, future_interval_s: float) -> list[int]:
    sample_count = max(1, int(round(future_horizon_s / max(future_interval_s, 1.0e-6))))
    return [
        max(0, int(round((index + 1) * future_interval_s / DATABASE_INTERVAL_S)) - 1)
        for index in range(sample_count)
    ]


def _discover_db_files(*, data_root: Path, db_files: tuple[str, ...]) -> list[str]:
    if db_files:
        discovered: list[str] = []
        for value in db_files:
            candidate = Path(value)
            if candidate.is_file():
                discovered.append(str(candidate))
                continue
            if candidate.is_dir():
                discovered.extend(str(path) for path in sorted(candidate.rglob("*.db")))
                continue
            rooted = data_root / value
            if rooted.is_file():
                discovered.append(str(rooted))
            elif rooted.is_dir():
                discovered.extend(str(path) for path in sorted(rooted.rglob("*.db")))
            else:
                raise FileNotFoundError(value)
        return list(dict.fromkeys(discovered))
    return [str(path) for path in sorted(data_root.rglob("*.db"))]


def _nuplan_imports() -> dict[str, Any]:
    try:
        from nuplan.database.nuplan_db.nuplan_db_utils import get_lidarpc_sensor_data
        from nuplan.database.nuplan_db.nuplan_scenario_queries import get_ego_state_for_lidarpc_token_from_db
        from nuplan.database.nuplan_db.nuplan_scenario_queries import get_mission_goal_for_sensor_data_token_from_db
        from nuplan.database.nuplan_db.nuplan_scenario_queries import get_sampled_ego_states_from_db
        from nuplan.database.nuplan_db.nuplan_scenario_queries import get_scenarios_from_db
        from nuplan.database.nuplan_db.nuplan_scenario_queries import get_sensor_data_token_timestamp_from_db
        from nuplan.database.nuplan_db.nuplan_scenario_queries import get_tracked_objects_for_lidarpc_token_from_db
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only outside nuPlan installs.
        raise ImportError(
            "nuPlan devkit is not installed. Run `./scripts/bootstrap_nuplan_env.sh` "
            "or install the required nuPlan dependencies into the active environment."
        ) from exc

    return {
        "get_ego_state_for_lidarpc_token_from_db": get_ego_state_for_lidarpc_token_from_db,
        "get_lidarpc_sensor_data": get_lidarpc_sensor_data,
        "get_mission_goal_for_sensor_data_token_from_db": get_mission_goal_for_sensor_data_token_from_db,
        "get_sampled_ego_states_from_db": get_sampled_ego_states_from_db,
        "get_scenarios_from_db": get_scenarios_from_db,
        "get_sensor_data_token_timestamp_from_db": get_sensor_data_token_timestamp_from_db,
        "get_tracked_objects_for_lidarpc_token_from_db": get_tracked_objects_for_lidarpc_token_from_db,
    }


def _speed_mps(ego: Any) -> float:
    velocity = ego.dynamic_car_state.rear_axle_velocity_2d
    return float(math.hypot(float(velocity.x), float(velocity.y)))


def _turn_command(lateral_m: float) -> str:
    if lateral_m > 1.0:
        return "left"
    if lateral_m < -1.0:
        return "right"
    return "straight"


def _global_to_local(
    *,
    x: float,
    y: float,
    origin_x: float,
    origin_y: float,
    origin_heading: float,
) -> tuple[float, float]:
    dx = x - origin_x
    dy = y - origin_y
    return _rotate_into_local(x=dx, y=dy, heading=origin_heading)


def _rotate_into_local(*, x: float, y: float, heading: float) -> tuple[float, float]:
    cos_h = math.cos(heading)
    sin_h = math.sin(heading)
    return (cos_h * x + sin_h * y, -sin_h * x + cos_h * y)


def _normalize_angle(value: float) -> float:
    return math.atan2(math.sin(value), math.cos(value))
