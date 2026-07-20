from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wod2sim.audit.trace_diagnostics import (
    diagnose_contract_trace,
    load_telemetry_trace,
    trace_runtime_summary,
)

CANVAS_SIZE = (1280, 720)
CAMERA_SIZE = (320, 150)
SOURCE_FPS = 10
MEDIA_WINDOW_FRAMES = 18
FINAL_HOLD_FRAMES = 25
PLOT_X_RANGE_M = (0.0, 60.0)
PLOT_Y_RANGE_M = (-0.5, 2.5)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render one camera comparison GIF from paired AlpaSim protocol replays."
    )
    parser.add_argument("--full", required=True, type=Path)
    parser.add_argument("--command", required=True, type=Path)
    parser.add_argument("--full-telemetry", required=True, type=Path)
    parser.add_argument("--command-telemetry", required=True, type=Path)
    parser.add_argument("--learned-full", required=True, type=Path)
    parser.add_argument("--learned-command", required=True, type=Path)
    parser.add_argument("--learned-full-telemetry", required=True, type=Path)
    parser.add_argument("--learned-command-telemetry", required=True, type=Path)
    parser.add_argument("--learned-checkpoint-url", required=True)
    parser.add_argument("--learned-checkpoint-sha256", required=True)
    parser.add_argument("--learned-runtime-image-id", required=True)
    parser.add_argument("--frames", required=True, type=Path)
    parser.add_argument("--video-output", required=True, type=Path)
    parser.add_argument("--preview-output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--docker-image-id", required=True)
    return parser.parse_args()


def _load_pillow() -> tuple[Any, Any, Any, Any]:
    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFont
    except ImportError as exc:
        raise SystemExit("Install the visualization extra: uv sync --extra viz") from exc
    return Image, ImageDraw, ImageEnhance, ImageFont


def _font(image_font: Any, size: int, *, bold: bool = False) -> Any:
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        if bold
        else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")
        if bold
        else Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return image_font.truetype(str(path), size=size)
    return image_font.load_default()


def _rounded_panel(
    canvas: Any,
    image_module: Any,
    image_draw: Any,
    box: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int],
) -> None:
    overlay = image_module.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = image_draw.Draw(overlay)
    draw.rounded_rectangle(box, radius=8, fill=fill, outline=outline, width=2)
    canvas.alpha_composite(overlay)


def _fit_camera(image: Any, frame: Any, size: tuple[int, int]) -> Any:
    target_width, target_height = size
    source_ratio = frame.width / frame.height
    target_ratio = target_width / target_height
    if source_ratio > target_ratio:
        crop_width = int(frame.height * target_ratio)
        left = (frame.width - crop_width) // 2
        frame = frame.crop((left, 0, left + crop_width, frame.height))
    else:
        crop_height = int(frame.width / target_ratio)
        top = max(0, (frame.height - crop_height) // 2)
        frame = frame.crop((0, top, frame.width, top + crop_height))
    return frame.resize((target_width, target_height), image.Resampling.LANCZOS)


def _route_frame_xy(
    route: list[list[float]],
    trajectory: list[list[float]],
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    origin = route[0] if route else (trajectory[0] if trajectory else (0.0, 0.0))
    x0, y0 = float(origin[0]), float(origin[1])
    def transform(
        points: list[list[float]],
        *,
        origin_x: float,
        origin_y: float,
    ) -> list[tuple[float, float]]:
        return [
            (
                float(point[0]) - origin_x,
                float(point[1]) - origin_y,
            )
            for point in points
        ]

    trajectory_origin = trajectory[0] if trajectory else (0.0, 0.0)
    return (
        transform(route, origin_x=x0, origin_y=y0),
        transform(
            trajectory,
            origin_x=float(trajectory_origin[0]),
            origin_y=float(trajectory_origin[1]),
        ),
    )


def _clip_forward_path(
    points: list[tuple[float, float]],
    *,
    maximum_x: float,
) -> list[tuple[float, float]]:
    clipped: list[tuple[float, float]] = []
    for point in points:
        if point[0] <= maximum_x:
            clipped.append(point)
            continue
        if clipped and point[0] > clipped[-1][0]:
            previous = clipped[-1]
            fraction = (maximum_x - previous[0]) / (point[0] - previous[0])
            clipped.append(
                (
                    maximum_x,
                    previous[1] + fraction * (point[1] - previous[1]),
                )
            )
        break
    return clipped


def _path_y_at_x(points: list[tuple[float, float]], x_value: float) -> float | None:
    for first, second in zip(points, points[1:]):
        if first[0] <= x_value <= second[0] and second[0] > first[0]:
            fraction = (x_value - first[0]) / (second[0] - first[0])
            return first[1] + fraction * (second[1] - first[1])
    return None


def _draw_path_plot(
    draw: Any,
    box: tuple[int, int, int, int],
    route: list[list[float]],
    trajectory: list[list[float]],
    *,
    color: tuple[int, int, int],
    route_dashed: bool,
    endpoint_label: str,
    label_font: Any,
    small_font: Any,
    axis_font: Any,
) -> float:
    left, top, right, bottom = box
    draw.rectangle(box, fill=(12, 18, 22), outline=(75, 88, 94), width=1)

    local_route, local_trajectory = _route_frame_xy(route, trajectory)
    local_route = _clip_forward_path(
        local_route,
        maximum_x=PLOT_X_RANGE_M[1],
    )
    local_trajectory = _clip_forward_path(
        local_trajectory,
        maximum_x=PLOT_X_RANGE_M[1],
    )
    plot_left, plot_top = left + 48, top + 36
    plot_right, plot_bottom = right - 16, bottom - 36
    x_scale = (plot_right - plot_left) / (
        PLOT_X_RANGE_M[1] - PLOT_X_RANGE_M[0]
    )
    y_scale = (plot_bottom - plot_top) / (
        PLOT_Y_RANGE_M[1] - PLOT_Y_RANGE_M[0]
    )

    def project(point: tuple[float, float]) -> tuple[int, int]:
        return (
            int(plot_left + (point[0] - PLOT_X_RANGE_M[0]) * x_scale),
            int(plot_bottom - (point[1] - PLOT_Y_RANGE_M[0]) * y_scale),
        )

    for x_tick in (0, 20, 40, 60):
        x_pixel, _ = project((float(x_tick), 0.0))
        draw.line(
            (x_pixel, plot_top, x_pixel, plot_bottom),
            fill=(38, 49, 54),
            width=1,
        )
        draw.text(
            (x_pixel - 7, plot_bottom + 7),
            str(x_tick),
            font=axis_font,
            fill=(145, 157, 161),
        )
    for y_tick in (0, 1, 2):
        _, y_pixel = project((0.0, float(y_tick)))
        draw.line(
            (plot_left, y_pixel, plot_right, y_pixel),
            fill=(38, 49, 54),
            width=1,
        )
        draw.text(
            (left + 20, y_pixel - 7),
            str(y_tick),
            font=axis_font,
            fill=(145, 157, 161),
        )
    draw.text(
        ((plot_left + plot_right) // 2 - 55, bottom - 18),
        "forward distance (m)",
        font=axis_font,
        fill=(145, 157, 161),
    )
    draw.text(
        (left + 10, top + 8),
        "lateral position (m)",
        font=axis_font,
        fill=(145, 157, 161),
    )

    if len(local_route) >= 2:
        route_pixels = [project(point) for point in local_route]
        if route_dashed:
            for index in range(0, len(route_pixels) - 1, 2):
                draw.line(
                    (route_pixels[index], route_pixels[index + 1]),
                    fill=(112, 119, 121),
                    width=2,
                )
        else:
            draw.line(route_pixels, fill=(222, 229, 230), width=3)
        for x_pixel, y_pixel in route_pixels:
            draw.ellipse(
                (x_pixel - 2, y_pixel - 2, x_pixel + 2, y_pixel + 2),
                fill=(222, 229, 230),
            )
    if len(local_trajectory) >= 2:
        trajectory_pixels = [project(point) for point in local_trajectory]
        draw.line(trajectory_pixels, fill=color, width=5)
        end_x, end_y = trajectory_pixels[-1]
        draw.ellipse((end_x - 5, end_y - 5, end_x + 5, end_y + 5), fill=color)

    draw.line((right - 244, top + 17, right - 216, top + 17), fill=(222, 229, 230), width=3)
    draw.text(
        (right - 208, top + 8),
        "route",
        font=small_font,
        fill=(199, 207, 209),
    )
    draw.line((right - 128, top + 17, right - 100, top + 17), fill=color, width=5)
    draw.text(
        (right - 92, top + 8),
        "policy output",
        font=small_font,
        fill=color,
    )

    route_y = (
        _path_y_at_x(local_route, local_trajectory[-1][0])
        if local_trajectory
        else None
    )
    endpoint_error = (
        abs(local_trajectory[-1][1] - route_y)
        if local_trajectory and route_y is not None
        else math.nan
    )
    if local_trajectory and route_y is not None:
        endpoint_x = local_trajectory[-1][0]
        route_pixel = project((endpoint_x, route_y))
        output_pixel = project(local_trajectory[-1])
        bracket_x = min(plot_right - 3, output_pixel[0] + 10)
        draw.line(
            (bracket_x, route_pixel[1], bracket_x, output_pixel[1]),
            fill=color,
            width=3,
        )
        draw.line(
            (bracket_x - 5, route_pixel[1], bracket_x + 5, route_pixel[1]),
            fill=color,
            width=2,
        )
        draw.line(
            (bracket_x - 5, output_pixel[1], bracket_x + 5, output_pixel[1]),
            fill=color,
            width=2,
        )
    draw.text(
        (left + 60, top + 42),
        f"{endpoint_label}: {endpoint_error:.2f} m",
        font=label_font,
        fill=color,
    )
    return endpoint_error


def _draw_badge(
    draw: Any,
    text: str,
    position: tuple[int, int],
    font: Any,
    *,
    fill: tuple[int, int, int],
) -> None:
    x_value, y_value = position
    bounds = draw.textbbox((x_value, y_value), text, font=font)
    padding_x, padding_y = 8, 4
    box = (
        bounds[0] - padding_x,
        bounds[1] - padding_y,
        bounds[2] + padding_x,
        bounds[3] + padding_y,
    )
    draw.rounded_rectangle(box, radius=5, fill=fill)
    draw.text((x_value, y_value), text, font=font, fill=(255, 255, 255))


def _render_frame(
    source_frame: Path,
    full_drive: dict[str, Any],
    command_drive: dict[str, Any],
) -> Any:
    image_module, image_draw, image_enhance, image_font = _load_pillow()
    source = image_module.open(source_frame).convert("RGB")
    source = _fit_camera(image_module, source, CAMERA_SIZE)
    source = image_enhance.Brightness(source).enhance(0.96)
    canvas = image_module.new("RGBA", CANVAS_SIZE, (8, 12, 15, 255))
    draw = image_draw.Draw(canvas)

    title_font = _font(image_font, 25, bold=True)
    subtitle_font = _font(image_font, 15)
    label_font = _font(image_font, 17, bold=True)
    body_font = _font(image_font, 15)
    outcome_font = _font(image_font, 18, bold=True)
    small_font = _font(image_font, 12)
    axis_font = _font(image_font, 11)

    title = "SAME ROUTE-FOLLOWING POLICY + SAME ALPASIM MESSAGES"
    title_bounds = draw.textbbox((0, 0), title, font=title_font)
    draw.text(
        ((CANVAS_SIZE[0] - (title_bounds[2] - title_bounds[0])) // 2, 12),
        title,
        font=title_font,
        fill=(248, 250, 250),
    )
    subtitle = "One boundary changes: waypoint coordinates are dropped or preserved"
    subtitle_bounds = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    draw.text(
        ((CANVAS_SIZE[0] - (subtitle_bounds[2] - subtitle_bounds[0])) // 2, 46),
        subtitle,
        font=subtitle_font,
        fill=(188, 199, 202),
    )

    left_x, right_x = 20, 650
    panel_width = 610
    draw.rounded_rectangle(
        (left_x, 72, left_x + panel_width, 150),
        radius=6,
        fill=(30, 20, 18),
        outline=(193, 93, 66),
        width=2,
    )
    draw.rounded_rectangle(
        (right_x, 72, right_x + panel_width, 150),
        radius=6,
        fill=(15, 29, 27),
        outline=(67, 157, 143),
        width=2,
    )
    draw.text(
        (left_x + 18, 82),
        "LOSSY BOUNDARY: INTENTIONAL TEST ABLATION",
        font=label_font,
        fill=(246, 151, 118),
    )
    draw.text(
        (right_x + 18, 82),
        "PRESERVED BOUNDARY: WOD2SIM CONTRACT",
        font=label_font,
        fill=(109, 214, 190),
    )
    draw.text(
        (left_x + 18, 113),
        "20 (x,y) waypoints  ->  DROP COORDINATES  ->  LEFT only",
        font=body_font,
        fill=(239, 225, 220),
    )
    draw.text(
        (right_x + 18, 113),
        "20 (x,y) waypoints  ->  PRESERVE  ->  20 (x,y) waypoints",
        font=body_font,
        fill=(220, 238, 234),
    )

    full_route = full_drive["route_waypoints_xy"]
    full_endpoint = full_drive["trajectory_ego_xy"][-1]
    command_endpoint = command_drive["trajectory_ego_xy"][-1]
    endpoint_separation = math.dist(full_endpoint, command_endpoint)
    draw.text(
        (left_x + 16, 164),
        "POLICY CANNOT SEE THE CURVE",
        font=outcome_font,
        fill=(246, 151, 118),
    )
    draw.text(
        (right_x + 16, 164),
        "POLICY RECEIVES THE CURVE",
        font=outcome_font,
        fill=(109, 214, 190),
    )
    plot_top = 190
    plot_bottom = 455
    command_error = _draw_path_plot(
        draw,
        (left_x + 16, plot_top, left_x + panel_width - 16, plot_bottom),
        full_route,
        command_drive["trajectory_ego_xy"],
        color=(235, 103, 73),
        route_dashed=True,
        endpoint_label="5 s endpoint miss",
        label_font=label_font,
        small_font=small_font,
        axis_font=axis_font,
    )
    full_error = _draw_path_plot(
        draw,
        (right_x + 16, plot_top, right_x + panel_width - 16, plot_bottom),
        full_route,
        full_drive["trajectory_ego_xy"],
        color=(71, 207, 174),
        route_dashed=False,
        endpoint_label="5 s endpoint miss",
        label_font=label_font,
        small_font=small_font,
        axis_font=axis_font,
    )
    separation_text = (
        f"Returned endpoints are {endpoint_separation:.2f} m apart "
        f"({command_error:.2f} m vs {full_error:.2f} m from route)"
    )
    separation_bounds = draw.textbbox((0, 0), separation_text, font=label_font)
    draw.text(
        (
            (CANVAS_SIZE[0] - (separation_bounds[2] - separation_bounds[0])) // 2,
            466,
        ),
        separation_text,
        font=label_font,
        fill=(238, 242, 242),
    )

    camera_y = 522
    left_camera_x, right_camera_x = 255, 705
    draw.text(
        (left_camera_x + 45, 498),
        "LOSSY ARM CAMERA",
        font=small_font,
        fill=(192, 202, 204),
    )
    draw.text(
        (right_camera_x + 36, 498),
        "PRESERVED ARM CAMERA",
        font=small_font,
        fill=(192, 202, 204),
    )
    canvas.alpha_composite(source.convert("RGBA"), (left_camera_x, camera_y))
    canvas.alpha_composite(source.convert("RGBA"), (right_camera_x, camera_y))
    draw = image_draw.Draw(canvas)
    draw.rectangle(
        (
            left_camera_x,
            camera_y,
            left_camera_x + CAMERA_SIZE[0] - 1,
            camera_y + CAMERA_SIZE[1] - 1,
        ),
        outline=(193, 93, 66),
        width=2,
    )
    draw.rectangle(
        (
            right_camera_x,
            camera_y,
            right_camera_x + CAMERA_SIZE[0] - 1,
            camera_y + CAMERA_SIZE[1] - 1,
        ),
        outline=(67, 157, 143),
        width=2,
    )
    draw.text(
        (624, camera_y + 56),
        "=",
        font=_font(image_font, 34, bold=True),
        fill=(220, 227, 228),
    )
    footer = (
        "Identical recorded frames control the input. This replay is non-reactive; "
        "the plots show the returned trajectories."
    )
    footer_bounds = draw.textbbox((0, 0), footer, font=small_font)
    draw.text(
        (
            (CANVAS_SIZE[0] - (footer_bounds[2] - footer_bounds[0])) // 2,
            687,
        ),
        footer,
        font=small_font,
        fill=(157, 169, 173),
    )
    return canvas.convert("RGB")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _render_media(
    full: dict[str, Any],
    command: dict[str, Any],
    frame_paths: list[Path],
    *,
    video_output: Path,
    preview_output: Path,
) -> dict[str, float | int]:
    full_drives = full["drives"]
    command_drives = command["drives"]
    count = min(len(full_drives), len(command_drives))
    if count < 1:
        raise ValueError("paired replay contains no camera/Drive frames")
    frame_by_name = {path.name: path for path in frame_paths}
    paired_frames: list[Path] = []
    for drive in full_drives[:count]:
        frame_name = str(drive.get("camera_frame", ""))
        if frame_name not in frame_by_name:
            raise ValueError(f"missing camera frame for Drive RPC: {frame_name!r}")
        paired_frames.append(frame_by_name[frame_name])
    endpoint_separations = [
        math.dist(
            full_drive["trajectory_ego_xy"][-1],
            command_drive["trajectory_ego_xy"][-1],
        )
        for full_drive, command_drive in zip(
            full_drives,
            command_drives,
            strict=True,
        )
    ]
    end_drive = max(
        range(count),
        key=endpoint_separations.__getitem__,
    )
    start_drive = max(0, end_drive - MEDIA_WINDOW_FRAMES + 1)
    displayed_drive_indices = list(range(start_drive, end_drive + 1))
    video_output.parent.mkdir(parents=True, exist_ok=True)
    preview_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wod2sim-replay-video-") as temp_dir:
        temp = Path(temp_dir)
        for output_index, drive_index in enumerate(displayed_drive_indices):
            rendered = _render_frame(
                paired_frames[drive_index],
                full_drives[drive_index],
                command_drives[drive_index],
            )
            rendered.save(temp / f"frame-{output_index:04d}.png", format="PNG")
        final_frame = _render_frame(
            paired_frames[end_drive],
            full_drives[end_drive],
            command_drives[end_drive],
        )
        displayed_count = len(displayed_drive_indices)
        for offset in range(FINAL_HOLD_FRAMES):
            final_frame.save(
                temp / f"frame-{displayed_count + offset:04d}.png",
                format="PNG",
            )

        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(SOURCE_FPS),
                "-i",
                str(temp / "frame-%04d.png"),
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(video_output),
            ],
            check=True,
        )
        palette = temp / "palette.png"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(SOURCE_FPS),
                "-i",
                str(temp / "frame-%04d.png"),
                "-vf",
                "palettegen=max_colors=128:stats_mode=diff",
                str(palette),
            ],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(SOURCE_FPS),
                "-i",
                str(temp / "frame-%04d.png"),
                "-i",
                str(palette),
                "-lavfi",
                "paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                "-loop",
                "0",
                str(preview_output),
            ],
            check=True,
        )
    return {
        "displayed_camera_frames": len(displayed_drive_indices),
        "duration_seconds": (
            len(displayed_drive_indices) + FINAL_HOLD_FRAMES
        )
        / SOURCE_FPS,
        "end_drive_index": end_drive,
        "maximum_endpoint_separation_m": round(
            endpoint_separations[end_drive],
            6,
        ),
        "start_drive_index": start_drive,
    }


def _cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                return line.split(":", maxsplit=1)[1].strip()
    return platform.processor() or "unknown"


def _source_file(path: Path) -> dict[str, str]:
    return {
        "path": _manifest_path(path),
        "sha256": _sha256(path),
    }


def _arm_manifest(
    *,
    result_path: Path,
    telemetry_path: Path,
    diagnostics: list[Any],
    events: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "result_path": _manifest_path(result_path),
        "result_sha256": _sha256(result_path),
        "telemetry_path": _manifest_path(telemetry_path),
        "telemetry_sha256": _sha256(telemetry_path),
        "diagnostics": [item.to_dict() for item in diagnostics],
        "runtime": trace_runtime_summary(events),
        "results": result["results"],
    }


def _validate_result(
    result: dict[str, Any],
    *,
    label: str,
    expected_mode: str,
    expected_model: str,
) -> None:
    adapter = result.get("adapter")
    drives = result.get("drives")
    results = result.get("results")
    if (
        result.get("schema") != "wod2sim_alpasim_protocol_replay_v1"
        or not isinstance(adapter, dict)
        or adapter.get("mode") != expected_mode
        or adapter.get("version_id") != f"wod2sim-challenge-{expected_model}"
        or not isinstance(drives, list)
        or not isinstance(results, dict)
    ):
        raise ValueError(f"{label} replay metadata is inconsistent")
    drive_calls = results.get("drive_calls")
    finite_outputs = results.get("finite_drive_outputs")
    nonstationary_outputs = results.get("nonstationary_drive_outputs")
    if (
        drive_calls != len(drives)
        or drive_calls != 60
        or finite_outputs != drive_calls
        or nonstationary_outputs != drive_calls
        or any(
            not isinstance(drive, dict)
            or drive.get("trajectory_finite") is not True
            or not isinstance(drive.get("trajectory_progress_m"), (int, float))
            or float(drive["trajectory_progress_m"]) <= 1.0
            for drive in drives
        )
    ):
        raise ValueError(f"{label} replay outputs are incomplete, invalid, or stationary")


def main() -> int:
    args = _parse_args()
    full = _read_json(args.full)
    command = _read_json(args.command)
    learned_full = _read_json(args.learned_full)
    learned_command = _read_json(args.learned_command)
    source_hashes = {
        result["source"]["asl_sha256"]
        for result in (full, command, learned_full, learned_command)
    }
    if len(source_hashes) != 1:
        raise ValueError("paired replay arms use different ASL sources")
    _validate_result(
        full,
        label="route-following full-contract",
        expected_mode="full_contract",
        expected_model="route_following",
    )
    _validate_result(
        command,
        label="route-following command-only",
        expected_mode="command_only_route",
        expected_model="route_following",
    )
    _validate_result(
        learned_full,
        label="NAVSIM EgoStatusMLP full-contract",
        expected_mode="full_contract",
        expected_model="navsim_ego_status_mlp",
    )
    _validate_result(
        learned_command,
        label="NAVSIM EgoStatusMLP command-only",
        expected_mode="command_only_route",
        expected_model="navsim_ego_status_mlp",
    )
    frame_paths = sorted(
        path
        for path in args.frames.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    render_summary = _render_media(
        full,
        command,
        frame_paths,
        video_output=args.video_output,
        preview_output=args.preview_output,
    )

    full_events = load_telemetry_trace(args.full_telemetry)
    command_events = load_telemetry_trace(args.command_telemetry)
    learned_full_events = load_telemetry_trace(args.learned_full_telemetry)
    learned_command_events = load_telemetry_trace(args.learned_command_telemetry)
    full_diagnostics = diagnose_contract_trace(full_events)
    command_diagnostics = diagnose_contract_trace(command_events)
    learned_full_diagnostics = diagnose_contract_trace(learned_full_events)
    learned_command_diagnostics = diagnose_contract_trace(learned_command_events)
    command_codes = [item.code for item in command_diagnostics]
    learned_command_codes = [item.code for item in learned_command_diagnostics]
    if full_diagnostics or learned_full_diagnostics:
        raise ValueError(
            "full-contract replay failed audit: "
            + ", ".join(
                item.code for item in [*full_diagnostics, *learned_full_diagnostics]
            )
        )
    if (
        command_codes != ["semantic.command_only"]
        or learned_command_codes
    ):
        raise ValueError(
            "policy-aware command-only replay diagnostics are incorrect: "
            + ", ".join([*command_codes, *learned_command_codes])
        )
    learned_drive_events = [
        event
        for event in [*learned_full_events, *learned_command_events]
        if event.get("event") == "drive"
    ]
    if (
        len(learned_drive_events) != 120
        or {event.get("model") for event in learned_drive_events}
        != {"navsim_ego_status_mlp"}
        or {event.get("checkpoint_sha256") for event in learned_drive_events}
        != {args.learned_checkpoint_sha256}
        or {event.get("model_input_contract") for event in learned_drive_events}
        != {"velocity_xy+acceleration_xy+discrete_command"}
        or {event.get("route_geometry_consumed") for event in learned_drive_events}
        != {False}
    ):
        raise ValueError("learned replay telemetry does not match the pinned checkpoint")
    for full_drive, command_drive in zip(
        learned_full["drives"],
        learned_command["drives"],
        strict=True,
    ):
        if (
            full_drive["time_now_us"] != command_drive["time_now_us"]
            or full_drive["trajectory_ego_xy"]
            != command_drive["trajectory_ego_xy"]
        ):
            raise ValueError(
                "command-only NAVSIM EgoStatusMLP changed despite its command-only "
                "input signature"
            )

    manifest = {
        "schema": "wod2sim_alpasim_replay_demo_manifest_v3",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "claim_scope": (
            "Executed client-to-service gRPC protocol replay with recorded camera, "
            "route, egomotion, and Drive messages. The replay is non-reactive: "
            "adapter outputs do not change the recorded camera or ego-state sequence."
        ),
        "source": full["source"],
        "execution_environment": {
            "cpu_model": _cpu_model(),
            "docker_image_id": args.docker_image_id,
            "learned_runtime_image_id": args.learned_runtime_image_id,
            "grpc_transport": "host loopback",
            "host_machine": platform.machine(),
            "host_platform": platform.platform(),
            "python": sys.version.split()[0],
            "run_order": [
                "full_contract",
                "command_only_route",
                "navsim_ego_status_mlp_full_contract",
                "navsim_ego_status_mlp_command_only_route",
            ],
            "timer": "time.perf_counter_ns",
            "wod2sim_commit": full["adapter"]["git_hash"],
        },
        "reproduction_sources": {
            "client": _source_file(Path("scripts/run_alpasim_replay_client.py")),
            "challenge_driver": _source_file(
                Path("src/wod2sim/challenge/e2e_driver.py")
            ),
            "navsim_ego_status_mlp": _source_file(
                Path("src/wod2sim/simulator/navsim_ego_status_mlp.py")
            ),
            "renderer": _source_file(Path("scripts/generate_alpasim_replay_video.py")),
            "runner": _source_file(Path("scripts/run_alpasim_replay_demo.sh")),
        },
        "learned_policy": {
            "name": "ego_status_mlp_seed_0",
            "family": "NAVSIM v1.1 EgoStatusMLP blind learned baseline",
            "checkpoint_url": args.learned_checkpoint_url,
            "checkpoint_sha256": args.learned_checkpoint_sha256,
            "checkpoint_repository": "autonomousvision/navsim_baselines",
            "checkpoint_revision": "32d89c0ae6e7c13c311f4a034002006c250afab0",
            "license": "Apache-2.0",
            "navsim_source_commit": "0811876c274e8b058ab2be9b3dcd4d37bd23f177",
            "input_contract": [
                "velocity_xy",
                "acceleration_xy",
                "discrete_command",
            ],
            "route_geometry_consumed": False,
            "runtime_device": "cpu",
            "trained_on_navsim": True,
            "visual_policy": False,
            "redistributed_in_wod2sim": False,
        },
        "arms": {
            "full_contract": _arm_manifest(
                result_path=args.full,
                telemetry_path=args.full_telemetry,
                diagnostics=full_diagnostics,
                events=full_events,
                result=full,
            ),
            "command_only_route": _arm_manifest(
                result_path=args.command,
                telemetry_path=args.command_telemetry,
                diagnostics=command_diagnostics,
                events=command_events,
                result=command,
            ),
            "navsim_ego_status_mlp_full_contract": _arm_manifest(
                result_path=args.learned_full,
                telemetry_path=args.learned_full_telemetry,
                diagnostics=learned_full_diagnostics,
                events=learned_full_events,
                result=learned_full,
            ),
            "navsim_ego_status_mlp_command_only_route": _arm_manifest(
                result_path=args.learned_command,
                telemetry_path=args.learned_command_telemetry,
                diagnostics=learned_command_diagnostics,
                events=learned_command_events,
                result=learned_command,
            ),
        },
        "media": {
            "camera_frames": len(
                {str(drive["camera_frame"]) for drive in full["drives"]}
            ),
            **render_summary,
            "video": {
                "path": _manifest_path(args.video_output),
                "sha256": _sha256(args.video_output),
                "bytes": args.video_output.stat().st_size,
                "format": "H.264 MP4",
            },
            "readme_preview": {
                "path": _manifest_path(args.preview_output),
                "sha256": _sha256(args.preview_output),
                "bytes": args.preview_output.stat().st_size,
                "format": "animated GIF",
            },
        },
        "reproduction": "scripts/run_alpasim_replay_demo.sh",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest["media"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
