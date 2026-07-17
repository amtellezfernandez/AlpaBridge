#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
from pathlib import Path

from wod2sim.cli.commands.run_alpasim_local_external import (
    SCENE_PRESETS,
    _preflight_alpasim_base_image,
    _preflight_alpasim_local_environment,
    _preflight_docker_access,
    _preflight_nvidia_container_runtime,
    _preflight_platform_compatibility,
    _preflight_scene_artifacts,
    _resolve_alpasim_root,
    _scene_catalog_paths,
    _scene_ids,
    _validate_alpasim_checkout,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate that this repo is ready to launch local AlpaSim runs."
    )
    parser.add_argument(
        "--alpasim-root",
        type=Path,
        default=None,
        help="Path to the nested AlpaSim checkout. Defaults to $ALPASIM_ROOT or ./workspace/alpasim.",
    )
    parser.add_argument(
        "--scene-preset",
        choices=tuple(SCENE_PRESETS),
        default="fresh_3scene",
        help="Scene preset whose artifacts should be checked.",
    )
    parser.add_argument(
        "--scene-id",
        action="append",
        default=[],
        help="Explicit scene id override. If set, replaces the preset scene list.",
    )
    parser.add_argument(
        "--local-usdz-dir",
        type=Path,
        default=None,
        help=(
            "Explicit local USDZ cache directory. Relative paths are resolved from the "
            "current working directory when present, otherwise from --alpasim-root."
        ),
    )
    parser.add_argument(
        "--skip-image",
        action="store_true",
        help="Skip checking for the local alpasim-base image.",
    )
    parser.add_argument(
        "--skip-local-env",
        action="store_true",
        help="Skip checking the local AlpaSim .venv and alpasim_wizard executable.",
    )
    parser.add_argument(
        "--skip-scene-artifacts",
        action="store_true",
        help="Skip checking gated/local USDZ scene artifacts.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    alpasim_root = _resolve_alpasim_root(args.alpasim_root)
    scene_ids = _scene_ids(args.scene_preset, args.scene_id)
    scene_catalog_paths = _scene_catalog_paths(args.scene_preset, alpasim_root)
    local_usdz_dir = _resolve_local_usdz_dir(args.local_usdz_dir, alpasim_root)

    _validate_alpasim_checkout(alpasim_root)
    if not args.skip_local_env:
        _preflight_alpasim_local_environment(alpasim_root)
    _preflight_docker_access()
    _preflight_platform_compatibility()
    if not args.skip_image:
        _preflight_alpasim_base_image()
    _preflight_nvidia_container_runtime()
    if not args.skip_scene_artifacts:
        _preflight_scene_artifacts(
            alpasim_root=alpasim_root,
            scene_ids=scene_ids,
            scene_catalog_paths=scene_catalog_paths,
            local_usdz_dir=local_usdz_dir,
        )

    token_state = "present" if os.environ.get("HF_TOKEN") else "not set"
    print("AlpaSim readiness: OK")
    print(f"  ALPASIM_ROOT: {alpasim_root}")
    print(f"  scene count: {len(scene_ids)}")
    print(f"  scene preset: {args.scene_preset}")
    print(f"  scene catalogs: {', '.join(str(path) for path in scene_catalog_paths)}")
    print(f"  local USDZ dir: {local_usdz_dir if local_usdz_dir is not None else 'default'}")
    print(f"  HF_TOKEN: {token_state}")
    print("  docker: accessible")
    print("  gpu runtime: accessible")
    print(f"  image: {'skipped' if args.skip_image else 'alpasim-base:0.66.0'}")
    print(f"  local AlpaSim env: {'skipped' if args.skip_local_env else 'checked'}")
    print(f"  scene artifacts: {'skipped' if args.skip_scene_artifacts else 'checked'}")


def _resolve_local_usdz_dir(value: Path | None, alpasim_root: Path) -> Path | None:
    if value is None:
        return None
    candidate = value.expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    cwd_candidate = candidate.resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    return (alpasim_root / candidate).resolve()


if __name__ == "__main__":
    main()
