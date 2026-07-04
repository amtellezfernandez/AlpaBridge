from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from dataclasses import dataclass
import math
from typing import Any

import numpy as np


TOKEN_ORDER = (
    "stop",
    "crawl",
    "maintain",
    "slow_yield",
    "nudge_left",
    "nudge_right",
    "evasive_left",
    "evasive_right",
    "lane_recover",
)

EXPANDED_TOKEN_ORDER = TOKEN_ORDER + (
    "micro_creep",
    "brake_left",
    "brake_right",
    "creep_left",
    "creep_right",
    "wide_left",
    "wide_right",
    "wide_left_crawl",
    "wide_right_crawl",
    "fast_left",
    "fast_right",
    "reverse_creep",
)

_TOKEN_SPECS = {
    "stop": (0.0, 0.0, "smooth"),
    "crawl": (0.15, 0.0, "smooth"),
    "maintain": (1.0, 0.0, "smooth"),
    "slow_yield": (0.5, 0.0, "smooth"),
    "nudge_left": (0.8, 0.9, "smooth"),
    "nudge_right": (0.8, -0.9, "smooth"),
    "evasive_left": (0.7, 2.2, "early"),
    "evasive_right": (0.7, -2.2, "early"),
    "lane_recover": (0.9, 0.0, "smooth"),
    "micro_creep": (0.05, 0.0, "smooth"),
    "brake_left": (0.35, 1.2, "smooth"),
    "brake_right": (0.35, -1.2, "smooth"),
    "creep_left": (0.15, 1.7, "smooth"),
    "creep_right": (0.15, -1.7, "smooth"),
    "wide_left": (0.55, 3.4, "early"),
    "wide_right": (0.55, -3.4, "early"),
    "wide_left_crawl": (0.20, 3.2, "early"),
    "wide_right_crawl": (0.20, -3.2, "early"),
    "fast_left": (1.05, 2.4, "early"),
    "fast_right": (1.05, -2.4, "early"),
    "reverse_creep": (-0.10, 0.0, "smooth"),
}

_ESCAPE_SIDE_TO_FLOAT = {"left": 1.0, "center": 0.0, "right": -1.0}


@dataclass(frozen=True)
class NuPlanScalarState:
    obstacle_pressure: float
    route_blockage: float
    corridor_blocked: bool
    left_clearance_m: float
    right_clearance_m: float
    preferred_escape_side: str


@dataclass(frozen=True)
class NuPlanRouteFeatures:
    route_command: str
    heading_error_rad: float
    lane_offset_m: float
    route_remaining_m: float


@dataclass(frozen=True)
class NuPlanActorSummary:
    actor_count: int
    visible_actor_count: int
    nearest_actor_distance_m: float
    leading_actor_distance_m: float
    rear_closing_actor_count: int
    crossing_actor_count: int


@dataclass(frozen=True)
class ManeuverTokenCandidate:
    token: str
    speed_scale: float
    lateral_offset_m: float
    profile: str
    proxy_safe: bool
    min_proxy_clearance_m: float
    final_progress_m: float
    score: float
    poses: tuple[tuple[float, float, float], ...]
    per_frame_diagnostics: tuple[dict[str, float], ...]


def extract_scalar_state(scene: Mapping[str, Any] | Any) -> NuPlanScalarState:
    ego = _ego_state(scene)
    actors = _visible_actors(scene)
    nearest_distance = min((_distance_m(actor) for actor in actors), default=math.inf)
    left_clearance = min(
        (_side_clearance(actor) for actor in actors if _actor_lateral_m(actor) > 0.0),
        default=20.0,
    )
    right_clearance = min(
        (_side_clearance(actor) for actor in actors if _actor_lateral_m(actor) < 0.0),
        default=20.0,
    )
    route_blockage = _route_blockage(ego, actors)
    corridor_blocked = _corridor_blocked(ego, actors)
    if left_clearance > right_clearance + 0.25:
        preferred_escape_side = "left"
    elif right_clearance > left_clearance + 0.25:
        preferred_escape_side = "right"
    else:
        preferred_escape_side = "center"
    return NuPlanScalarState(
        obstacle_pressure=_clip01((10.0 - nearest_distance) / 10.0) if math.isfinite(nearest_distance) else 0.0,
        route_blockage=route_blockage,
        corridor_blocked=corridor_blocked,
        left_clearance_m=float(left_clearance),
        right_clearance_m=float(right_clearance),
        preferred_escape_side=preferred_escape_side,
    )


def extract_route_features(scene: Mapping[str, Any] | Any) -> NuPlanRouteFeatures:
    route = _route_state(scene)
    return NuPlanRouteFeatures(
        route_command=str(_get_value(route, "command", "straight")).lower(),
        heading_error_rad=float(_get_value(route, "heading_error_rad", 0.0)),
        lane_offset_m=float(_get_value(route, "lane_offset_m", 0.0)),
        route_remaining_m=float(_get_value(route, "remaining_distance_m", 30.0)),
    )


def summarize_actors(scene: Mapping[str, Any] | Any) -> NuPlanActorSummary:
    actors = _actors(scene)
    visible = [actor for actor in actors if bool(_get_value(actor, "visible", True))]
    nearest_distance = min((_distance_m(actor) for actor in visible), default=math.inf)
    leading_distance = min(
        (_distance_m(actor) for actor in visible if _actor_forward_m(actor) >= 0.0),
        default=math.inf,
    )
    rear_closing = 0
    crossing = 0
    for actor in visible:
        vx = float(_get_value(actor, "vx_mps", 0.0))
        vy = float(_get_value(actor, "vy_mps", 0.0))
        if _actor_forward_m(actor) < -1.0 and vx > 1.0:
            rear_closing += 1
        if abs(vy) > 1.0 and abs(_actor_forward_m(actor)) <= 12.0:
            crossing += 1
    return NuPlanActorSummary(
        actor_count=len(actors),
        visible_actor_count=len(visible),
        nearest_actor_distance_m=_finite_or(nearest_distance, 50.0),
        leading_actor_distance_m=_finite_or(leading_distance, 50.0),
        rear_closing_actor_count=rear_closing,
        crossing_actor_count=crossing,
    )


def six_scalar_vector(state: NuPlanScalarState) -> tuple[float, float, float, float, float, float]:
    return (
        float(state.obstacle_pressure),
        float(state.route_blockage),
        1.0 if state.corridor_blocked else 0.0,
        float(state.left_clearance_m),
        float(state.right_clearance_m),
        _ESCAPE_SIDE_TO_FLOAT[state.preferred_escape_side],
    )


def build_maneuver_token_candidates(
    scene: Mapping[str, Any] | Any,
    *,
    horizon_s: float = 4.0,
    dt_s: float = 0.5,
    candidate_profile: str = "base",
) -> list[ManeuverTokenCandidate]:
    token_order = _token_order_for_profile(candidate_profile)
    scalar_state = extract_scalar_state(scene)
    route = extract_route_features(scene)
    actor_summary = summarize_actors(scene)
    ego = _ego_state(scene)
    speed_mps = max(0.0, float(_get_value(ego, "speed_mps", 0.0)))
    num_poses = max(1, int(round(horizon_s / max(dt_s, 1e-6))))
    candidates = []
    for token in token_order:
        speed_scale, base_lateral, profile = _TOKEN_SPECS[token]
        lateral_offset = _token_lateral_offset(token, base_lateral, route)
        poses = _maneuver_token_poses(
            speed_mps=speed_mps,
            speed_scale=speed_scale,
            lateral_offset_m=lateral_offset,
            profile=profile,
            num_poses=num_poses,
            interval_length_s=dt_s,
        )
        diagnostics = _candidate_proxy_diagnostics(poses, _visible_actors(scene))
        min_clearance = min((frame["proxy_clearance_m"] for frame in diagnostics), default=math.inf)
        score = _candidate_score(
            token=token,
            scalar_state=scalar_state,
            route=route,
            actor_summary=actor_summary,
            min_proxy_clearance_m=min_clearance,
            final_progress_m=float(poses[-1][0]),
        )
        candidates.append(
            ManeuverTokenCandidate(
                token=token,
                speed_scale=speed_scale,
                lateral_offset_m=float(lateral_offset),
                profile=profile,
                proxy_safe=min_clearance >= 0.0,
                min_proxy_clearance_m=_finite_or(min_clearance, 50.0),
                final_progress_m=float(poses[-1][0]),
                score=float(score),
                poses=tuple((float(x), float(y), float(heading)) for x, y, heading in poses),
                per_frame_diagnostics=tuple(diagnostics),
            )
        )
    return candidates


def select_maneuver_token(
    scene: Mapping[str, Any] | Any,
    *,
    candidate_profile: str = "base",
) -> ManeuverTokenCandidate:
    candidates = build_maneuver_token_candidates(scene, candidate_profile=candidate_profile)
    return max(
        candidates,
        key=lambda candidate: (candidate.score, candidate.min_proxy_clearance_m, candidate.final_progress_m),
    )


def build_scene_diagnostic_record(
    scene: Mapping[str, Any] | Any,
    *,
    candidate_profile: str = "base",
) -> dict[str, Any]:
    rollout_dt_s = 0.5
    rollout_horizon_s = 4.0
    scalar_state = extract_scalar_state(scene)
    route = extract_route_features(scene)
    actor_summary = summarize_actors(scene)
    candidates = build_maneuver_token_candidates(
        scene,
        horizon_s=rollout_horizon_s,
        dt_s=rollout_dt_s,
        candidate_profile=candidate_profile,
    )
    selected = max(
        candidates,
        key=lambda candidate: (candidate.score, candidate.min_proxy_clearance_m, candidate.final_progress_m),
    )
    return {
        "scene_id": str(_get_value(scene, "scene_id", "unknown_scene")),
        "source_db_file": _get_value(scene, "source_db_file", None),
        "log_name": _get_value(scene, "log_name", None),
        "scenario_token": _get_value(scene, "scenario_token", None),
        "scenario_type": _get_value(scene, "scenario_type", None),
        "map_name": _get_value(scene, "map_name", None),
        "sensor_timestamp_us": _get_value(scene, "sensor_timestamp_us", None),
        "six_scalar_state": {
            **asdict(scalar_state),
            "vector": [round(value, 6) for value in six_scalar_vector(scalar_state)],
        },
        "route_features": asdict(route),
        "actor_summary": asdict(actor_summary),
        "candidate_count": len(candidates),
        "candidate_profile": candidate_profile,
        "selected_token_rollout_dt_s": rollout_dt_s,
        "selected_token_rollout_horizon_s": rollout_horizon_s,
        "selected_token": selected.token,
        "selected_token_proxy_safe": selected.proxy_safe,
        "selected_token_min_proxy_clearance_m": round(selected.min_proxy_clearance_m, 6),
        "selected_token_score": round(selected.score, 6),
        "candidates": [_candidate_to_dict(candidate) for candidate in candidates],
        "selected_token_rollout": _candidate_to_dict(selected),
    }


def _candidate_to_dict(candidate: ManeuverTokenCandidate) -> dict[str, Any]:
    return {
        "token": candidate.token,
        "speed_scale": round(candidate.speed_scale, 6),
        "lateral_offset_m": round(candidate.lateral_offset_m, 6),
        "profile": candidate.profile,
        "proxy_safe": candidate.proxy_safe,
        "min_proxy_clearance_m": round(candidate.min_proxy_clearance_m, 6),
        "final_progress_m": round(candidate.final_progress_m, 6),
        "score": round(candidate.score, 6),
        "poses": [[round(value, 6) for value in pose] for pose in candidate.poses],
        "per_frame_diagnostics": [
            {key: round(float(value), 6) for key, value in frame.items()}
            for frame in candidate.per_frame_diagnostics
        ],
    }


def _candidate_score(
    *,
    token: str,
    scalar_state: NuPlanScalarState,
    route: NuPlanRouteFeatures,
    actor_summary: NuPlanActorSummary,
    min_proxy_clearance_m: float,
    final_progress_m: float,
) -> float:
    score = final_progress_m
    score += min(2.5, max(-1.0, min_proxy_clearance_m))
    score -= abs(route.lane_offset_m) * (0.6 if token == "lane_recover" else 0.2)
    score -= abs(route.heading_error_rad) * 0.5
    score -= scalar_state.obstacle_pressure * 2.0 if token == "maintain" else 0.0
    if min_proxy_clearance_m < 0.0:
        score -= 12.0 + 4.0 * abs(min_proxy_clearance_m)
    elif min_proxy_clearance_m < 0.5:
        score -= 2.0 * (0.5 - min_proxy_clearance_m)
    score -= 1.5 if token == "stop" and scalar_state.obstacle_pressure < 0.3 else 0.0
    if scalar_state.corridor_blocked:
        if scalar_state.preferred_escape_side == "left":
            score += 2.5 if token in {"nudge_left", "evasive_left"} else 0.0
            score -= 2.0 if token in {"nudge_right", "evasive_right"} else 0.0
        elif scalar_state.preferred_escape_side == "right":
            score += 2.5 if token in {"nudge_right", "evasive_right"} else 0.0
            score -= 2.0 if token in {"nudge_left", "evasive_left"} else 0.0
        else:
            score += 1.5 if token in {"slow_yield", "crawl"} else 0.0
        score -= 3.0 if token == "maintain" else 0.0
    if actor_summary.crossing_actor_count > 0:
        score += 1.0 if token in {"crawl", "slow_yield"} else 0.0
    if actor_summary.rear_closing_actor_count > 0:
        score -= 0.5 if token == "stop" else 0.0
    if route.route_command == "left":
        score += 0.5 if token in {"nudge_left", "evasive_left"} else 0.0
    elif route.route_command == "right":
        score += 0.5 if token in {"nudge_right", "evasive_right"} else 0.0
    return score


def _token_order_for_profile(candidate_profile: str) -> tuple[str, ...]:
    if candidate_profile == "base":
        return TOKEN_ORDER
    if candidate_profile == "expanded":
        return EXPANDED_TOKEN_ORDER
    raise ValueError(f"unknown nuPlan ManeuverToken candidate profile: {candidate_profile!r}")


def _candidate_proxy_diagnostics(
    poses: np.ndarray,
    actors: list[Any],
) -> tuple[dict[str, float], ...]:
    diagnostics = []
    for index, (x, y, heading) in enumerate(poses):
        min_clearance = math.inf
        for actor in actors:
            dx = float(x) - _actor_forward_m(actor)
            dy = float(y) - _actor_lateral_m(actor)
            clearance = math.hypot(dx, dy) - 1.0 - float(_get_value(actor, "radius_m", 1.0))
            min_clearance = min(min_clearance, clearance)
        diagnostics.append(
            {
                "step": float(index),
                "x_m": float(x),
                "y_m": float(y),
                "heading_rad": float(heading),
                "proxy_clearance_m": _finite_or(min_clearance, 50.0),
            }
        )
    return tuple(diagnostics)


def _maneuver_token_poses(
    *,
    speed_mps: float,
    speed_scale: float,
    lateral_offset_m: float,
    profile: str,
    num_poses: int,
    interval_length_s: float,
) -> np.ndarray:
    poses = []
    previous_x = 0.0
    previous_y = 0.0
    forward_speed = speed_mps * speed_scale
    for index in range(num_poses):
        t = (index + 1) * interval_length_s
        horizon_ratio = (index + 1) / max(1, num_poses)
        x = forward_speed * t
        blend = _smoothstep(min(1.0, horizon_ratio * 2.5)) if profile == "early" else _smoothstep(horizon_ratio)
        y = lateral_offset_m * blend
        heading = math.atan2(y - previous_y, max(1e-6, x - previous_x))
        poses.append((x, y, heading))
        previous_x = x
        previous_y = y
    return np.asarray(poses, dtype=np.float32)


def _token_lateral_offset(token: str, base_lateral: float, route: NuPlanRouteFeatures) -> float:
    if token == "lane_recover":
        return -route.lane_offset_m
    if token in {"maintain", "slow_yield", "crawl", "stop"}:
        return 0.0
    route_bias = 0.0
    if route.route_command == "left":
        route_bias = 0.2 if "left" in token else -0.1 if "right" in token else 0.0
    elif route.route_command == "right":
        route_bias = -0.2 if "right" in token else 0.1 if "left" in token else 0.0
    return base_lateral + route_bias


def _route_blockage(ego: Any, actors: list[Any]) -> float:
    visibility_horizon = max(8.0, float(_get_value(ego, "speed_mps", 0.0)) * 2.0 + 4.0)
    occupied = 0
    total = 0
    for actor in actors:
        forward = _actor_forward_m(actor)
        lateral = abs(_actor_lateral_m(actor))
        if 0.0 <= forward <= visibility_horizon:
            total += 1
            if lateral <= 1.75:
                occupied += 1
    return 0.0 if total == 0 else occupied / total


def _corridor_blocked(ego: Any, actors: list[Any]) -> bool:
    speed_mps = float(_get_value(ego, "speed_mps", 0.0))
    stopping_distance = speed_mps * 1.5 + 0.5 * speed_mps * speed_mps / 4.0
    for actor in actors:
        forward = _actor_forward_m(actor)
        lateral = abs(_actor_lateral_m(actor))
        if 0.0 <= forward <= stopping_distance and lateral <= 1.4:
            return True
    return False


def _visible_actors(scene: Mapping[str, Any] | Any) -> list[Any]:
    return [actor for actor in _actors(scene) if bool(_get_value(actor, "visible", True))]


def _actors(scene: Mapping[str, Any] | Any) -> list[Any]:
    actors = _get_value(scene, "actors", [])
    return list(actors)


def _ego_state(scene: Mapping[str, Any] | Any) -> Any:
    ego = _get_value(scene, "ego_state", None)
    if ego is None:
        return {}
    return ego


def _route_state(scene: Mapping[str, Any] | Any) -> Any:
    route = _get_value(scene, "route", None)
    if route is None:
        return {}
    return route


def _actor_forward_m(actor: Any) -> float:
    return float(_get_value(actor, "x_m", _get_value(actor, "forward_m", 0.0)))


def _actor_lateral_m(actor: Any) -> float:
    return float(_get_value(actor, "y_m", _get_value(actor, "lateral_m", 0.0)))


def _distance_m(actor: Any) -> float:
    return math.hypot(_actor_forward_m(actor), _actor_lateral_m(actor))


def _side_clearance(actor: Any) -> float:
    return max(0.0, abs(_actor_lateral_m(actor)) - float(_get_value(actor, "radius_m", 1.0)) - 1.0)


def _get_value(container: Any, key: str, default: Any) -> Any:
    if isinstance(container, Mapping):
        return container.get(key, default)
    return getattr(container, key, default)


def _smoothstep(value: float) -> float:
    x = max(0.0, min(1.0, value))
    return x * x * (3.0 - 2.0 * x)


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _finite_or(value: float, fallback: float) -> float:
    return float(value) if math.isfinite(value) else float(fallback)
