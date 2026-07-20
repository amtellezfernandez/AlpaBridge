#!/usr/bin/env python3
"""Prepare the pinned public AlpaSim video fixture used by the reactive rollout."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ALPASIM_COMMIT = "9177bd0bec547d7516cc77d1864e943780ef7e7a"
SOURCE_URL = (
    "https://media.githubusercontent.com/media/NVlabs/alpasim/"
    f"{ALPASIM_COMMIT}/src/runtime/tests/data/mock_video_model/"
    "clipgt-0b10bce8-61f1-4350-8577-cf3c9493ffc3.usdz"
)
SOURCE_SHA256 = "0ee95b5bc3a69693cd5a3da3a7d430b673f15371f6844f641866302b5deab2f6"
DERIVED_SHA256 = "069fd063a64c82112ec971b585b7eb08d09f9233a4f2ac5e816e19af7185d70d"
DERIVATION_SOURCE_LABEL = "workspace/alpasim-public-scene-video/mock-video.usdz"
ARCHIVE_TIMESTAMP = (2026, 7, 20, 19, 12, 42)

FLAT_MESH = b"""ply
format ascii 1.0
comment WOD2Sim declared flat test surface; not recorded scene geometry
element vertex 4
property float x
property float y
property float z
element face 2
property list uchar int vertex_indices
end_header
-100.0 -100.0 0.0
200.0 -100.0 0.0
200.0 100.0 0.0
-100.0 100.0 0.0
3 0 1 2
3 0 2 3
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def derivation_record() -> bytes:
    payload = {
        "added_files": {
            "mesh.ply": "flat z=0 m rectangle x=[-100,200], y=[-100,100]",
            "mesh_ground.ply": "identical declared flat test surface",
        },
        "claim_boundary": (
            "Synthetic flat physics surface; recorded camera/map/trajectory "
            "payloads are unchanged."
        ),
        "source": DERIVATION_SOURCE_LABEL,
        "source_sha256": SOURCE_SHA256,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def append_declared_surface(output: Path) -> None:
    additions = (
        ("mesh.ply", FLAT_MESH),
        ("mesh_ground.ply", FLAT_MESH),
        ("WOD2SIM_DERIVATION.json", derivation_record()),
    )
    with ZipFile(output, mode="a", compression=ZIP_DEFLATED) as archive:
        for name, content in additions:
            info = ZipInfo(name, ARCHIVE_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)


def prepare_fixture(source: Path, output: Path) -> str:
    source_digest = sha256_file(source)
    if source_digest != SOURCE_SHA256:
        raise ValueError(
            f"source SHA-256 mismatch: expected {SOURCE_SHA256}, got {source_digest}"
        )
    if source.resolve() == output.resolve():
        raise ValueError("source and output paths must differ")

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)
    append_declared_surface(output)
    derived_digest = sha256_file(output)
    if derived_digest != DERIVED_SHA256:
        raise RuntimeError(
            f"derived SHA-256 mismatch: expected {DERIVED_SHA256}, got {derived_digest}"
        )
    return derived_digest


def download_source(source: Path) -> None:
    source.parent.mkdir(parents=True, exist_ok=True)
    temporary = source.with_suffix(source.suffix + ".download")
    with urllib.request.urlopen(SOURCE_URL) as response, temporary.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    temporary.replace(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(DERIVATION_SOURCE_LABEL),
        help="Pinned public AlpaSim USDZ; downloaded when absent.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("workspace/alpasim-public-scene-video-flat/mock-video.usdz"),
    )
    args = parser.parse_args()

    if not args.source.is_file():
        download_source(args.source)
    digest = prepare_fixture(args.source, args.output)
    print(
        json.dumps(
            {
                "alpasim_commit": ALPASIM_COMMIT,
                "derived_sha256": digest,
                "output": str(args.output),
                "source_sha256": SOURCE_SHA256,
                "source_url": SOURCE_URL,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
