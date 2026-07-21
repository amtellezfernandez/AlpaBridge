#!/usr/bin/env python3
"""Regenerate the README's before/after example images.

Builds a synthetic-but-structurally-real PredictionInput (the same shape
`tests/test_alpasim_integration.py::_baseline_prediction_input` uses), runs
the real, shipped `route_following` preset against it, and renders:

- docs/assets/readme/example-input.png: the actual input fields the adapter
  reads, next to a real camera frame reused from a retained evidence video.
- docs/assets/readme/example-output.png: the real trajectory_xy the model
  returned, plotted.

No AlpaSim, GPU, Docker, or checkpoint is required. The `viz` extra brings
in matplotlib; extracting the camera frame needs `ffmpeg` on PATH (skipped
gracefully if missing). Run with:

    uv sync --extra viz
    uv run python scripts/render_readme_example.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpabridge.simulator.alpasim_contract import DriveCommand
from alpabridge.simulator.baseline_drivers import RouteFollowingAlpaSimModel

ACCENT = "#0f766e"
OUT_DIR = ROOT / "docs" / "assets" / "readme"
SOURCE_VIDEO = ROOT / "artifacts" / "external" / "alpasim_dynamic_camera_rollout" / "camera.mp4"


def _build_prediction_input() -> SimpleNamespace:
    """Same fixture shape as tests/test_alpasim_integration.py::_baseline_prediction_input."""
    route_waypoints = [
        {"x": 0.0, "y": 0.0},
        {"x": 8.0, "y": 0.6},
        {"x": 16.0, "y": 2.8},
        {"x": 24.0, "y": 6.5},
        {"x": 32.0, "y": 9.0},
        {"x": 40.0, "y": 9.6},
    ]
    return SimpleNamespace(
        camera_images={
            "camera_front_wide_120fov": [
                SimpleNamespace(
                    image=np.full((4, 4, 3), 180, dtype=np.uint8),
                    timestamp_us=2_000_000_000,
                )
            ]
        },
        command=DriveCommand.RIGHT,
        speed=6.0,
        acceleration=0.2,
        ego_pose_history=[object()],
        scene_id="readme-example-scene",
        session_uuid="readme-example-session",
        runtime_random_seed=7,
        debug_scene_id="readme-example",
        route_waypoints=route_waypoints,
        alpasignal={"hazards": []},
    ), route_waypoints


def _extract_camera_frame(dest: Path, *, timestamp_s: float = 8.0) -> bool:
    if not SOURCE_VIDEO.is_file():
        print(f"skip: {SOURCE_VIDEO} not found", file=sys.stderr)
        return False
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(timestamp_s), "-i", str(SOURCE_VIDEO),
            "-vframes", "1", str(dest),
        ],
        check=False,
    )
    return result.returncode == 0 and dest.is_file()


def render_input_panel(prediction_input: SimpleNamespace, route_waypoints: list[dict[str, float]]) -> None:
    frame_path = OUT_DIR / "_example-camera-frame.png"
    have_frame = _extract_camera_frame(frame_path)

    fig, axes = plt.subplots(1, 2, figsize=(8.4, 2.6), gridspec_kw={"width_ratios": [1.1, 1]})
    fig.patch.set_facecolor("white")

    ax_img, ax_text = axes
    if have_frame:
        ax_img.imshow(plt.imread(frame_path), aspect="auto")
    ax_img.set_axis_off()
    ax_img.set_title("camera_images[\"camera_front_wide_120fov\"]", fontsize=9, color="#333")

    ax_text.set_axis_off()
    lines = [
        f"command          = DriveCommand.{prediction_input.command_name}",
        f"speed            = {prediction_input.speed} m/s",
        f"acceleration     = {prediction_input.acceleration} m/s^2",
        f"route_waypoints  = {len(route_waypoints)} points (x, y)",
        f"  first: ({route_waypoints[0]['x']:.1f}, {route_waypoints[0]['y']:.1f})",
        f"  last:  ({route_waypoints[-1]['x']:.1f}, {route_waypoints[-1]['y']:.1f})",
        "ego_pose_history = [<latest pose>]",
        f"scene_id         = \"{prediction_input.scene_id}\"",
    ]
    ax_text.text(
        0, 1, "\n".join(lines),
        family="monospace", fontsize=9.5, va="top", ha="left",
        transform=ax_text.transAxes, color="#1a2321",
    )
    ax_text.set_title("what AlpaBridge reads from AlpaSim", fontsize=9, color="#333")

    fig.suptitle("Before: one AlpaSim Drive() request", fontsize=11, color=ACCENT, fontweight="bold", y=1.02)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    out_path = OUT_DIR / "example-input.png"
    fig.savefig(out_path, dpi=160, facecolor="white", bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    if frame_path.exists():
        frame_path.unlink()
    print(f"wrote {out_path}")


def render_output_panel(trajectory_xy: np.ndarray) -> None:
    fig, ax = plt.subplots(figsize=(4.2, 3.4))
    fig.patch.set_facecolor("white")
    ax.plot(trajectory_xy[:, 1], trajectory_xy[:, 0], color=ACCENT, linewidth=2.5, marker="o", markersize=3)
    ax.scatter([0], [0], color="#92400e", zorder=5)
    ax.annotate(
        "ego", (0, 0), xytext=(6, -12), textcoords="offset points",
        fontsize=8.5, color="#92400e",
    )
    ax.set_xlabel("lateral (m)")
    ax.set_ylabel("longitudinal (m)")
    ax.set_title("After: route_following's trajectory_xy", fontsize=11, color=ACCENT, fontweight="bold")
    ax.grid(True, alpha=0.25)
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    out_path = OUT_DIR / "example-output.png"
    fig.savefig(out_path, dpi=160, facecolor="white", bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"wrote {out_path}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prediction_input, route_waypoints = _build_prediction_input()
    prediction_input.command_name = "RIGHT"

    model = RouteFollowingAlpaSimModel()
    prediction = model.predict(prediction_input)
    trajectory_xy = np.asarray(prediction.trajectory_xy)
    assert np.isfinite(trajectory_xy).all(), "trajectory_xy must be finite"
    assert trajectory_xy.shape[0] > 1, "trajectory_xy must have more than one point"
    print(f"real trajectory_xy from RouteFollowingAlpaSimModel: shape={trajectory_xy.shape}")

    render_input_panel(prediction_input, route_waypoints)
    render_output_panel(trajectory_xy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
