#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wod2sim.cli.commands import check_alpasim_readiness as _cmd

SCENE_PRESETS = _cmd.SCENE_PRESETS
_parse_args = _cmd._parse_args
_preflight_alpasim_base_image = _cmd._preflight_alpasim_base_image
_preflight_docker_access = _cmd._preflight_docker_access
_preflight_alpasim_local_environment = _cmd._preflight_alpasim_local_environment
_preflight_nvidia_container_runtime = _cmd._preflight_nvidia_container_runtime
_preflight_platform_compatibility = _cmd._preflight_platform_compatibility
_preflight_scene_artifacts = _cmd._preflight_scene_artifacts
_resolve_alpasim_root = _cmd._resolve_alpasim_root
_scene_catalog_paths = _cmd._scene_catalog_paths
_scene_ids = _cmd._scene_ids
_validate_alpasim_checkout = _cmd._validate_alpasim_checkout


def main() -> None:
    args = _parse_args()
    alpasim_root = _resolve_alpasim_root(args.alpasim_root)
    scene_ids = _scene_ids(args.scene_preset, args.scene_id)
    scene_catalog_paths = _scene_catalog_paths(args.scene_preset, alpasim_root)

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
        )

    token_state = "present" if _cmd.os.environ.get("HF_TOKEN") else "not set"
    print("AlpaSim readiness: OK")
    print(f"  ALPASIM_ROOT: {alpasim_root}")
    print(f"  scene count: {len(scene_ids)}")
    print(f"  scene preset: {args.scene_preset}")
    print(f"  scene catalogs: {', '.join(str(path) for path in scene_catalog_paths)}")
    print(f"  HF_TOKEN: {token_state}")
    print("  docker: accessible")
    print("  gpu runtime: accessible")
    print(f"  image: {'skipped' if args.skip_image else 'alpasim-base:0.66.0'}")
    print(f"  local AlpaSim env: {'skipped' if args.skip_local_env else 'checked'}")
    print(f"  scene artifacts: {'skipped' if args.skip_scene_artifacts else 'checked'}")


if __name__ == "__main__":
    main()
