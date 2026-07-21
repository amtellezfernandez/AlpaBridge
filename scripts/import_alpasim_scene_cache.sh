#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALPASIM_ROOT="${ALPASIM_ROOT:-$ROOT/workspace/alpasim}"
SOURCE_ROOT=""
SOURCE_ALL_USDZS=""
SOURCE_SCENE_CATALOG=""
TRANSFER_MODE="hardlink"

usage() {
  cat <<'EOF'
Import a local AlpaSim scene cache into this checkout without symlink indirection.

Usage:
  ./scripts/import_alpasim_scene_cache.sh --source-root /path/to/other/alpasim

Options:
  --source-root PATH           Existing AlpaSim checkout or cache root.
  --source-all-usdzs PATH      Explicit all-usdzs directory.
  --source-scene-catalog PATH  Explicit sim_scenes.csv path.
  --alpasim-root PATH          Target AlpaSim checkout. Defaults to ./workspace/alpasim.
  --copy                       Copy files instead of hardlinking them.
  --help                       Show this message.

Notes:
  - By default the script hardlinks USDZ files so the target checkout is self-contained
    inside the mounted tree used by Docker, without duplicating data when source and
    target are on the same filesystem.
  - If hardlinking is not possible, the script falls back to copying per file.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-root)
      SOURCE_ROOT="${2:?missing value for --source-root}"
      shift 2
      ;;
    --source-all-usdzs)
      SOURCE_ALL_USDZS="${2:?missing value for --source-all-usdzs}"
      shift 2
      ;;
    --source-scene-catalog)
      SOURCE_SCENE_CATALOG="${2:?missing value for --source-scene-catalog}"
      shift 2
      ;;
    --alpasim-root)
      ALPASIM_ROOT="${2:?missing value for --alpasim-root}"
      shift 2
      ;;
    --copy)
      TRANSFER_MODE="copy"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -n "$SOURCE_ROOT" ]]; then
  SOURCE_ROOT="$(realpath "$SOURCE_ROOT")"
  if [[ -z "$SOURCE_ALL_USDZS" ]]; then
    SOURCE_ALL_USDZS="$SOURCE_ROOT/data/nre-artifacts/all-usdzs"
  fi
  if [[ -z "$SOURCE_SCENE_CATALOG" && -f "$SOURCE_ROOT/data/scenes/sim_scenes.csv" ]]; then
    SOURCE_SCENE_CATALOG="$SOURCE_ROOT/data/scenes/sim_scenes.csv"
  fi
fi

if [[ -z "$SOURCE_ALL_USDZS" ]]; then
  echo "Provide --source-root or --source-all-usdzs." >&2
  exit 1
fi

SOURCE_ALL_USDZS="$(realpath "$SOURCE_ALL_USDZS")"
if [[ ! -d "$SOURCE_ALL_USDZS" ]]; then
  echo "Source USDZ directory does not exist: $SOURCE_ALL_USDZS" >&2
  exit 1
fi

if [[ -n "$SOURCE_SCENE_CATALOG" ]]; then
  SOURCE_SCENE_CATALOG="$(realpath "$SOURCE_SCENE_CATALOG")"
  if [[ ! -f "$SOURCE_SCENE_CATALOG" ]]; then
    echo "Source scene catalog does not exist: $SOURCE_SCENE_CATALOG" >&2
    exit 1
  fi
fi

ALPASIM_ROOT="$(realpath -m "$ALPASIM_ROOT")"
TARGET_ALL_USDZS="$ALPASIM_ROOT/data/nre-artifacts/all-usdzs"
TARGET_SCENE_CATALOG="$ALPASIM_ROOT/data/scenes/sim_scenes.csv"

mkdir -p "$TARGET_ALL_USDZS" "$(dirname "$TARGET_SCENE_CATALOG")"

if [[ -n "$SOURCE_SCENE_CATALOG" ]]; then
  cp -f "$SOURCE_SCENE_CATALOG" "$TARGET_SCENE_CATALOG"
fi

shopt -s nullglob
source_files=("$SOURCE_ALL_USDZS"/*.usdz)
shopt -u nullglob

if [[ ${#source_files[@]} -eq 0 ]]; then
  echo "No USDZ files found under $SOURCE_ALL_USDZS" >&2
  exit 1
fi

imported=0
linked=0
copied=0
skipped=0

for source_file in "${source_files[@]}"; do
  target_file="$TARGET_ALL_USDZS/$(basename "$source_file")"
  if [[ -e "$target_file" ]]; then
    skipped=$((skipped + 1))
    continue
  fi

  if [[ "$TRANSFER_MODE" == "hardlink" ]]; then
    if ln "$source_file" "$target_file" 2>/dev/null; then
      linked=$((linked + 1))
      imported=$((imported + 1))
      continue
    fi
  fi

  cp -p "$source_file" "$target_file"
  copied=$((copied + 1))
  imported=$((imported + 1))
done

echo "Imported scene cache into $ALPASIM_ROOT"
echo "  source all-usdzs: $SOURCE_ALL_USDZS"
if [[ -n "$SOURCE_SCENE_CATALOG" ]]; then
  echo "  source sim_scenes.csv: $SOURCE_SCENE_CATALOG"
fi
echo "  imported: $imported"
echo "  hardlinked: $linked"
echo "  copied: $copied"
echo "  skipped existing: $skipped"
