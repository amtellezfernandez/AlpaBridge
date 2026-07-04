from __future__ import annotations

import math
import random

from .environment import Actor, Obstacle, Scenario, offset_centerline


WOD_E2E_CLUSTERS = (
    "construction",
    "intersection",
    "pedestrian",
    "cyclist",
    "multi-lane maneuver",
    "single-lane maneuver",
    "cut-in",
    "foreign object debris",
    "special vehicle",
    "spotlight",
    "others",
)


def generate_wod_scenario(cluster: str, seed: int, width: float = 120.0, height: float = 80.0) -> Scenario:
    if cluster not in WOD_E2E_CLUSTERS:
        valid = ", ".join(WOD_E2E_CLUSTERS)
        raise ValueError(f"unknown WOD-E2E cluster {cluster!r}; expected one of: {valid}")

    rng = random.Random(seed)
    lane_half_width = _cluster_lane_half_width(cluster, rng)
    lane_center = _lane_center_for_cluster(cluster, rng, width, height)
    obstacles = _repair_static_corridor(
        _cluster_obstacles(cluster, rng, lane_center, lane_half_width),
        lane_center,
        lane_half_width,
        _corridor_clearance(cluster),
    )
    actors = _cluster_actors(cluster, rng, lane_center, lane_half_width)
    map_features = _cluster_map_features(cluster, rng, lane_center, lane_half_width)
    route_line = offset_centerline(lane_center, _travel_lane_offset(cluster, lane_half_width))
    start = (route_line[0][0] - 4.0, route_line[0][1])
    goal = (route_line[-1][0] + 4.0, route_line[-1][1])
    environment = _cluster_environment(cluster, rng)
    if cluster == "intersection":
        conflict_x = lane_center[3][0]
        environment["intersection_trigger_x"] = round(conflict_x - 9.0, 3)
    tags = _cluster_tags(cluster, rng)

    return Scenario(
        width=width,
        height=height,
        lane_center=lane_center,
        lane_half_width=lane_half_width,
        obstacles=obstacles,
        start=start,
        goal=goal,
        seed=seed,
        cluster=cluster,
        tags=tags,
        actors=actors,
        map_features=map_features,
        environment=environment,
    )


def _cluster_lane_half_width(cluster: str, rng: random.Random) -> float:
    if cluster in {"single-lane maneuver", "construction"}:
        return rng.uniform(5.2, 6.8)
    if cluster in {"multi-lane maneuver", "cut-in"}:
        return rng.uniform(9.0, 11.5)
    return rng.uniform(7.0, 9.5)


def _lane_center_for_cluster(
    cluster: str,
    rng: random.Random,
    width: float,
    height: float,
) -> list[tuple[float, float]]:
    control_points = 8
    center_y = height * 0.5
    lane_center: list[tuple[float, float]] = []
    spotlight_curve_amp = rng.uniform(-2.8, 2.8)
    spotlight_drift = rng.uniform(-1.8, 1.8)
    spotlight_phase = rng.uniform(-0.2, 0.2)
    for index in range(control_points):
        x = 10.0 + index * (width - 20.0) / (control_points - 1)
        progress = index / (control_points - 1)
        if cluster == "intersection":
            y = center_y + (index - 3.5) * rng.uniform(-1.0, 1.0)
        elif cluster == "construction":
            lane_shift = 8.0 * math.sin(progress * math.pi)
            y = center_y + lane_shift + rng.uniform(-1.5, 1.5)
        elif cluster == "single-lane maneuver":
            y = center_y + rng.uniform(-height * 0.12, height * 0.12)
        elif cluster == "multi-lane maneuver":
            y = center_y + (progress - 0.5) * rng.uniform(-10.0, 10.0)
        elif cluster == "spotlight":
            lane_arc = math.sin((progress + spotlight_phase) * math.pi)
            y = center_y + lane_arc * spotlight_curve_amp + (progress - 0.5) * spotlight_drift + rng.uniform(-0.45, 0.45)
        else:
            y = center_y + rng.uniform(-height * 0.18, height * 0.18)
        lane_center.append((x, y))
    return lane_center


def _cluster_obstacles(
    cluster: str,
    rng: random.Random,
    lane_center: list[tuple[float, float]],
    lane_half_width: float,
) -> list[Obstacle]:
    builders = {
        "construction": _construction_obstacles,
        "intersection": _intersection_obstacles,
        "pedestrian": _pedestrian_obstacles,
        "cyclist": _cyclist_obstacles,
        "multi-lane maneuver": _multi_lane_obstacles,
        "single-lane maneuver": _single_lane_obstacles,
        "cut-in": _cut_in_obstacles,
        "foreign object debris": _fod_obstacles,
        "special vehicle": _special_vehicle_obstacles,
        "spotlight": _spotlight_obstacles,
        "others": _others_obstacles,
    }
    return builders[cluster](rng, lane_center, lane_half_width)


def _cluster_actors(
    cluster: str,
    rng: random.Random,
    lane: list[tuple[float, float]],
    half_width: float,
) -> list[Actor]:
    builders = {
        "construction": _construction_actors,
        "intersection": _intersection_actors,
        "pedestrian": _pedestrian_actors,
        "cyclist": _cyclist_actors,
        "multi-lane maneuver": _multi_lane_actors,
        "single-lane maneuver": _single_lane_actors,
        "cut-in": _cut_in_actors,
        "foreign object debris": _fod_actors,
        "special vehicle": _special_vehicle_actors,
        "spotlight": _spotlight_actors,
        "others": _others_actors,
    }
    return builders[cluster](rng, lane, half_width)


def _cluster_map_features(
    cluster: str,
    rng: random.Random,
    lane: list[tuple[float, float]],
    half_width: float,
) -> list[dict[str, float | int | str | bool]]:
    features: list[dict[str, float | int | str | bool]] = [
        {
            "kind": "route_corridor",
            "lane_half_width": round(half_width, 3),
            "lane_count": _lane_count(cluster),
            "travel_lane_index": _travel_lane_index(cluster),
            "travel_side": "right",
        }
    ]
    if cluster == "construction":
        x, y = lane[3]
        features.append({"kind": "lane_closure", "x": x, "y": y, "side": rng.choice(("left", "right")), "length": 28.0})
        features.append({"kind": "merge_taper", "x": lane[2][0], "y": lane[2][1], "length": 20.0})
    elif cluster in {"intersection", "pedestrian"}:
        x, y = lane[3]
        features.append({"kind": "crosswalk", "x": x, "y": y, "width": half_width * 2.4})
        features.append({"kind": "conflict_zone", "x": x + 3.0, "y": y, "radius": half_width})
    elif cluster in {"multi-lane maneuver", "cut-in"}:
        features.append({"kind": "adjacent_lane", "offset": half_width * 0.65, "length": 80.0})
        features.append({"kind": "merge_zone", "x": lane[4][0], "y": lane[4][1], "length": 24.0})
    elif cluster == "foreign object debris":
        features.append({"kind": "avoidance_corridor", "x": lane[3][0], "y": lane[3][1], "width": half_width * 1.4})
    return features


def _cluster_environment(cluster: str, rng: random.Random) -> dict[str, float | int | str | bool]:
    weather = rng.choice(("clear", "rain", "mist", "low_sun", "night"))
    if cluster == "spotlight":
        weather = rng.choice(("night", "mist", "low_sun"))
    environment: dict[str, float | int | str | bool | list[dict[str, object]]] = {
        "weather": weather,
        "visibility": round(rng.uniform(0.35 if weather != "clear" else 0.75, 1.0), 3),
        "time_of_day": rng.choice(("morning", "midday", "dusk", "night")),
        "road_surface": "wet" if weather in {"rain", "mist"} else "dry",
        "severity": round(rng.uniform(0.35, 1.0), 3),
    }
    if cluster == "spotlight":
        environment["trigger_regions"] = [
            {"actor_roles": ["spotlight_hazard"], "x_min": 36.0, "x_max": 56.0, "delay_ticks": 1.0}
        ]
    elif cluster == "pedestrian":
        environment["trigger_regions"] = [
            {"actor_roles": ["erratic_pedestrian"], "x_min": 40.0, "x_max": 54.0, "delay_ticks": 0.0}
        ]
    elif cluster == "cut-in":
        environment["trigger_regions"] = [
            {"actor_roles": ["cut_in_vehicle"], "x_min": 34.0, "x_max": 50.0, "delay_ticks": 0.0}
        ]
    return environment


def _construction_obstacles(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Obstacle]:
    obstacles = _ambient_obstacles(rng, lane, half_width, 3)
    side = rng.choice((-1.0, 1.0))
    for index in range(2, 6):
        x, y = lane[index]
        for cone in range(3):
            obstacles.append(
                Obstacle(
                    x=x + cone * 2.2,
                    y=y + side * rng.uniform(2.0, half_width * 0.85),
                    radius=0.45,
                    kind="cone",
                    label="construction_taper",
                )
            )
    worker_x, worker_y = lane[4]
    obstacles.append(Obstacle(worker_x + rng.uniform(-1.0, 1.0), worker_y - side * half_width * 0.45, 0.9, "worker", "flagger"))
    return obstacles


def _intersection_obstacles(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Obstacle]:
    obstacles = _ambient_obstacles(rng, lane, half_width, 3)
    cx, cy = lane[3]
    # Keep static visual context away from the immediate crossing pocket so the live
    # actor timing is the actual test signal instead of a cluttered overlap of textures.
    textures = (
        (-11.0, -half_width * 1.65),
        (-7.0, -half_width * 1.15),
        (7.5, half_width * 1.15),
        (11.5, half_width * 1.65),
    )
    for dx, dy in textures:
        obstacles.append(
            Obstacle(
                cx + dx + rng.uniform(-0.8, 0.8),
                cy + dy + rng.uniform(-0.6, 0.6),
                rng.uniform(0.9, 1.35),
                "vehicle",
                "cross_traffic_texture",
            )
        )
    pocket_narrowing = (
        (-2.8, -half_width * 0.82),
        (1.6, half_width * 0.76),
        (5.0, -half_width * 0.72),
    )
    for dx, dy in pocket_narrowing:
        obstacles.append(
            Obstacle(
                cx + dx + rng.uniform(-0.45, 0.45),
                cy + dy + rng.uniform(-0.35, 0.35),
                rng.uniform(1.0, 1.25),
                "vehicle",
                "intersection_occluder",
            )
        )
    return obstacles


def _pedestrian_obstacles(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Obstacle]:
    obstacles = _ambient_obstacles(rng, lane, half_width, 4)
    x, y = lane[3]
    side = rng.choice((-1.0, 1.0))
    obstacles.append(Obstacle(x, y + side * rng.uniform(1.0, 2.5), 0.75, "pedestrian", "crosswalk_hazard"))
    obstacles.append(Obstacle(x + rng.uniform(3.0, 6.0), y - side * half_width * 0.8, 1.2, "occluder", "pedestrian_occluder"))
    return obstacles


def _cyclist_obstacles(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Obstacle]:
    return _ambient_obstacles(rng, lane, half_width, 4)


def _multi_lane_obstacles(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Obstacle]:
    return _ambient_obstacles(rng, lane, half_width, 5)


def _single_lane_obstacles(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Obstacle]:
    obstacles = _ambient_obstacles(rng, lane, half_width, 4)
    x, y = lane[4]
    obstacles.append(Obstacle(x + rng.uniform(-1.0, 1.0), y + rng.choice((-1.0, 1.0)) * half_width * 0.55, 1.3, "vehicle", "single_lane_slow_vehicle"))
    return obstacles


def _cut_in_obstacles(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Obstacle]:
    obstacles = _ambient_obstacles(rng, lane, half_width, 4)
    for index, lateral in ((3, 0.75), (4, 0.35)):
        x, y = lane[index]
        obstacles.append(Obstacle(x + rng.uniform(-1.0, 1.0), y + rng.choice((-1.0, 1.0)) * half_width * lateral, 1.6, "vehicle", "cut_in_setup"))
    return obstacles


def _fod_obstacles(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Obstacle]:
    return _ambient_obstacles(rng, lane, half_width, 4)


def _special_vehicle_obstacles(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Obstacle]:
    return _ambient_obstacles(rng, lane, half_width, 4)


def _spotlight_obstacles(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Obstacle]:
    obstacles = _ambient_obstacles(rng, lane, half_width, 5)
    x, y = lane[3]
    obstacles.append(
        Obstacle(
            x + rng.uniform(5.0, 8.0),
            y + rng.choice((-1.0, 1.0)) * half_width * 0.45,
            rng.uniform(1.0, 1.8),
            "occluder",
            "spotlight_occluder",
        )
    )
    return obstacles


def _others_obstacles(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Obstacle]:
    return _ambient_obstacles(rng, lane, half_width, rng.randint(7, 11))


def _construction_actors(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Actor]:
    x, y = lane[4]
    side = rng.choice((-1.0, 1.0))
    return [_actor("worker_0", "worker", x + 1.0, y + side * half_width * 0.6, 0.8, 1.8, 0.0, 0.0, "flagging", "flagger")]


def _intersection_actors(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Actor]:
    x, y = lane[3]
    trigger_tick = _intersection_trigger_tick(lane, trigger_index=3)
    primary_side = rng.choice((-1.0, 1.0))
    secondary_side = -primary_side
    primary_speed = rng.uniform(2.55, 2.9)
    secondary_speed = rng.uniform(0.9, 1.3)
    return [
        _actor(
            "cross_traffic_0",
            "vehicle",
            x + rng.uniform(0.4, 1.2),
            y + primary_side * half_width * 1.14,
            2.0,
            4.4,
            -primary_side * math.pi / 2.0,
            primary_speed,
            "crossing",
            "conflicting_vehicle",
            active_from=max(0, trigger_tick),
            active_until=trigger_tick + 18,
        ),
        _actor(
            "cross_traffic_1",
            "vehicle",
            x + rng.uniform(5.5, 8.0),
            y + secondary_side * half_width * 1.22,
            2.0,
            4.2,
            primary_side * math.pi / 2.0,
            secondary_speed,
            "creeping",
            "occluded_vehicle",
            active_from=trigger_tick + 7,
            active_until=trigger_tick + 24,
        ),
    ]


def _pedestrian_actors(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Actor]:
    x, y = lane[3]
    side = rng.choice((-1.0, 1.0))
    return [_actor("pedestrian_0", "pedestrian", x - 1.5, y + side * half_width, 0.6, 0.6, -side * math.pi / 2.0, 0.55, "crossing", "erratic_pedestrian")]


def _cyclist_actors(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Actor]:
    x, y = lane[3]
    return [_actor("cyclist_0", "cyclist", x, y + rng.choice((-1.0, 1.0)) * half_width * 0.7, 0.7, 1.8, 0.0, 0.8, "parallel", "cyclist")]


def _multi_lane_actors(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Actor]:
    x, y = lane[3]
    return [_actor("lead_vehicle_0", "vehicle", x, y, 2.0, 4.5, 0.0, 0.45, "slow_lead", "lead_vehicle")]


def _single_lane_actors(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Actor]:
    x, y = lane[4]
    return [_actor("slow_vehicle_0", "vehicle", x, y + rng.choice((-1.0, 1.0)) * half_width * 0.4, 2.1, 4.6, 0.0, 0.25, "slow_lead", "slow_vehicle")]


def _cut_in_actors(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Actor]:
    x, y = lane[3]
    side = rng.choice((-1.0, 1.0))
    return [_actor("cut_in_vehicle_0", "vehicle", x + 2.0, y + side * half_width * 0.85, 2.0, 4.4, -side * 0.45, 0.9, "cut_in", "cut_in_vehicle")]


def _fod_actors(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Actor]:
    x, y = lane[3]
    return [_actor("debris_0", "debris", x + rng.uniform(-1.0, 1.0), y + rng.uniform(-1.0, 1.0), 1.0, 1.0, 0.0, 0.0, "static", "foreign_object")]


def _special_vehicle_actors(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Actor]:
    x, y = lane[4]
    return [_actor("special_vehicle_0", "special_vehicle", x, y + rng.choice((-1.0, 1.0)) * half_width * 0.35, 3.0, 7.5, 0.0, 0.2, "oversized", "special_vehicle")]


def _spotlight_actors(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Actor]:
    x, y = lane[3]
    hazard = rng.choice(("animal", "fallen_rider", "wrong_way_vehicle"))
    if hazard == "animal":
        return [_actor("animal_0", "animal", x, y + half_width * 0.9, 0.9, 1.2, -math.pi / 2.0, 0.65, "darting", "spotlight_hazard")]
    if hazard == "wrong_way_vehicle":
        return [
            _actor(
                "wrong_way_0",
                "vehicle",
                x + 8.0,
                y + rng.choice((-1.0, 1.0)) * half_width * 0.55,
                2.0,
                4.4,
                math.pi,
                0.45,
                "wrong_way",
                "spotlight_hazard",
            )
        ]
    return [_actor("fallen_rider_0", "pedestrian", x + 2.0, y + rng.uniform(-1.0, 1.0), 0.8, 1.6, 0.0, 0.0, "static", "spotlight_hazard")]


def _others_actors(rng: random.Random, lane: list[tuple[float, float]], half_width: float) -> list[Actor]:
    x, y = lane[3]
    return [_actor("misc_vehicle_0", "vehicle", x, y + rng.uniform(-half_width * 0.5, half_width * 0.5), 2.0, 4.3, 0.0, 0.35, "misc", "long_tail_actor")]


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
    active_from: int = 0,
    active_until: int = 10_000,
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
        active_from=active_from,
        active_until=active_until,
    )


def _intersection_trigger_tick(lane: list[tuple[float, float]], trigger_index: int) -> int:
    start_x = lane[0][0] - 4.0
    conflict_x = lane[trigger_index][0]
    approach_distance = max(0.0, conflict_x - start_x)
    nominal_approach_speed_mps = 4.2
    trigger_time_s = max(0.0, (approach_distance - 11.0) / nominal_approach_speed_mps)
    return int(round(trigger_time_s / 0.25))


def _ambient_obstacles(
    rng: random.Random,
    lane: list[tuple[float, float]],
    half_width: float,
    count: int,
) -> list[Obstacle]:
    obstacles: list[Obstacle] = []
    for _ in range(count):
        index = rng.randint(1, len(lane) - 2)
        x, y = lane[index]
        side = rng.choice((-1.0, 1.0))
        lateral_offset = side * rng.uniform(half_width * 0.45, half_width * 0.95)
        obstacles.append(
            Obstacle(
                x=x + rng.uniform(-4.0, 4.0),
                y=y + lateral_offset,
                radius=rng.uniform(0.8, 2.2),
                kind="ambient",
                label="ambient_texture",
            )
        )
    return obstacles


def _cluster_tags(cluster: str, rng: random.Random) -> dict[str, float | int | str | bool]:
    tags: dict[str, float | int | str | bool] = {
        "generator": "wod_e2e_procedural_v1",
        "severity": round(rng.uniform(0.35, 1.0), 3),
        "visibility": round(rng.uniform(0.45, 1.0), 3),
    }
    if cluster == "construction":
        tags.update({"flagger_present": rng.choice((True, False)), "lane_closure": rng.choice(("left", "right"))})
    elif cluster == "foreign object debris":
        tags.update({"object_type": rng.choice(("tire", "box", "scooter", "furniture"))})
    elif cluster == "spotlight":
        tags.update({"hazard_type": rng.choice(("animal", "debris", "wrong_way", "fallen_rider"))})
    elif cluster == "special vehicle":
        tags.update({"vehicle_type": rng.choice(("emergency", "service", "oversized"))})
    return tags


def _lane_count(cluster: str) -> int:
    if cluster in {"multi-lane maneuver", "cut-in"}:
        return 3
    if cluster in {"single-lane maneuver", "construction"}:
        return 1
    return 2


def _travel_lane_index(cluster: str) -> int:
    lane_count = _lane_count(cluster)
    if lane_count <= 1:
        return 0
    return 0


def _travel_lane_offset(cluster: str, half_width: float) -> float:
    lane_count = _lane_count(cluster)
    if lane_count <= 1:
        return 0.0
    lane_width = (half_width * 2.0) / lane_count
    return -half_width + lane_width * (_travel_lane_index(cluster) + 0.5)


def _repair_static_corridor(
    obstacles: list[Obstacle],
    lane: list[tuple[float, float]],
    half_width: float,
    corridor_clearance: float,
) -> list[Obstacle]:
    repaired: list[Obstacle] = []
    for obstacle in obstacles:
        lane_point, tangent = _nearest_lane_geometry((obstacle.x, obstacle.y), lane)
        normal = (-tangent[1], tangent[0])
        dx = obstacle.x - lane_point[0]
        dy = obstacle.y - lane_point[1]
        lateral = dx * normal[0] + dy * normal[1]
        min_lateral = min(half_width * 0.82, obstacle.radius + corridor_clearance)
        if abs(lateral) < min_lateral:
            side = 1.0 if lateral >= 0.0 else -1.0
            repaired.append(
                Obstacle(
                    x=lane_point[0] + normal[0] * side * min_lateral,
                    y=lane_point[1] + normal[1] * side * min_lateral,
                    radius=obstacle.radius,
                    kind=obstacle.kind,
                    label=obstacle.label,
                )
            )
        else:
            repaired.append(obstacle)
    return repaired


def _nearest_lane_geometry(point: tuple[float, float], lane: list[tuple[float, float]]) -> tuple[tuple[float, float], tuple[float, float]]:
    dense_lane = _sample_lane(lane)
    best_index = 0
    best_distance = math.inf
    for index, lane_point in enumerate(dense_lane):
        distance = math.dist(point, lane_point)
        if distance < best_distance:
            best_index = index
            best_distance = distance
    prev_index = max(0, best_index - 1)
    next_index = min(len(dense_lane) - 1, best_index + 1)
    tangent = (dense_lane[next_index][0] - dense_lane[prev_index][0], dense_lane[next_index][1] - dense_lane[prev_index][1])
    norm = math.hypot(tangent[0], tangent[1])
    if norm == 0.0:
        return dense_lane[best_index], (1.0, 0.0)
    return dense_lane[best_index], (tangent[0] / norm, tangent[1] / norm)


def _sample_lane(lane: list[tuple[float, float]], samples_per_segment: int = 16) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for first, second in zip(lane, lane[1:]):
        for sample in range(samples_per_segment):
            t = sample / samples_per_segment
            points.append((first[0] + (second[0] - first[0]) * t, first[1] + (second[1] - first[1]) * t))
    points.append(lane[-1])
    return points


def _corridor_clearance(cluster: str) -> float:
    clearances = {
        "construction": 1.25,
        "intersection": 2.2,
        "pedestrian": 2.0,
        "cyclist": 2.0,
        "multi-lane maneuver": 2.2,
        "single-lane maneuver": 1.7,
        "cut-in": 2.0,
        "foreign object debris": 1.6,
        "special vehicle": 2.5,
        "spotlight": 2.5,
        "others": 2.0,
    }
    return clearances[cluster]
