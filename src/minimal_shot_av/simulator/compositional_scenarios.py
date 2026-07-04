from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
from typing import Any

from .environment import Actor, Obstacle, Scenario
from .wod_scenarios import _repair_static_corridor


COMPOSITIONAL_TOPOLOGIES = (
    "straight",
    "s_bend",
    "roundabout_entry",
    "rural_single_track",
    "industrial_yard",
    "worksite_chicane",
)

COMPOSITIONAL_HAZARDS = (
    "debris_object",
    "animal_crossing",
    "occluded_pedestrian",
    "cut_in_vehicle",
    "emergency_vehicle",
    "wrong_way_vehicle",
    "stalled_vehicle",
    "construction_taper",
    "novel_object",
)

COMPOSITIONAL_CONDITIONS = (
    "clear",
    "rain",
    "low_light",
    "glare",
    "mist",
    "wet_surface",
)

COMPOSITIONAL_SUITES = ("compositional", "adversarial", "gauntlet", "hidden")

GAUNTLET_HAZARD_SETS = (
    ("wrong_way_vehicle", "cut_in_vehicle", "occluded_pedestrian", "debris_object"),
    ("emergency_vehicle", "animal_crossing", "construction_taper", "novel_object"),
    ("wrong_way_vehicle", "emergency_vehicle", "stalled_vehicle", "occluded_pedestrian"),
    ("cut_in_vehicle", "animal_crossing", "novel_object", "construction_taper"),
)

SUITE_PRESSURE = {
    "compositional": 1.0,
    "hidden": 1.15,
    "adversarial": 1.65,
    "gauntlet": 2.35,
}


@dataclass(frozen=True)
class CorridorClearanceConfig:
    rural_single_track: float = 1.1
    static_blocker: float = 1.45
    default: float = 1.9


@dataclass(frozen=True)
class DifficultyConfig:
    base: float = 0.35
    per_hazard: float = 0.16
    gauntlet_bonus: float = 0.28
    adversarial_bonus: float = 0.12
    poor_condition_bonus: float = 0.12
    complex_topology_bonus: float = 0.08


@dataclass(frozen=True)
class TopologyGeometryConfig:
    lane_half_width_ranges: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "rural_single_track": (4.8, 5.8),
            "industrial_yard": (6.0, 7.4),
            "worksite_chicane": (6.0, 7.4),
            "roundabout_entry": (7.0, 8.4),
            "default": (7.2, 9.4),
        }
    )
    lane_control_points: int = 9
    route_x_margin_m: float = 12.0
    start_goal_padding_m: float = 4.0
    center_y_fraction: float = 0.5
    straight_jitter_m: float = 1.2
    s_bend_amplitude_m: float = 11.0
    s_bend_jitter_m: float = 1.0
    roundabout_cos_amplitude_m: float = 6.0
    roundabout_sin_amplitude_m: float = 5.0
    roundabout_sin_frequency: float = 1.5
    rural_amplitude_m: float = 8.0
    rural_frequency: float = 1.7
    rural_jitter_m: float = 2.0
    industrial_y_jitter_m: tuple[float, float] = (1.0, 3.0)
    worksite_chicane_amplitude_m: float = 9.0
    roundabout_feature_radius_m: float = 14.0
    rural_pullout_width_scale: float = 0.8
    industrial_speed_limit_mps: float = 6.0
    temporary_alignment_length_m: float = 35.0
    narrow_corridor_half_width_m: float = 6.0


@dataclass(frozen=True)
class HazardGeometryConfig:
    crossing_start_scale: dict[str, float] = field(
        default_factory=lambda: {"gauntlet": 0.48, "adversarial": 0.72, "default": 0.95}
    )
    cut_in_start_scale: dict[str, float] = field(
        default_factory=lambda: {"gauntlet": 0.45, "adversarial": 0.72, "default": 1.05}
    )
    cut_in_heading_delta_rad: dict[str, float] = field(
        default_factory=lambda: {"gauntlet": 0.85, "adversarial": 0.65, "default": 0.35}
    )
    emergency_longitudinal_offset_m: dict[str, float] = field(
        default_factory=lambda: {"gauntlet": 0.5, "adversarial": 1.5, "default": 4.0}
    )
    emergency_lateral_scale: dict[str, float] = field(
        default_factory=lambda: {"gauntlet": 0.05, "adversarial": 0.18, "default": 0.45}
    )
    wrong_way_lateral_scale: dict[str, float] = field(
        default_factory=lambda: {"gauntlet": 0.0, "adversarial": 0.12, "default": 0.35}
    )
    stalled_lateral_scale: dict[str, float] = field(default_factory=lambda: {"gauntlet": 0.12, "default": 0.28})
    taper_lateral_scale: dict[str, float] = field(default_factory=lambda: {"gauntlet": 0.08, "default": 0.25})
    novel_object_lateral_max_m: dict[str, float] = field(default_factory=lambda: {"gauntlet": 0.22, "default": 0.55})
    novel_object_radius_max_m: dict[str, float] = field(default_factory=lambda: {"gauntlet": 2.6, "default": 2.1})
    debris_lateral_jitter_m: tuple[float, float] = (-0.7, 0.7)
    debris_radius_m: tuple[float, float] = (0.9, 1.5)
    construction_cone_count: int = 5
    construction_cone_spacing_m: float = 1.8
    construction_cone_lateral_step_m: float = 0.35
    construction_cone_radius_m: float = 0.42
    temporary_taper_length_m: float = 18.0


@dataclass(frozen=True)
class AmbientGeometryConfig:
    lane_index_min: int = 1
    lane_index_end_buffer: int = 2
    longitudinal_jitter_m: tuple[float, float] = (-5.0, 5.0)
    lateral_scale_range: tuple[float, float] = (0.68, 1.2)
    radius_range_m: tuple[float, float] = (0.7, 2.0)


@dataclass(frozen=True)
class EnvironmentConfig:
    visibility_ranges: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "clear": (0.82, 1.0),
            "rain": (0.45, 0.75),
            "low_light": (0.38, 0.68),
            "glare": (0.42, 0.72),
            "mist": (0.34, 0.62),
            "wet_surface": (0.58, 0.84),
        }
    )
    normal_latency_budget_ms: tuple[int, ...] = (80, 100, 120)
    degraded_latency_budget_ms: tuple[int, ...] = (60, 80, 100)
    degraded_latency_visibility_threshold: float = 0.5


@dataclass(frozen=True)
class CompositionalScenarioProfile:
    name: str = "compositional-generator-v0"
    suite_seed_offsets: dict[str, int] = field(
        default_factory=lambda: {"compositional": 0, "adversarial": 10_000, "gauntlet": 15_000, "hidden": 20_000}
    )
    suite_pressure: dict[str, float] = field(default_factory=lambda: dict(SUITE_PRESSURE))
    hazard_counts: dict[str, tuple[int, ...]] = field(
        default_factory=lambda: {
            "compositional": (1,),
            "hidden": (1, 2),
            "adversarial": (2, 3),
            "gauntlet": (4,),
        }
    )
    ambient_base_count: int = 5
    gauntlet_lane_half_width_cap: tuple[float, float] = (4.6, 6.2)
    corridor_clearance: CorridorClearanceConfig = field(default_factory=CorridorClearanceConfig)
    difficulty: DifficultyConfig = field(default_factory=DifficultyConfig)
    topology: TopologyGeometryConfig = field(default_factory=TopologyGeometryConfig)
    hazards: HazardGeometryConfig = field(default_factory=HazardGeometryConfig)
    ambient: AmbientGeometryConfig = field(default_factory=AmbientGeometryConfig)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)


DEFAULT_COMPOSITIONAL_PROFILE = CompositionalScenarioProfile()


def generate_compositional_scenario(
    seed: int,
    suite: str = "compositional",
    width: float = 140.0,
    height: float = 90.0,
    profile: CompositionalScenarioProfile | None = None,
) -> Scenario:
    profile = profile or DEFAULT_COMPOSITIONAL_PROFILE
    if suite not in COMPOSITIONAL_SUITES:
        valid = ", ".join(COMPOSITIONAL_SUITES)
        raise ValueError(f"unknown compositional suite {suite!r}; expected one of: {valid}")

    rng = random.Random(_suite_seed(seed, suite, profile))
    topology = rng.choice(_topologies_for_suite(suite, rng))
    lane_half_width = _lane_half_width(topology, rng, profile)
    if suite == "gauntlet":
        lane_half_width = min(lane_half_width, rng.uniform(*profile.gauntlet_lane_half_width_cap))
    lane = _lane_for_topology(topology, rng, width, height, profile)
    start = (lane[0][0] - profile.topology.start_goal_padding_m, lane[0][1])
    goal = (lane[-1][0] + profile.topology.start_goal_padding_m, lane[-1][1])
    condition = rng.choice(_conditions_for_suite(suite))

    hazard_count = _hazard_count_for_suite(suite, rng, profile)

    if suite == "gauntlet":
        selected_hazards = list(rng.choice(GAUNTLET_HAZARD_SETS))
        rng.shuffle(selected_hazards)
    else:
        hazards = list(COMPOSITIONAL_HAZARDS)
        rng.shuffle(hazards)
        selected_hazards = hazards[:hazard_count]
    primary_hazard = selected_hazards[0]

    obstacles = _repair_static_corridor(
        _ambient_obstacles(rng, lane, lane_half_width, count=profile.ambient_base_count + hazard_count, profile=profile),
        lane,
        lane_half_width,
        _corridor_clearance(topology, primary_hazard, profile),
    )
    actors: list[Actor] = []
    map_features = _topology_features(topology, lane, lane_half_width, profile)
    allowed_maneuvers: set[str] = set()
    blocking_hazards = 0

    slots = _hazard_slots(len(selected_hazards), lane)
    for index, hazard in enumerate(selected_hazards):
        slot = slots[index]
        created = _build_hazard(hazard, index, rng, lane, slot, lane_half_width, suite, profile)
        obstacles.extend(created["obstacles"])
        actors.extend(created["actors"])
        map_features.extend(created["map_features"])
        allowed_maneuvers.update(created["allowed_maneuvers"])
        blocking_hazards += int(created["blocking"])

    environment = _environment(condition, rng, profile)
    manifest = {
        "generator": "compositional_ood_v1",
        "scenario_suite": suite,
        "topology": topology,
        "condition": condition,
        "primary_hazard_id": f"hazard_0_{primary_hazard}",
        "primary_hazard_type": primary_hazard,
        "intended_decision": _intended_decision(primary_hazard, lane_half_width, profile),
        "allowed_maneuvers": ",".join(sorted(allowed_maneuvers or {"maintain"})),
        "difficulty": _difficulty(suite, hazard_count, condition, topology, profile),
        "ood_axes": ",".join(_ood_axes(suite, selected_hazards, condition, topology)),
        "hazard_count": hazard_count,
        "difficulty_axes": ",".join(_difficulty_axes(suite, condition, topology, profile)),
        "scenario_profile": profile.name,
        "ambient_objects": sum(1 for obstacle in obstacles if obstacle.kind == "ambient"),
        "blocking_hazards": blocking_hazards,
        "hazard_composition": "+".join(selected_hazards),
    }

    return Scenario(
        width=width,
        height=height,
        lane_center=lane,
        lane_half_width=lane_half_width,
        obstacles=obstacles,
        start=start,
        goal=goal,
        seed=seed,
        cluster=f"{suite}:{topology}",
        tags=manifest,
        actors=actors,
        map_features=map_features,
        environment=environment,
    )


def compositional_cases(suite: str) -> tuple[str, ...]:
    if suite == "compositional":
        return COMPOSITIONAL_TOPOLOGIES
    if suite == "adversarial":
        return tuple(f"adversarial_{count}_hazard" for count in (2, 3))
    if suite == "gauntlet":
        return tuple(f"gauntlet_case_{index}" for index in range(1, len(GAUNTLET_HAZARD_SETS) + 1))
    if suite == "hidden":
        return ("hidden_holdout",)
    raise ValueError(f"unknown compositional suite {suite!r}")


def _hazard_count_for_suite(suite: str, rng: random.Random, profile: CompositionalScenarioProfile) -> int:
    counts = profile.hazard_counts.get(suite, (1,))
    return counts[0] if len(counts) == 1 else rng.choice(counts)


def _suite_seed(seed: int, suite: str, profile: CompositionalScenarioProfile) -> int:
    return seed + profile.suite_seed_offsets[suite]


def _topologies_for_suite(suite: str, rng: random.Random) -> tuple[str, ...]:
    if suite == "gauntlet":
        return ("rural_single_track", "worksite_chicane", "roundabout_entry", "industrial_yard")
    return COMPOSITIONAL_TOPOLOGIES


def _conditions_for_suite(suite: str) -> tuple[str, ...]:
    if suite == "gauntlet":
        return ("rain", "low_light", "glare", "mist")
    return COMPOSITIONAL_CONDITIONS


def _lane_half_width(topology: str, rng: random.Random, profile: CompositionalScenarioProfile) -> float:
    low, high = profile.topology.lane_half_width_ranges.get(
        topology,
        profile.topology.lane_half_width_ranges["default"],
    )
    return rng.uniform(low, high)


def _lane_for_topology(
    topology: str,
    rng: random.Random,
    width: float,
    height: float,
    profile: CompositionalScenarioProfile,
) -> list[tuple[float, float]]:
    geometry = profile.topology
    points = geometry.lane_control_points
    center_y = height * geometry.center_y_fraction
    lane: list[tuple[float, float]] = []
    for index in range(points):
        t = index / (points - 1)
        x = geometry.route_x_margin_m + t * (width - geometry.route_x_margin_m * 2.0)
        if topology == "straight":
            y = center_y + rng.uniform(-geometry.straight_jitter_m, geometry.straight_jitter_m)
        elif topology == "s_bend":
            y = center_y + math.sin(t * math.tau) * geometry.s_bend_amplitude_m + rng.uniform(
                -geometry.s_bend_jitter_m,
                geometry.s_bend_jitter_m,
            )
        elif topology == "roundabout_entry":
            y = (
                center_y
                + (1.0 - math.cos(t * math.pi)) * geometry.roundabout_cos_amplitude_m
                + math.sin(t * math.pi * geometry.roundabout_sin_frequency) * geometry.roundabout_sin_amplitude_m
            )
        elif topology == "rural_single_track":
            y = center_y + math.sin(t * math.pi * geometry.rural_frequency) * geometry.rural_amplitude_m + rng.uniform(
                -geometry.rural_jitter_m,
                geometry.rural_jitter_m,
            )
        elif topology == "industrial_yard":
            y = center_y + (index % 3 - 1) * rng.uniform(*geometry.industrial_y_jitter_m)
        elif topology == "worksite_chicane":
            y = center_y + math.sin(t * math.pi) * geometry.worksite_chicane_amplitude_m
        else:
            raise ValueError(f"unknown topology {topology!r}")
        lane.append((x, y))
    return lane


def _hazard_slots(count: int, lane: list[tuple[float, float]]) -> list[int]:
    if count == 1:
        return [4]
    if count == 2:
        return [3, 6]
    if count == 4:
        return [2, 3, 5, 6]
    return [2, 4, 6]


def _build_hazard(
    hazard: str,
    index: int,
    rng: random.Random,
    lane: list[tuple[float, float]],
    slot: int,
    half_width: float,
    suite: str,
    profile: CompositionalScenarioProfile,
) -> dict[str, Any]:
    geometry = profile.hazards
    x, y = lane[slot]
    side = rng.choice((-1.0, 1.0))
    obstacles: list[Obstacle] = []
    actors: list[Actor] = []
    features: list[dict[str, Any]] = []
    allowed: set[str] = {"slow_yield"}
    blocking = False
    hazard_id = f"hazard_{index}_{hazard}"
    pressure = _suite_pressure(suite, profile)

    if hazard == "debris_object":
        obstacles.append(
            Obstacle(
                x,
                y + rng.uniform(*geometry.debris_lateral_jitter_m),
                rng.uniform(*geometry.debris_radius_m),
                "debris",
                hazard_id,
            )
        )
        allowed.update({"nudge_left", "nudge_right", "evasive_left", "evasive_right"})
        blocking = True
    elif hazard == "animal_crossing":
        actors.append(
            _actor(
                hazard_id,
                "animal",
                x - 2.2,
                y + side * half_width * _scale_for_suite(geometry.crossing_start_scale, suite),
                0.9,
                1.2,
                -side * math.pi / 2.0,
                0.9 * pressure,
                "darting",
                hazard_id,
            )
        )
        allowed.update({"slow_yield", "evasive_left", "evasive_right"})
        blocking = True
    elif hazard == "occluded_pedestrian":
        obstacles.append(Obstacle(x - 2.0, y + side * half_width * 0.72, 1.4, "occluder", f"{hazard_id}_occluder"))
        actors.append(
            _actor(
                hazard_id,
                "pedestrian",
                x - 4.0,
                y + side * half_width * _scale_for_suite(geometry.crossing_start_scale, suite),
                0.6,
                0.6,
                -side * math.pi / 2.0,
                0.7 * pressure,
                "erratic_pedestrian",
                hazard_id,
            )
        )
        allowed.update({"crawl", "slow_yield"})
        blocking = True
    elif hazard == "cut_in_vehicle":
        actors.append(
            _actor(
                hazard_id,
                "vehicle",
                x - 1.0,
                y + side * half_width * _scale_for_suite(geometry.cut_in_start_scale, suite),
                2.0,
                4.4,
                -side * _scale_for_suite(geometry.cut_in_heading_delta_rad, suite),
                1.15 * pressure,
                "cut_in",
                hazard_id,
            )
        )
        allowed.update({"slow_yield", "nudge_left", "nudge_right"})
        blocking = True
    elif hazard == "emergency_vehicle":
        actors.append(
            _actor(
                hazard_id,
                "special_vehicle",
                x + _scale_for_suite(geometry.emergency_longitudinal_offset_m, suite),
                y - side * half_width * _scale_for_suite(geometry.emergency_lateral_scale, suite),
                2.6,
                6.0,
                0.0,
                0.65 * pressure,
                "sudden_brake",
                hazard_id,
            )
        )
        features.append({"kind": "emergency_response_zone", "x": x, "y": y, "yield_side": "left" if side < 0 else "right"})
        allowed.update({"slow_yield", "nudge_left", "nudge_right"})
        blocking = True
    elif hazard == "wrong_way_vehicle":
        actors.append(
            _actor(
                hazard_id,
                "vehicle",
                x + 7.0,
                y + side * half_width * _scale_for_suite(geometry.wrong_way_lateral_scale, suite),
                2.0,
                4.5,
                math.pi,
                0.85 * pressure,
                "wrong_way",
                hazard_id,
            )
        )
        allowed.update({"crawl", "slow_yield", "evasive_left", "evasive_right"})
        blocking = True
    elif hazard == "stalled_vehicle":
        obstacles.append(
            Obstacle(
                x + 1.0,
                y + side * half_width * _scale_for_suite(geometry.stalled_lateral_scale, suite),
                2.4,
                "vehicle",
                hazard_id,
            )
        )
        allowed.update({"nudge_left", "nudge_right", "evasive_left", "evasive_right"})
        blocking = True
    elif hazard == "construction_taper":
        for cone in range(geometry.construction_cone_count):
            obstacles.append(
                Obstacle(
                    x + cone * geometry.construction_cone_spacing_m,
                    y
                    + side
                    * (
                        half_width * _scale_for_suite(geometry.taper_lateral_scale, suite)
                        + cone * geometry.construction_cone_lateral_step_m
                    ),
                    geometry.construction_cone_radius_m,
                    "cone",
                    hazard_id,
                )
            )
        features.append(
            {
                "kind": "temporary_taper",
                "x": x,
                "y": y,
                "side": "left" if side > 0 else "right",
                "length": geometry.temporary_taper_length_m,
            }
        )
        allowed.update({"lane_recover", "nudge_left", "nudge_right"})
        blocking = True
    elif hazard == "novel_object":
        label = rng.choice(("piano", "parade_float", "horse_trailer", "fallen_sign", "portable_toilet"))
        obstacles.append(
            Obstacle(
                x,
                y + side * rng.uniform(0.0, _scale_for_suite(geometry.novel_object_lateral_max_m, suite)),
                rng.uniform(1.2, _scale_for_suite(geometry.novel_object_radius_max_m, suite)),
                "novel_object",
                f"{hazard_id}:{label}",
            )
        )
        allowed.update({"nudge_left", "nudge_right", "evasive_left", "evasive_right"})
        blocking = True
    else:
        raise ValueError(f"unknown hazard {hazard!r}")

    features.append({"kind": "primary_decision_point" if index == 0 else "secondary_decision_point", "x": x, "y": y, "hazard": hazard})
    return {"obstacles": obstacles, "actors": actors, "map_features": features, "allowed_maneuvers": allowed, "blocking": blocking}


def _scale_for_suite(values: dict[str, float], suite: str) -> float:
    return values.get(suite, values["default"])


def _suite_pressure(suite: str, profile: CompositionalScenarioProfile | None = None) -> float:
    profile = profile or DEFAULT_COMPOSITIONAL_PROFILE
    return profile.suite_pressure[suite]


def _actor(
    actor_id: str,
    kind: str,
    x: float,
    y: float,
    width: float,
    length: float,
    heading: float,
    speed: float,
    behavior: str,
    role: str,
) -> Actor:
    return Actor(
        actor_id=actor_id,
        kind=kind,
        x=x,
        y=y,
        width=width,
        length=length,
        heading=heading,
        speed=speed,
        vx=math.cos(heading) * speed,
        vy=math.sin(heading) * speed,
        behavior=behavior,
        role=role,
    )


def _ambient_obstacles(
    rng: random.Random,
    lane: list[tuple[float, float]],
    half_width: float,
    count: int,
    profile: CompositionalScenarioProfile | None = None,
) -> list[Obstacle]:
    profile = profile or DEFAULT_COMPOSITIONAL_PROFILE
    config = profile.ambient
    obstacles: list[Obstacle] = []
    for index in range(count):
        lane_index = rng.randint(config.lane_index_min, len(lane) - config.lane_index_end_buffer)
        x, y = lane[lane_index]
        side = rng.choice((-1.0, 1.0))
        obstacles.append(
            Obstacle(
                x=x + rng.uniform(*config.longitudinal_jitter_m),
                y=y + side * rng.uniform(
                    half_width * config.lateral_scale_range[0],
                    half_width * config.lateral_scale_range[1],
                ),
                radius=rng.uniform(*config.radius_range_m),
                kind="ambient",
                label=f"ambient_texture_{index}",
            )
        )
    return obstacles


def _topology_features(
    topology: str,
    lane: list[tuple[float, float]],
    half_width: float,
    profile: CompositionalScenarioProfile | None = None,
) -> list[dict[str, Any]]:
    profile = profile or DEFAULT_COMPOSITIONAL_PROFILE
    geometry = profile.topology
    features: list[dict[str, Any]] = [
        {"kind": "route_corridor", "lane_half_width": round(half_width, 3), "topology": topology}
    ]
    if topology == "roundabout_entry":
        features.append({"kind": "roundabout_entry", "x": lane[5][0], "y": lane[5][1], "radius": geometry.roundabout_feature_radius_m})
    elif topology == "rural_single_track":
        features.append({"kind": "single_track_pullout", "x": lane[4][0], "y": lane[4][1], "width": half_width * geometry.rural_pullout_width_scale})
    elif topology == "industrial_yard":
        features.append({"kind": "unmarked_operational_area", "x": lane[3][0], "y": lane[3][1], "speed_limit": geometry.industrial_speed_limit_mps})
    elif topology == "worksite_chicane":
        features.append({"kind": "temporary_alignment", "x": lane[4][0], "y": lane[4][1], "length": geometry.temporary_alignment_length_m})
    return features


def _environment(condition: str, rng: random.Random, profile: CompositionalScenarioProfile | None = None) -> dict[str, Any]:
    profile = profile or DEFAULT_COMPOSITIONAL_PROFILE
    config = profile.environment
    visibility = rng.uniform(*config.visibility_ranges[condition])
    latency_choices = (
        config.normal_latency_budget_ms
        if visibility > config.degraded_latency_visibility_threshold
        else config.degraded_latency_budget_ms
    )
    return {
        "weather": condition,
        "visibility": round(visibility, 3),
        "time_of_day": "dusk" if condition in {"low_light", "glare"} else rng.choice(("morning", "midday", "night")),
        "road_surface": "wet" if condition in {"rain", "mist", "wet_surface"} else "dry",
        "sensor_noise": round(1.0 - visibility, 3),
        "latency_budget_ms": rng.choice(latency_choices),
    }


def _corridor_clearance(topology: str, primary_hazard: str, profile: CompositionalScenarioProfile | None = None) -> float:
    profile = profile or DEFAULT_COMPOSITIONAL_PROFILE
    clearance = profile.corridor_clearance
    if topology == "rural_single_track":
        return clearance.rural_single_track
    if primary_hazard in {"debris_object", "novel_object", "stalled_vehicle"}:
        return clearance.static_blocker
    return clearance.default


def _intended_decision(
    primary_hazard: str,
    half_width: float,
    profile: CompositionalScenarioProfile | None = None,
) -> str:
    profile = profile or DEFAULT_COMPOSITIONAL_PROFILE
    if primary_hazard in {"occluded_pedestrian", "animal_crossing", "emergency_vehicle"}:
        return "slow_or_yield_before_conflict"
    if primary_hazard == "construction_taper":
        return "recover_to_temporary_corridor"
    if half_width < profile.topology.narrow_corridor_half_width_m:
        return "crawl_then_nudge_through_narrow_gap"
    return "lateral_avoidance_with_progress"


def _difficulty(
    suite: str,
    hazard_count: int,
    condition: str,
    topology: str,
    profile: CompositionalScenarioProfile | None = None,
) -> float:
    profile = profile or DEFAULT_COMPOSITIONAL_PROFILE
    config = profile.difficulty
    score = config.base + hazard_count * config.per_hazard
    if suite == "gauntlet":
        score += config.gauntlet_bonus
    elif suite in {"adversarial", "hidden"}:
        score += config.adversarial_bonus
    if condition in {"rain", "low_light", "glare", "mist"}:
        score += config.poor_condition_bonus
    if topology in {"rural_single_track", "roundabout_entry", "industrial_yard"}:
        score += config.complex_topology_bonus
    return round(min(1.0, score), 3)


def _ood_axes(suite: str, hazards: list[str], condition: str, topology: str) -> list[str]:
    axes = [f"topology:{topology}", f"condition:{condition}"]
    if len(hazards) > 1:
        axes.append("composed_hazards")
    if "novel_object" in hazards:
        axes.append("novel_object_type")
    if suite in {"adversarial", "hidden", "gauntlet"}:
        axes.append(f"suite:{suite}")
    if suite == "gauntlet":
        axes.extend(("synchronized_threats", "quality_gated_benchmark"))
    return axes


def _difficulty_axes(
    suite: str,
    condition: str,
    topology: str,
    profile: CompositionalScenarioProfile | None = None,
) -> list[str]:
    axes = [f"suite_pressure:{_suite_pressure(suite, profile):.2f}"]
    if condition in {"rain", "low_light", "glare", "mist"}:
        axes.append("reduced_visibility")
    if topology in {"rural_single_track", "roundabout_entry", "industrial_yard"}:
        axes.append("topology_complexity")
    return axes
