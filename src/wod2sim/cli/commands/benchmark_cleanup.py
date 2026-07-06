from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

CLEANUP_SCHEMA = "wod2sim_benchmark_cleanup_report_v1"
DEFAULT_ALPASIM_ROOT = Path("workspace/alpasim")
PRUNED_BYTECODE_DIRS = {".git", ".venv", "node_modules"}


@dataclass(frozen=True)
class CleanupTarget:
    target_id: str
    path: Path
    category: str
    include_by_default: bool
    requires_option: str | None
    description: str


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Report or remove ignored local benchmark artifacts. The command is dry-run by "
            "default, never calls Docker or downloads assets, and refuses to remove paths "
            "that contain tracked files."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--alpasim-root", type=Path, default=DEFAULT_ALPASIM_ROOT)
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Remove included targets. Without this flag the command only reports.",
    )
    parser.add_argument(
        "--include-scale-caches",
        action="store_true",
        help=(
            "Allow removal of generated 50/100 local USDZ cache directories. This is "
            "opt-in because valid scale caches are prerequisites for the benchmark claim."
        ),
    )
    parser.add_argument(
        "--include-gated-assets",
        action="store_true",
        help=(
            "Allow removal of the source all-usdzs directory. This may contain gated "
            "private assets and is never removed by default."
        ),
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    report = build_cleanup_report(
        repo_root=args.repo_root,
        alpasim_root=args.alpasim_root,
        created_at=args.created_at,
        apply=args.apply,
        include_scale_caches=args.include_scale_caches,
        include_gated_assets=args.include_gated_assets,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human_summary(report)
    return 0 if report["valid"] else 1


def build_cleanup_report(
    *,
    repo_root: Path = Path.cwd(),
    alpasim_root: Path = DEFAULT_ALPASIM_ROOT,
    created_at: str | None = None,
    apply: bool = False,
    include_scale_caches: bool = False,
    include_gated_assets: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    resolved_alpasim_root = _resolve_path(repo_root, alpasim_root)
    options = {
        "include_scale_caches": include_scale_caches,
        "include_gated_assets": include_gated_assets,
    }
    targets = _cleanup_targets(repo_root=repo_root, alpasim_root=resolved_alpasim_root)
    rows = [
        _target_report(target, repo_root=repo_root, apply=apply, options=options)
        for target in targets
    ]
    return {
        "schema": CLEANUP_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "generator": {
            "command": "wod2sim-benchmark-cleanup",
            "dry_run_default": True,
            "no_docker_or_download_probes": True,
            "tracked_file_guard": True,
        },
        "repo_root": _display_path(repo_root, repo_root=repo_root),
        "alpasim_root": _display_path(resolved_alpasim_root, repo_root=repo_root),
        "apply": apply,
        "options": options,
        "valid": not any(row["action"] == "error" for row in rows),
        "target_count": len(rows),
        "included_target_count": sum(1 for row in rows if row["included"]),
        "existing_included_target_count": sum(
            1 for row in rows if row["included"] and row["exists"]
        ),
        "reclaimable_bytes": sum(
            row["size_bytes"]
            for row in rows
            if row["included"] and row["exists"] and row["safe_to_remove"]
        ),
        "removed_bytes": sum(row["size_bytes"] for row in rows if row["action"] == "removed"),
        "targets": rows,
    }


def _cleanup_targets(*, repo_root: Path, alpasim_root: Path) -> list[CleanupTarget]:
    targets = [
        CleanupTarget(
            "benchmark_runs",
            repo_root / "runs",
            "runtime_outputs",
            True,
            None,
            "Local benchmark run directories, rollout logs, videos, and telemetry.",
        ),
        CleanupTarget(
            "uv_cache",
            repo_root / ".uv-cache",
            "dependency_cache",
            True,
            None,
            "Project-local uv package cache.",
        ),
        CleanupTarget("pytest_cache", repo_root / ".pytest_cache", "tool_cache", True, None, ""),
        CleanupTarget("ruff_cache", repo_root / ".ruff_cache", "tool_cache", True, None, ""),
        CleanupTarget("mypy_cache", repo_root / ".mypy_cache", "tool_cache", True, None, ""),
        CleanupTarget("build_dir", repo_root / "build", "build_output", True, None, ""),
        CleanupTarget("dist_dir", repo_root / "dist", "build_output", True, None, ""),
        CleanupTarget(
            "alpasim_outputs",
            alpasim_root / "outputs",
            "runtime_outputs",
            True,
            None,
            "Local AlpaSim output directories.",
        ),
        CleanupTarget(
            "scale_cache_50",
            alpasim_root / "data" / "nre-artifacts" / "local-2602-usdzs-50",
            "scale_cache",
            False,
            "include_scale_caches",
            "Generated 50-scene local USDZ cache.",
        ),
        CleanupTarget(
            "scale_cache_100",
            alpasim_root / "data" / "nre-artifacts" / "local-2602-usdzs-100",
            "scale_cache",
            False,
            "include_scale_caches",
            "Generated 100-scene local USDZ cache.",
        ),
        CleanupTarget(
            "source_all_usdzs",
            alpasim_root / "data" / "nre-artifacts" / "all-usdzs",
            "gated_source_cache",
            False,
            "include_gated_assets",
            "Source all-usdzs directory, which may contain gated private assets.",
        ),
    ]
    targets.extend(_bytecode_targets(repo_root))
    return sorted(targets, key=lambda target: (target.category, str(target.path), target.target_id))


def _bytecode_targets(repo_root: Path) -> list[CleanupTarget]:
    targets: list[CleanupTarget] = []
    for root, dirs, _files in os.walk(repo_root):
        root_path = Path(root)
        dirs[:] = [
            dirname
            for dirname in dirs
            if dirname not in PRUNED_BYTECODE_DIRS
            and not _is_within(root_path / dirname, repo_root / "workspace" / "alpasim" / ".venv")
        ]
        if root_path.name == "__pycache__":
            targets.append(
                CleanupTarget(
                    f"python_bytecode:{_display_path(root_path, repo_root=repo_root)}",
                    root_path,
                    "python_bytecode",
                    True,
                    None,
                    "Python bytecode cache.",
                )
            )
            dirs[:] = []
    return targets


def _target_report(
    target: CleanupTarget,
    *,
    repo_root: Path,
    apply: bool,
    options: dict[str, bool],
) -> dict[str, Any]:
    path = target.path.resolve()
    exists = path.exists() or path.is_symlink()
    included = target.include_by_default or bool(
        target.requires_option and options[target.requires_option]
    )
    within_repo = _is_within(path, repo_root)
    tracked_files = (
        _tracked_files_under(path, repo_root=repo_root) if exists and within_repo else []
    )
    safe_to_remove = included and exists and within_repo and not tracked_files
    action = _target_action(
        exists=exists,
        included=included,
        within_repo=within_repo,
        tracked_files=tracked_files,
        safe_to_remove=safe_to_remove,
        apply=apply,
    )
    error = None
    size_bytes = _path_size(path) if exists else 0
    if action == "remove":
        try:
            _remove_path(path)
            action = "removed"
        except OSError as exc:
            action = "error"
            error = str(exc)

    row = {
        "id": target.target_id,
        "path": _display_path(path, repo_root=repo_root),
        "category": target.category,
        "description": target.description,
        "exists": exists,
        "included": included,
        "include_by_default": target.include_by_default,
        "requires_option": target.requires_option,
        "within_repo": within_repo,
        "tracked_file_count": len(tracked_files),
        "tracked_files_sample": tracked_files[:10],
        "safe_to_remove": safe_to_remove,
        "size_bytes": size_bytes,
        "action": action,
    }
    if error is not None:
        row["error"] = error
    return row


def _target_action(
    *,
    exists: bool,
    included: bool,
    within_repo: bool,
    tracked_files: list[str],
    safe_to_remove: bool,
    apply: bool,
) -> str:
    if not exists:
        return "missing"
    if not included:
        return "skipped_not_included"
    if not within_repo:
        return "skipped_outside_repo"
    if tracked_files:
        return "skipped_tracked_files"
    if not safe_to_remove:
        return "skipped"
    return "remove" if apply else "would_remove"


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    shutil.rmtree(path)


def _tracked_files_under(path: Path, *, repo_root: Path) -> list[str]:
    tracked: set[str] = set()
    for git_root in _git_roots_for_path(path, repo_root=repo_root):
        tracked.update(_tracked_files_under_git_root(path, git_root=git_root, repo_root=repo_root))
    return sorted(tracked)


def _git_roots_for_path(path: Path, *, repo_root: Path) -> list[Path]:
    roots: list[Path] = []
    if (repo_root / ".git").exists():
        roots.append(repo_root)
    for ancestor in (path, *path.parents):
        if ancestor == repo_root or not _is_within(ancestor, repo_root):
            continue
        if (ancestor / ".git").exists():
            roots.append(ancestor)
    unique: list[Path] = []
    for root in roots:
        if root not in unique and _is_within(path, root):
            unique.append(root)
    return unique


def _tracked_files_under_git_root(path: Path, *, git_root: Path, repo_root: Path) -> list[str]:
    relative = _display_path(path, repo_root=git_root)
    try:
        completed = subprocess.run(
            ["git", "-C", str(git_root), "ls-files", "-z", "--", relative],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=False,
        )
    except OSError:
        return []
    if completed.returncode != 0 or not completed.stdout:
        return []
    return [
        _display_path(git_root / item.decode("utf-8"), repo_root=repo_root)
        for item in completed.stdout.split(b"\0")
        if item
    ]


def _path_size(path: Path) -> int:
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    total = path.lstat().st_size
    for item in path.rglob("*"):
        try:
            total += item.lstat().st_size
        except OSError:
            continue
    return total


def _resolve_path(repo_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (repo_root / path).resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _display_path(path: Path, *, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def _print_human_summary(report: dict[str, Any]) -> None:
    mode = "apply" if report["apply"] else "dry-run"
    print(f"{report['schema']} ({mode})")
    print(f"- included targets: {report['included_target_count']}/{report['target_count']}")
    print(f"- reclaimable bytes: {report['reclaimable_bytes']}")
    print(f"- removed bytes: {report['removed_bytes']}")
    for target in report["targets"]:
        if target["action"] not in {"missing", "skipped_not_included"}:
            print(f"- {target['action']}: {target['path']} ({target['size_bytes']} bytes)")


if __name__ == "__main__":
    raise SystemExit(main())
