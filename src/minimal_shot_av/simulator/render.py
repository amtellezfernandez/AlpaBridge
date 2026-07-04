from __future__ import annotations

import math
from pathlib import Path

from .environment import Actor, Scenario, actor_at_tick, interpolate_lane
from .policy import Rollout


def _polygon(points: list[tuple[float, float]], fill: str, opacity: float = 1.0, stroke: str = "none", width: float = 0.0) -> str:
    joined = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    stroke_attr = "" if stroke == "none" else f' stroke="{stroke}" stroke-width="{width:.2f}"'
    return f'<polygon points="{joined}" fill="{fill}" opacity="{opacity:.3f}"{stroke_attr} />'


def _polyline(points: list[tuple[float, float]], color: str, width: float, dash: str = "", opacity: float = 1.0) -> str:
    joined = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<polyline points="{joined}" fill="none" stroke="{color}" stroke-width="{width}" '
        f'stroke-linecap="round" stroke-linejoin="round" opacity="{opacity:.3f}"{dash_attr} />'
    )


def _actor_color(kind: str) -> str:
    colors = {
        "vehicle": "#6d597a",
        "pedestrian": "#9d4edd",
        "cyclist": "#2a9d8f",
        "animal": "#7f5539",
        "debris": "#5c677d",
        "worker": "#f77f00",
        "special_vehicle": "#d00000",
    }
    return colors.get(kind, "#6c757d")


def _actor_svg(actor: Actor) -> str:
    color = _actor_color(actor.kind)
    if actor.kind in {"pedestrian", "animal", "debris", "worker"}:
        return (
            f'<circle cx="{actor.x:.2f}" cy="{actor.y:.2f}" r="{actor.radius:.2f}" fill="{color}" opacity="0.9" />'
            f'<circle cx="{actor.x:.2f}" cy="{actor.y:.2f}" r="{actor.radius + 0.18:.2f}" fill="none" stroke="#fff7ed" stroke-width="0.18" opacity="0.8" />'
        )
    width = max(actor.width, 0.6)
    length = max(actor.length, 0.6)
    x = actor.x - length * 0.5
    y = actor.y - width * 0.5
    angle = actor.heading * 180.0 / 3.141592653589793
    return (
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{length:.2f}" height="{width:.2f}" '
        f'rx="0.28" ry="0.28" fill="{color}" opacity="0.92" transform="rotate({angle:.2f} {actor.x:.2f} {actor.y:.2f})" />'
        f'<rect x="{actor.x - length * 0.18:.2f}" y="{actor.y - width * 0.28:.2f}" width="{length * 0.22:.2f}" height="{width * 0.56:.2f}" '
        f'rx="0.12" fill="#e0f2fe" opacity="0.55" transform="rotate({angle:.2f} {actor.x:.2f} {actor.y:.2f})" />'
    )


def _map_feature_svg(feature: dict[str, float | int | str | bool]) -> str:
    kind = str(feature.get("kind", ""))
    x = float(feature.get("x", 0.0))
    y = float(feature.get("y", 0.0))
    if kind == "crosswalk":
        width = float(feature.get("width", 12.0))
        stripes = []
        stripe_count = 7
        spacing = width / stripe_count
        for index in range(stripe_count):
            y0 = y - width / 2 + index * spacing + spacing * 0.20
            stripes.append(
                f'<rect x="{x - 1.25:.2f}" y="{y0:.2f}" width="2.5" height="{spacing * 0.46:.2f}" '
                f'fill="#f8fafc" opacity="0.82" />'
            )
        stripes.append(f'<line x1="{x - 3.2:.2f}" y1="{y - width / 2:.2f}" x2="{x - 3.2:.2f}" y2="{y + width / 2:.2f}" stroke="#f8fafc" stroke-width="0.35" opacity="0.8" />')
        return "".join(stripes)
    if kind == "conflict_zone":
        radius = float(feature.get("radius", 8.0))
        return (
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="#f59e0b" opacity="0.10" />'
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="none" stroke="#f59e0b" stroke-width="0.35" stroke-dasharray="1.5 1.2" opacity="0.55" />'
        )
    if kind == "lane_closure":
        length = float(feature.get("length", 20.0))
        return f'<rect x="{x:.2f}" y="{y - 2.0:.2f}" width="{length:.2f}" height="4.0" fill="#f97316" opacity="0.18" stroke="#fb923c" stroke-width="0.28" stroke-dasharray="1.2 1.0" />'
    if kind in {"temporary_taper", "merge_taper"}:
        length = float(feature.get("length", 18.0))
        return f'<path d="M {x:.2f},{y - 3.4:.2f} L {x + length:.2f},{y - 0.8:.2f} L {x + length:.2f},{y + 0.8:.2f} L {x:.2f},{y + 3.4:.2f} Z" fill="#f97316" opacity="0.12" stroke="#fb923c" stroke-width="0.28" />'
    if kind == "merge_zone":
        length = float(feature.get("length", 20.0))
        return f'<rect x="{x:.2f}" y="{y - 5.0:.2f}" width="{length:.2f}" height="10.0" fill="#38bdf8" opacity="0.10" stroke="#0284c7" stroke-width="0.28" stroke-dasharray="1.6 1.2" />'
    if kind == "avoidance_corridor":
        width = float(feature.get("width", 10.0))
        return f'<rect x="{x - 5.0:.2f}" y="{y - width / 2:.2f}" width="22.0" height="{width:.2f}" fill="#22c55e" opacity="0.09" stroke="#16a34a" stroke-width="0.25" stroke-dasharray="1.6 1.2" />'
    return ""


def _lane_count(scenario: Scenario) -> int:
    for feature in scenario.map_features:
        if str(feature.get("kind", "")) == "route_corridor":
            try:
                return max(1, int(feature.get("lane_count", 1)))
            except (TypeError, ValueError):
                return 1
    return 1


def _offset_ribbon(points: list[tuple[float, float]], offset_m: float) -> list[tuple[float, float]]:
    if not points:
        return []
    if len(points) == 1:
        return [points[0]]
    normals: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        prev_point = points[index - 1] if index > 0 else points[index]
        next_point = points[index + 1] if index < len(points) - 1 else points[index]
        dx = next_point[0] - prev_point[0]
        dy = next_point[1] - prev_point[1]
        norm = math.hypot(dx, dy)
        if norm <= 1e-9:
            normals.append((0.0, 1.0))
            continue
        normals.append((-dy / norm, dx / norm))
    return [(point[0] + nx * offset_m, point[1] + ny * offset_m) for point, (nx, ny) in zip(points, normals)]


def _road_surface_svg(scenario: Scenario, lane: list[tuple[float, float]]) -> list[str]:
    lane_count = _lane_count(scenario)
    half_width = float(scenario.lane_half_width)
    road_half_width = half_width * max(1.0, lane_count / 2.0)
    left_edge = _offset_ribbon(lane, road_half_width)
    right_edge = _offset_ribbon(lane, -road_half_width)
    left_shoulder = _offset_ribbon(lane, road_half_width + 1.4)
    right_shoulder = _offset_ribbon(lane, -road_half_width - 1.4)
    svg = [
        _polygon(left_shoulder + list(reversed(right_shoulder)), "#a6b09a", opacity=0.45),
        _polygon(left_edge + list(reversed(right_edge)), "#46515a", opacity=1.0),
        _polyline(left_edge, "#cbd5e1", 0.22, opacity=0.65),
        _polyline(right_edge, "#cbd5e1", 0.22, opacity=0.65),
    ]
    if lane_count > 1:
        lane_width = (road_half_width * 2.0) / lane_count
        for divider in range(1, lane_count):
            offset = -road_half_width + lane_width * divider
            dash = "2.4 2.0"
            color = "#f8fafc" if lane_count != 2 else "#facc15"
            svg.append(_polyline(_offset_ribbon(lane, offset), color, 0.28, dash=dash, opacity=0.9))
    else:
        svg.append(_polyline(lane, "#facc15", 0.22, dash="2.4 2.0", opacity=0.75))
    return svg


def _obstacle_svg(obstacle) -> str:
    if obstacle.kind == "ambient":
        return (
            f'<circle cx="{obstacle.x:.2f}" cy="{obstacle.y:.2f}" r="{obstacle.radius:.2f}" '
            f'fill="#94a3b8" opacity="0.28" />'
        )
    if obstacle.kind == "cone":
        r = obstacle.radius * 1.65
        points = [(obstacle.x, obstacle.y - r), (obstacle.x - r * 0.75, obstacle.y + r), (obstacle.x + r * 0.75, obstacle.y + r)]
        return _polygon(points, "#f97316", opacity=0.90, stroke="#fff7ed", width=0.10)
    if obstacle.kind in {"vehicle", "special_vehicle"}:
        width = max(obstacle.radius * 1.8, 1.6)
        length = max(obstacle.length or obstacle.radius * 3.2, width * 1.8)
        x = obstacle.x - length * 0.5
        y = obstacle.y - width * 0.5
        angle = obstacle.heading * 180.0 / math.pi
        return (
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{length:.2f}" height="{width:.2f}" rx="0.25" ry="0.25" '
            f'fill="#7c2d12" opacity="0.78" transform="rotate({angle:.2f} {obstacle.x:.2f} {obstacle.y:.2f})" />'
        )
    color = "#b45309" if obstacle.kind in {"occluder", "worker"} else "#a33d2b"
    return f'<circle cx="{obstacle.x:.2f}" cy="{obstacle.y:.2f}" r="{obstacle.radius:.2f}" fill="{color}" opacity="0.68" />'


def _ego_svg(trajectory: list[tuple[float, float]]) -> str:
    if not trajectory:
        return ""
    x, y = trajectory[-1]
    if len(trajectory) >= 2:
        px, py = trajectory[-2]
        heading = math.atan2(y - py, x - px)
    else:
        heading = 0.0
    length = 3.4
    width = 1.7
    rect_x = x - length * 0.5
    rect_y = y - width * 0.5
    angle = heading * 180.0 / math.pi
    return (
        f'<rect x="{rect_x:.2f}" y="{rect_y:.2f}" width="{length:.2f}" height="{width:.2f}" rx="0.32" '
        f'fill="#0f766e" stroke="#ecfeff" stroke-width="0.24" transform="rotate({angle:.2f} {x:.2f} {y:.2f})" />'
    )


def render_svg(path: Path, scenario: Scenario, rollout: Rollout) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    lane = interpolate_lane(scenario.lane_center)
    trajectory = [(step.x, step.y) for step in rollout.steps]

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {scenario.width} {scenario.height}">',
        '<rect width="100%" height="100%" fill="#dfe7d4" />',
        f'<text x="3" y="5" font-size="3.2" fill="#172033">{scenario.cluster} seed={scenario.seed} success={rollout.success}</text>',
    ]
    svg.extend(_road_surface_svg(scenario, lane))

    for feature in scenario.map_features:
        feature_svg = _map_feature_svg(feature)
        if feature_svg:
            svg.append(feature_svg)

    for obstacle in scenario.obstacles:
        svg.append(_obstacle_svg(obstacle))

    for actor in scenario.actors:
        active_ticks = [actor.active_from, min(actor.active_from + 18, actor.active_until), min(actor.active_from + 36, actor.active_until)]
        actor_path = [(actor_at_tick(actor, tick).x, actor_at_tick(actor, tick).y) for tick in active_ticks]
        svg.append(_polyline(actor_path, _actor_color(actor.kind), 0.34, dash="1 1", opacity=0.60))
        visible_tick = min(max(actor.active_from, rollout.steps[-1].t if rollout.steps else actor.active_from), actor.active_until)
        svg.append(_actor_svg(actor_at_tick(actor, visible_tick)))

    if trajectory:
        svg.append(_polyline(trajectory, "#e0f2fe", 1.9, opacity=0.92))
        svg.append(_polyline(trajectory, "#0284c7", 1.15, opacity=0.95))
        svg.append(_ego_svg(trajectory))

    sx, sy = scenario.start
    gx, gy = scenario.goal
    svg.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="1.6" fill="#0a9396" />')
    svg.append(f'<circle cx="{gx:.2f}" cy="{gy:.2f}" r="1.8" fill="#ee9b00" />')
    svg.append("</svg>")

    path.write_text("\n".join(svg))
