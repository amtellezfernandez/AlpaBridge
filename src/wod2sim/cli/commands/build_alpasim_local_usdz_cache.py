from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

from wod2sim.cli.commands.run_alpasim_local_external import (
    SCENE_PRESETS,
    _resolve_alpasim_root,
    _scene_catalog_paths,
    _scene_ids,
)

DEFAULT_HF_REPO = "nvidia/PhysicalAI-Autonomous-Vehicles-NuRec"
DEFAULT_HF_REVISION = "26.02"
MANIFEST_NAME = "wod2sim-local-usdz-cache-manifest.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local AlpaSim USDZ directory from Hugging Face files, using USDZ "
            "metadata as the source of truth. Use the resulting path as "
            "--wizard-arg scenes.local_usdz_dir=/path/to/cache for 26.02 runs."
        )
    )
    parser.add_argument("--scene-preset", choices=tuple(SCENE_PRESETS), required=True)
    parser.add_argument("--alpasim-root", type=Path, default=None)
    parser.add_argument("--target-count", type=int, default=None)
    parser.add_argument("--local-usdz-dir", type=Path, default=None)
    parser.add_argument("--download-dir", type=Path, default=None)
    parser.add_argument("--hf-repo", default=DEFAULT_HF_REPO)
    parser.add_argument("--hf-revision", default=DEFAULT_HF_REVISION)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate an existing local USDZ directory without querying Hugging Face or downloading.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    alpasim_root = _resolve_alpasim_root(args.alpasim_root)
    scene_ids = _scene_ids(args.scene_preset, [])
    if args.target_count is not None:
        if args.target_count <= 0:
            raise SystemExit("--target-count must be positive")
        scene_ids = scene_ids[: args.target_count]

    local_usdz_dir = (
        args.local_usdz_dir.resolve()
        if args.local_usdz_dir is not None
        else alpasim_root / "data" / "nre-artifacts" / f"local-usdzs-{args.scene_preset}"
    )
    download_dir = (
        args.download_dir.resolve()
        if args.download_dir is not None
        else alpasim_root / "data" / "nre-artifacts" / ".hf-downloads" / args.hf_revision
    )

    if args.validate_only:
        report = validate_local_usdz_cache(
            scene_preset=args.scene_preset,
            scene_ids=scene_ids,
            local_usdz_dir=local_usdz_dir,
            hf_revision=args.hf_revision,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["valid"] else 1

    rows = _selected_catalog_rows(
        catalog_paths=_scene_catalog_paths(args.scene_preset, alpasim_root),
        scene_ids=scene_ids,
        available_paths=_hf_available_paths(
            repo_id=args.hf_repo,
            revision=args.hf_revision,
            token=os.getenv("HF_TOKEN"),
        ),
    )
    if len(rows) != len(scene_ids):
        found = {row["scene_id"] for row in rows}
        missing = [scene_id for scene_id in scene_ids if scene_id not in found]
        raise SystemExit(
            f"{len(missing)} preset scene(s) are missing from Hugging Face revision "
            f"{args.hf_revision}: {', '.join(missing[:8])}"
        )

    if args.dry_run:
        print(
            json.dumps(
                {
                    "schema": "wod2sim_local_usdz_cache_plan_v1",
                    "scene_preset": args.scene_preset,
                    "scene_count": len(rows),
                    "local_usdz_dir": str(local_usdz_dir),
                    "download_dir": str(download_dir),
                    "hf_repo": args.hf_repo,
                    "hf_revision": args.hf_revision,
                    "scene_ids": [row["scene_id"] for row in rows],
                },
                indent=2,
            )
        )
        return 0

    local_usdz_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_local_usdz_cache(
        rows=rows,
        local_usdz_dir=local_usdz_dir,
        download_dir=download_dir,
        hf_repo=args.hf_repo,
        hf_revision=args.hf_revision,
        token=os.getenv("HF_TOKEN"),
        workers=max(1, args.workers),
    )
    manifest.update(
        {
            "source_preset": args.scene_preset,
            "source_catalogs": [str(path) for path in _scene_catalog_paths(args.scene_preset, alpasim_root)],
        }
    )
    manifest_path = local_usdz_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {manifest_path}")
    print(f"local_usdz_dir={local_usdz_dir}")
    print(f"scene_count={manifest['scene_count']}")
    if manifest["errors"]:
        raise SystemExit(1)
    return 0


def validate_local_usdz_cache(
    *,
    scene_preset: str,
    scene_ids: list[str],
    local_usdz_dir: Path,
    hf_revision: str,
) -> dict[str, Any]:
    existing = _existing_by_scene(local_usdz_dir) if local_usdz_dir.is_dir() else {}
    missing_scene_ids = [scene_id for scene_id in scene_ids if scene_id not in existing]
    extra_scene_ids = sorted(scene_id for scene_id in existing if scene_id not in set(scene_ids))
    invalid_revisions = [
        scene_id
        for scene_id in scene_ids
        if scene_id in existing
        and str(existing[scene_id].get("version_string", "")).strip()
        and not _metadata_version_matches(str(existing[scene_id]["version_string"]), hf_revision)
    ]
    duplicate_uuids = _duplicate_values(
        [
            str(existing[scene_id].get("uuid", ""))
            for scene_id in scene_ids
            if scene_id in existing
        ]
    )
    present_scene_count = len([scene_id for scene_id in scene_ids if scene_id in existing])
    valid = (
        local_usdz_dir.is_dir()
        and present_scene_count == len(scene_ids)
        and not missing_scene_ids
        and not invalid_revisions
        and not duplicate_uuids
    )
    return {
        "schema": "wod2sim_local_usdz_cache_validation_v1",
        "valid": valid,
        "scene_preset": scene_preset,
        "hf_revision": hf_revision,
        "local_usdz_dir": str(local_usdz_dir),
        "expected_scene_count": len(scene_ids),
        "present_scene_count": present_scene_count,
        "missing_scene_ids": missing_scene_ids,
        "extra_scene_ids": extra_scene_ids,
        "invalid_revision_scene_ids": invalid_revisions,
        "duplicate_uuids": duplicate_uuids,
        "scenes": [
            {"scene_id": scene_id, **existing[scene_id]}
            for scene_id in scene_ids
            if scene_id in existing
        ],
    }


def _hf_available_paths(*, repo_id: str, revision: str, token: str | None) -> set[str]:
    try:
        from huggingface_hub import HfApi
    except ImportError as exc:  # pragma: no cover - exercised by installed users.
        raise SystemExit(
            "huggingface_hub is required for this command. Install with "
            "`pip install 'wod2sim[alpasim]'` or run inside the AlpaSim virtualenv."
        ) from exc

    api = HfApi(token=token)
    return {
        path
        for path in api.list_repo_files(repo_id, repo_type="dataset", revision=revision)
        if path.endswith(".usdz")
    }


def _selected_catalog_rows(
    *,
    catalog_paths: list[Path],
    scene_ids: list[str],
    available_paths: set[str],
) -> list[dict[str, str]]:
    rows_by_scene: dict[str, dict[str, str]] = {}
    for catalog_path in catalog_paths:
        with catalog_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                scene_id = str(row.get("scene_id", "")).strip()
                path = str(row.get("path", "")).strip()
                if scene_id and path in available_paths:
                    rows_by_scene[scene_id] = row
    return [rows_by_scene[scene_id] for scene_id in scene_ids if scene_id in rows_by_scene]


def build_local_usdz_cache(
    *,
    rows: list[dict[str, str]],
    local_usdz_dir: Path,
    download_dir: Path,
    hf_repo: str,
    hf_revision: str,
    token: str | None,
    workers: int,
) -> dict[str, Any]:
    existing = _existing_by_scene(local_usdz_dir)
    results: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _fetch_one,
                row=row,
                existing=existing,
                local_usdz_dir=local_usdz_dir,
                download_dir=download_dir,
                hf_repo=hf_repo,
                hf_revision=hf_revision,
                token=token,
            ): row["scene_id"]
            for row in rows
        }
        for index, future in enumerate(as_completed(futures), start=1):
            scene_id = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - convert to manifest row for batch visibility.
                errors.append({"scene_id": scene_id, "error": str(exc)})
                print(f"[{index}/{len(rows)}] FAILED {scene_id}: {exc}", flush=True)
                continue
            results.append(result)
            print(
                f"[{index}/{len(rows)}] {result['status']} {scene_id} "
                f"uuid={result['uuid']} version={result['version_string']}",
                flush=True,
            )

    order = {row["scene_id"]: index for index, row in enumerate(rows)}
    results.sort(key=lambda item: order[item["scene_id"]])
    return {
        "schema": "wod2sim_local_usdz_cache_manifest_v1",
        "hf_repo": hf_repo,
        "hf_revision": hf_revision,
        "local_usdz_dir": str(local_usdz_dir),
        "download_dir": str(download_dir),
        "scene_count": len(results),
        "errors": errors,
        "scenes": results,
    }


def _fetch_one(
    *,
    row: dict[str, str],
    existing: dict[str, dict[str, str]],
    local_usdz_dir: Path,
    download_dir: Path,
    hf_repo: str,
    hf_revision: str,
    token: str | None,
) -> dict[str, str]:
    scene_id = row["scene_id"]
    if scene_id in existing:
        return {"scene_id": scene_id, "status": "cached", **existing[scene_id]}

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:  # pragma: no cover - exercised by installed users.
        raise RuntimeError("huggingface_hub is required for downloading scene assets") from exc

    downloaded = Path(
        hf_hub_download(
            repo_id=hf_repo,
            repo_type="dataset",
            filename=row["path"],
            revision=str(row.get("hf_revision") or hf_revision),
            local_dir=download_dir,
            token=token,
        )
    )
    metadata = _metadata_for(downloaded)
    actual_scene_id = str(metadata.get("scene_id"))
    if actual_scene_id != scene_id:
        raise RuntimeError(f"metadata scene_id {actual_scene_id!r} does not match {scene_id!r}")
    uuid = str(metadata["uuid"])
    final_path = local_usdz_dir / f"{uuid}.usdz"
    status = _link_or_copy(downloaded, final_path)
    return {
        "scene_id": scene_id,
        "status": status,
        "path": str(final_path),
        "uuid": uuid,
        "version_string": str(metadata.get("version_string")),
        "catalog_uuid": str(row.get("uuid", "")),
        "catalog_version_string": str(row.get("nre_version_string", "")),
    }


def _existing_by_scene(local_usdz_dir: Path) -> dict[str, dict[str, str]]:
    existing: dict[str, dict[str, str]] = {}
    for path in local_usdz_dir.glob("*.usdz"):
        metadata = _metadata_for(path)
        scene_id = str(metadata.get("scene_id"))
        existing[scene_id] = {
            "path": str(path),
            "uuid": str(metadata.get("uuid")),
            "version_string": str(metadata.get("version_string")),
        }
    return existing


def _metadata_version_matches(version_string: str, hf_revision: str) -> bool:
    expected = _version_numbers(hf_revision)
    actual = _version_numbers(version_string)
    return not expected or actual[: len(expected)] == expected


def _version_numbers(value: str) -> list[int]:
    return [int(part) for part in re.findall(r"\d+", value)]


def _duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if not value:
            continue
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _metadata_for(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        with archive.open("metadata.yaml") as handle:
            metadata = yaml.safe_load(handle)
    if not isinstance(metadata, dict):
        raise RuntimeError(f"metadata.yaml in {path} is not a mapping")
    return metadata


def _link_or_copy(src: Path, dst: Path) -> str:
    if dst.exists():
        return "exists"
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


if __name__ == "__main__":
    raise SystemExit(main())
