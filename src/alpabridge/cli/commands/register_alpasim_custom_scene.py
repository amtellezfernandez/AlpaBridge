"""Register a custom USDZ scene in an AlpaSim scene catalog CSV.

``alpabridge-build-local-cache --source-usdz-dir`` already links an
arbitrary USDZ file into a local cache using nothing but that file's own
embedded metadata - no catalog involved. But AlpaSim's own scene catalog
CSV (``data/scenes/sim_scenes*.csv`` in the connected checkout) is a
separate, harder gate: ``alpabridge-ready``/``alpabridge-launch`` refuse to
run a scene whose ``scene_id`` isn't a row in that catalog, before ever
looking at the USDZ file itself.

This command closes that one manual gap - it reads the scene's own
metadata and appends (or replaces, with ``--force``) the matching catalog
row - so a scene you already have a complete, valid USDZ for doesn't
require hand-editing a CSV. It does not, and cannot, fix an incomplete
USDZ (missing mesh, map, or ground-truth data) - that's a property of the
file itself, not of the catalog.

Once registered, ``alpabridge-build-local-cache --source-usdz-dir`` needs
``--hf-revision ""`` for this scene: without it, that command compares the
scene's own (arbitrary) ``version_string`` against a real Hugging Face
revision number and rejects it as a false version mismatch. An empty
``--hf-revision`` disables that comparison entirely - this command's own
printed "Next" step includes it.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from alpabridge.cli.commands.build_alpasim_local_usdz_cache import _metadata_for
from alpabridge.cli.commands.run_alpasim_local_external import (
    SCENE_PRESETS,
    _resolve_alpasim_root,
    _scene_catalog_paths,
)

DEFAULT_ARTIFACT_REPOSITORY = "local"
FALLBACK_FIELDNAMES = ["scene_id", "uuid", "path", "artifact_repository", "nre_version_string"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Append (or replace) a row in an AlpaSim scene catalog CSV for a USDZ file you "
            "already have, using that file's own embedded scene_id/uuid metadata. Does not "
            "download, validate, or repair the USDZ itself."
        )
    )
    parser.add_argument("--usdz", type=Path, required=True, help="Path to the USDZ scene file.")
    parser.add_argument("--alpasim-root", type=Path, default=None)
    parser.add_argument(
        "--scene-preset",
        choices=tuple(SCENE_PRESETS),
        default=None,
        help="Append to the catalog CSV(s) this preset points at. Mutually exclusive with --catalog-csv.",
    )
    parser.add_argument(
        "--catalog-csv",
        type=Path,
        default=None,
        help=(
            "Explicit catalog CSV to append to, instead of deriving one from --scene-preset. "
            "Created with a minimal header if it doesn't exist yet."
        ),
    )
    parser.add_argument(
        "--artifact-repository",
        default=DEFAULT_ARTIFACT_REPOSITORY,
        help=(
            f"Value for the row's artifact_repository column (default: {DEFAULT_ARTIFACT_REPOSITORY!r}). "
            "Keep this something other than 'huggingface' - that value tells AlpaBridge's own "
            "preflight checks to expect an HF-downloaded artifact instead of a local one."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Update an existing row for this scene_id instead of failing. Only the "
            "uuid/artifact_repository/nre_version_string fields change; any other "
            "existing column value for this scene_id is preserved."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the row that would be written without changing the catalog file.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.scene_preset and args.catalog_csv:
        raise SystemExit("Pass only one of --scene-preset or --catalog-csv, not both.")
    if not args.scene_preset and not args.catalog_csv:
        raise SystemExit("Pass --scene-preset or --catalog-csv to pick a target catalog file.")
    if args.artifact_repository.strip().lower() == "huggingface":
        raise SystemExit(
            "--artifact-repository must not be 'huggingface' for a custom scene - that value "
            "tells AlpaBridge's preflight checks this scene should already be an HF download."
        )

    if not args.usdz.is_file():
        raise SystemExit(f"USDZ file not found: {args.usdz}")
    metadata = _metadata_for(args.usdz)
    scene_id = str(metadata.get("scene_id", "")).strip()
    uuid = str(metadata.get("uuid", "")).strip()
    version_string = str(metadata.get("version_string", "")).strip()
    if not scene_id or not uuid:
        raise SystemExit(
            f"{args.usdz} is missing required metadata.yaml field(s): "
            f"{'scene_id ' if not scene_id else ''}{'uuid' if not uuid else ''}".strip()
        )

    if args.catalog_csv is not None:
        catalog_path = args.catalog_csv.resolve()
    else:
        alpasim_root = _resolve_alpasim_root(args.alpasim_root)
        catalog_paths = _scene_catalog_paths(args.scene_preset, alpasim_root)
        if len(catalog_paths) != 1:
            raise SystemExit(
                f"--scene-preset {args.scene_preset!r} points at {len(catalog_paths)} catalog "
                "files; pass --catalog-csv to pick one explicitly."
            )
        catalog_path = catalog_paths[0]

    fieldnames, rows = _read_catalog(catalog_path)
    existing_index = next((i for i, row in enumerate(rows) if row.get("scene_id") == scene_id), None)
    if existing_index is not None and not args.force:
        raise SystemExit(
            f"scene_id {scene_id!r} already has a row in {catalog_path} - pass --force to replace it."
        )

    # Start from the existing row when replacing, not a blank one - --force
    # updates this scene's fields, it doesn't drop unrelated columns
    # (path, hf_revision, or any project-specific extra column) that were
    # already set for it.
    base_row = dict(rows[existing_index]) if existing_index is not None else {}
    new_row = {name: base_row.get(name, "") for name in fieldnames}
    new_row.update(
        {
            "scene_id": scene_id,
            "uuid": uuid,
            "artifact_repository": args.artifact_repository,
            "nre_version_string": version_string,
        }
    )
    for column in ("scene_id", "uuid", "artifact_repository", "nre_version_string"):
        if column not in fieldnames:
            fieldnames.append(column)

    if args.dry_run:
        print(f"catalog_csv={catalog_path}")
        print(f"scene_id={scene_id}")
        print(f"uuid={uuid}")
        print(f"row={new_row}")
        print("action=" + ("replace" if existing_index is not None else "append"))
        return 0

    if existing_index is not None:
        rows[existing_index] = new_row
    else:
        rows.append(new_row)
    _write_catalog(catalog_path, fieldnames, rows)

    print(f"wrote scene_id={scene_id} to {catalog_path}")
    print(
        "Next: uv run alpabridge-build-local-cache --source-usdz-dir "
        f"{args.usdz.parent} --scene-id {scene_id} "
        f"--scene-preset {args.scene_preset or '<a preset using this catalog>'} "
        '--hf-revision ""'
    )
    print(
        "(--hf-revision \"\" is required here, not optional: without it, "
        "build-local-cache compares this scene's own version_string against "
        "a real HF revision number and rejects it as a false 'mismatch'.)"
    )
    return 0


def _read_catalog(catalog_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not catalog_path.is_file():
        return list(FALLBACK_FIELDNAMES), []
    with catalog_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or FALLBACK_FIELDNAMES)
        rows = [dict(row) for row in reader]
    return fieldnames, rows


def _write_catalog(catalog_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with catalog_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


if __name__ == "__main__":
    raise SystemExit(main())
