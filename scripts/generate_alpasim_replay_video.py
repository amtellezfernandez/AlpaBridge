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

CANVAS_SIZE = (960, 540)
CAMERA_HEIGHT = 310
SOURCE_FPS = 10


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render one camera comparison GIF from paired AlpaSim protocol replays."
    )
    parser.add_argument("--full", required=True, type=Path)
    parser.add_argument("--command", required=True, type=Path)
    parser.add_argument("--full-telemetry", required=True, type=Path)
    parser.add_argument("--command-telemetry", required=True, type=Path)
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


def _fit_camera(image: Any, frame: Any) -> Any:
    target_width, target_height = CANVAS_SIZE[0], CAMERA_HEIGHT
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


def _relative_xy(points: list[list[float]]) -> list[tuple[float, float]]:
    if not points:
        return []
    x0, y0 = float(points[0][0]), float(points[0][1])
    translated = [(float(point[0]) - x0, float(point[1]) - y0) for point in points]
    heading = 0.0
    for x_value, y_value in translated[1:]:
        if math.hypot(x_value, y_value) > 0.25:
            heading = math.atan2(y_value, x_value)
            break
    cos_heading = math.cos(-heading)
    sin_heading = math.sin(-heading)
    return [
        (
            cos_heading * x_value - sin_heading * y_value,
            sin_heading * x_value + cos_heading * y_value,
        )
        for x_value, y_value in translated
    ]


def _draw_path_plot(
    draw: Any,
    box: tuple[int, int, int, int],
    route: list[list[float]],
    trajectory: list[list[float]],
    *,
    color: tuple[int, int, int],
    route_visible: bool,
) -> None:
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=5, fill=(12, 18, 22), outline=(75, 88, 94), width=1)
    center_y = (top + bottom) / 2
    draw.line((left + 8, center_y, right - 8, center_y), fill=(72, 80, 84), width=1)
    draw.line((left + 8, top + 8, left + 8, bottom - 8), fill=(72, 80, 84), width=1)

    local_trajectory = _relative_xy(trajectory)
    local_route = [(float(point[0]), float(point[1])) for point in route]
    values = [*local_trajectory, *local_route]
    max_x = max((point[0] for point in values), default=1.0)
    max_y = max((abs(point[1]) for point in values), default=1.0)
    x_scale = (right - left - 20) / max(1.0, max_x)
    y_scale = (bottom - top - 18) / max(4.0, 2.0 * max_y)

    def project(point: tuple[float, float]) -> tuple[int, int]:
        return (
            int(left + 8 + max(0.0, point[0]) * x_scale),
            int(center_y - point[1] * y_scale),
        )

    if route_visible and len(local_route) >= 2:
        route_pixels = [project(point) for point in local_route]
        draw.line(route_pixels, fill=(170, 180, 183), width=2)
    if len(local_trajectory) >= 2:
        trajectory_pixels = [project(point) for point in local_trajectory]
        draw.line(trajectory_pixels, fill=color, width=4)
        end_x, end_y = trajectory_pixels[-1]
        draw.ellipse((end_x - 3, end_y - 3, end_x + 3, end_y + 3), fill=color)


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
    *,
    elapsed_s: float,
    final_hold: bool,
) -> Any:
    image_module, image_draw, image_enhance, image_font = _load_pillow()
    source = image_module.open(source_frame).convert("RGB")
    source = _fit_camera(image_module, source)
    source = image_enhance.Brightness(source).enhance(0.78)
    canvas = image_module.new("RGBA", CANVAS_SIZE, (8, 12, 15, 255))
    canvas.alpha_composite(source.convert("RGBA"), (0, 0))

    top_overlay = image_module.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    top_draw = image_draw.Draw(top_overlay)
    top_draw.rectangle((0, 0, CANVAS_SIZE[0], 78), fill=(5, 10, 13, 220))
    top_draw.rectangle(
        (0, CAMERA_HEIGHT - 42, CANVAS_SIZE[0], CAMERA_HEIGHT),
        fill=(5, 10, 13, 205),
    )
    canvas.alpha_composite(top_overlay)
    draw = image_draw.Draw(canvas)

    title_font = _font(image_font, 27, bold=True)
    subtitle_font = _font(image_font, 15)
    label_font = _font(image_font, 17, bold=True)
    body_font = _font(image_font, 13)
    small_font = _font(image_font, 11)
    metric_font = _font(image_font, 14, bold=True)

    draw.text(
        (22, 14),
        "FORMAT LOSS CAN LOOK LIKE POLICY FAILURE",
        font=title_font,
        fill=(248, 250, 250),
    )
    draw.text(
        (23, 48),
        "Same camera, ego state, and policy. Only the route representation changes.",
        font=subtitle_font,
        fill=(194, 205, 209),
    )
    _draw_badge(
        draw,
        "REAL RPC REPLAY",
        (809, 22),
        small_font,
        fill=(34, 102, 112),
    )
    draw.text(
        (22, CAMERA_HEIGHT - 30),
        "Recorded front-camera RPC stream",
        font=small_font,
        fill=(229, 234, 235),
    )
    draw.text(
        (728, CAMERA_HEIGHT - 30),
        f"non-reactive replay  t={elapsed_s:04.1f}s",
        font=small_font,
        fill=(237, 193, 104),
    )

    panel_top = CAMERA_HEIGHT + 10
    panel_bottom = CANVAS_SIZE[1] - 32
    left_box = (14, panel_top, 470, panel_bottom)
    right_box = (490, panel_top, 946, panel_bottom)
    _rounded_panel(
        canvas,
        image_module,
        image_draw,
        left_box,
        fill=(30, 22, 20, 245),
        outline=(193, 93, 66, 255),
    )
    _rounded_panel(
        canvas,
        image_module,
        image_draw,
        right_box,
        fill=(15, 29, 28, 245),
        outline=(67, 157, 143, 255),
    )
    draw = image_draw.Draw(canvas)

    draw.text(
        (30, panel_top + 12),
        "COMMAND-ONLY FORMAT",
        font=label_font,
        fill=(246, 151, 118),
    )
    draw.text(
        (506, panel_top + 12),
        "ROUTE-PRESERVING FORMAT",
        font=label_font,
        fill=(109, 214, 190),
    )
    command_route = command_drive["route_waypoints_xy"]
    full_route = full_drive["route_waypoints_xy"]
    draw.text(
        (30, panel_top + 39),
        f"{len(command_route)} route points arrive, policy receives one command",
        font=body_font,
        fill=(222, 214, 211),
    )
    draw.text(
        (506, panel_top + 39),
        f"{len(full_route)} route points retained at prediction time",
        font=body_font,
        fill=(207, 224, 220),
    )

    plot_top = panel_top + 63
    plot_bottom = panel_bottom - 12
    _draw_path_plot(
        draw,
        (30, plot_top, 238, plot_bottom),
        command_route,
        command_drive["trajectory_xyz"],
        color=(235, 103, 73),
        route_visible=False,
    )
    _draw_path_plot(
        draw,
        (506, plot_top, 714, plot_bottom),
        full_route,
        full_drive["trajectory_xyz"],
        color=(71, 207, 174),
        route_visible=True,
    )
    draw.text((45, plot_top + 8), "output path", font=small_font, fill=(235, 103, 73))
    draw.text((521, plot_top + 8), "route + output", font=small_font, fill=(185, 218, 210))

    command_latency = float(command_drive["rpc_latency_ms"])
    full_latency = float(full_drive["rpc_latency_ms"])
    draw.text(
        (253, plot_top + 7),
        f"Drive RPC   {command_latency:5.2f} ms",
        font=metric_font,
        fill=(242, 242, 242),
    )
    draw.text(
        (253, plot_top + 34),
        f"Output      {command_drive['trajectory_points']:2d} finite points",
        font=body_font,
        fill=(214, 214, 214),
    )
    draw.text(
        (253, plot_top + 60),
        "RPC status",
        font=body_font,
        fill=(206, 210, 211),
    )
    _draw_badge(
        draw,
        "ACCEPT",
        (358, plot_top + 58),
        small_font,
        fill=(137, 105, 28),
    )
    draw.text(
        (253, plot_top + 87),
        "Contract audit",
        font=body_font,
        fill=(206, 210, 211),
    )
    _draw_badge(
        draw,
        "REJECT",
        (358, plot_top + 85),
        small_font,
        fill=(166, 58, 47),
    )
    draw.text(
        (253, plot_top + 112),
        "semantic.command_only",
        font=small_font,
        fill=(246, 151, 118),
    )

    draw.text(
        (729, plot_top + 7),
        f"Drive RPC   {full_latency:5.2f} ms",
        font=metric_font,
        fill=(242, 242, 242),
    )
    draw.text(
        (729, plot_top + 34),
        f"Output      {full_drive['trajectory_points']:2d} finite points",
        font=body_font,
        fill=(214, 214, 214),
    )
    draw.text(
        (729, plot_top + 61),
        "Contract audit",
        font=body_font,
        fill=(206, 210, 211),
    )
    _draw_badge(
        draw,
        "ACCEPT",
        (834, plot_top + 59),
        small_font,
        fill=(34, 124, 101),
    )
    draw.text(
        (729, plot_top + 91),
        "route source:",
        font=small_font,
        fill=(176, 190, 189),
    )
    draw.text(
        (729, plot_top + 110),
        "alpasim_waypoints",
        font=small_font,
        fill=(109, 214, 190),
    )

    if final_hold:
        _draw_badge(
            draw,
            "60 / 60 DRIVE RPCs COMPLETE",
            (363, CAMERA_HEIGHT - 30),
            body_font,
            fill=(28, 97, 106),
        )
    draw.text(
        (18, CANVAS_SIZE[1] - 18),
        "Official AlpaSim Apache integration replay @ 049f70f. "
        "Outputs do not alter recorded frames.",
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
) -> None:
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
    video_output.parent.mkdir(parents=True, exist_ok=True)
    preview_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wod2sim-replay-video-") as temp_dir:
        temp = Path(temp_dir)
        for index in range(count):
            rendered = _render_frame(
                paired_frames[index],
                full_drives[index],
                command_drives[index],
                elapsed_s=index / SOURCE_FPS,
                final_hold=False,
            )
            rendered.save(temp / f"frame-{index:04d}.png", format="PNG")
        final_frame = _render_frame(
            paired_frames[count - 1],
            full_drives[count - 1],
            command_drives[count - 1],
            elapsed_s=(count - 1) / SOURCE_FPS,
            final_hold=True,
        )
        for offset in range(20):
            final_frame.save(temp / f"frame-{count + offset:04d}.png", format="PNG")

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


def main() -> int:
    args = _parse_args()
    full = _read_json(args.full)
    command = _read_json(args.command)
    if full["source"]["asl_sha256"] != command["source"]["asl_sha256"]:
        raise ValueError("paired replay arms use different ASL sources")
    frame_paths = sorted(
        path
        for path in args.frames.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    _render_media(
        full,
        command,
        frame_paths,
        video_output=args.video_output,
        preview_output=args.preview_output,
    )

    full_events = load_telemetry_trace(args.full_telemetry)
    command_events = load_telemetry_trace(args.command_telemetry)
    full_diagnostics = diagnose_contract_trace(full_events)
    command_diagnostics = diagnose_contract_trace(command_events)
    command_codes = [item.code for item in command_diagnostics]
    if full_diagnostics:
        raise ValueError(
            "full-contract replay failed audit: "
            + ", ".join(item.code for item in full_diagnostics)
        )
    if command_codes != ["semantic.command_only"]:
        raise ValueError(
            "command-only replay did not isolate semantic.command_only: "
            + ", ".join(command_codes)
        )

    manifest = {
        "schema": "wod2sim_alpasim_replay_demo_manifest_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "claim_scope": (
            "Executed end-to-end gRPC protocol replay with recorded camera, route, "
            "egomotion, and Drive messages. The replay is non-reactive: adapter "
            "outputs do not change the recorded camera or ego-state sequence."
        ),
        "source": full["source"],
        "execution_environment": {
            "cpu_model": _cpu_model(),
            "docker_image_id": args.docker_image_id,
            "grpc_transport": "host loopback",
            "host_machine": platform.machine(),
            "host_platform": platform.platform(),
            "python": sys.version.split()[0],
            "run_order": ["full_contract", "command_only_route"],
            "timer": "time.perf_counter_ns",
            "wod2sim_commit": full["adapter"]["git_hash"],
        },
        "reproduction_sources": {
            "client": _source_file(Path("scripts/run_alpasim_replay_client.py")),
            "renderer": _source_file(Path("scripts/generate_alpasim_replay_video.py")),
            "runner": _source_file(Path("scripts/run_alpasim_replay_demo.sh")),
        },
        "arms": {
            "full_contract": {
                "result_path": _manifest_path(args.full),
                "result_sha256": _sha256(args.full),
                "telemetry_path": _manifest_path(args.full_telemetry),
                "telemetry_sha256": _sha256(args.full_telemetry),
                "diagnostics": [],
                "runtime": trace_runtime_summary(full_events),
                "results": full["results"],
            },
            "command_only_route": {
                "result_path": _manifest_path(args.command),
                "result_sha256": _sha256(args.command),
                "telemetry_path": _manifest_path(args.command_telemetry),
                "telemetry_sha256": _sha256(args.command_telemetry),
                "diagnostics": [item.to_dict() for item in command_diagnostics],
                "runtime": trace_runtime_summary(command_events),
                "results": command["results"],
            },
        },
        "media": {
            "camera_frames": len(
                {str(drive["camera_frame"]) for drive in full["drives"]}
            ),
            "duration_seconds": 8.0,
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
