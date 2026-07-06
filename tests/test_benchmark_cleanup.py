from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def test_cleanup_dry_run_reports_default_targets_without_deleting() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_cleanup")
    with TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        runs_file = repo_root / "runs" / "batch" / "output.bin"
        uv_file = repo_root / ".uv-cache" / "archive" / "pkg.bin"
        source_file = (
            repo_root
            / "workspace"
            / "alpasim"
            / "data"
            / "nre-artifacts"
            / "all-usdzs"
            / "private.usdz"
        )
        for path in (runs_file, uv_file, source_file):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 8)

        report = module.build_cleanup_report(repo_root=repo_root, created_at="2026-07-06")
        targets = {row["id"]: row for row in report["targets"]}

        assert report["schema"] == "wod2sim_benchmark_cleanup_report_v1"
        assert report["created_at"] == "2026-07-06"
        assert report["apply"] is False
        assert report["valid"] is True
        assert targets["benchmark_runs"]["action"] == "would_remove"
        assert targets["uv_cache"]["action"] == "would_remove"
        assert targets["source_all_usdzs"]["action"] == "skipped_not_included"
        assert runs_file.exists()
        assert uv_file.exists()
        assert source_file.exists()


def test_cleanup_apply_removes_default_ignored_targets_but_not_gated_assets() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_cleanup")
    with TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        runs_file = repo_root / "runs" / "batch" / "output.bin"
        source_file = (
            repo_root
            / "workspace"
            / "alpasim"
            / "data"
            / "nre-artifacts"
            / "all-usdzs"
            / "private.usdz"
        )
        for path in (runs_file, source_file):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

        report = module.build_cleanup_report(repo_root=repo_root, apply=True)
        targets = {row["id"]: row for row in report["targets"]}

        assert targets["benchmark_runs"]["action"] == "removed"
        assert targets["source_all_usdzs"]["action"] == "skipped_not_included"
        assert not (repo_root / "runs").exists()
        assert source_file.exists()


def test_cleanup_gated_assets_and_scale_caches_are_explicit_opt_in() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_cleanup")
    with TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        source_dir = repo_root / "workspace" / "alpasim" / "data" / "nre-artifacts" / "all-usdzs"
        scale_dir = (
            repo_root / "workspace" / "alpasim" / "data" / "nre-artifacts" / "local-2602-usdzs-50"
        )
        for directory in (source_dir, scale_dir):
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "scene.usdz").write_bytes(b"x")

        report = module.build_cleanup_report(
            repo_root=repo_root,
            apply=True,
            include_gated_assets=True,
            include_scale_caches=True,
        )
        targets = {row["id"]: row for row in report["targets"]}

        assert targets["source_all_usdzs"]["action"] == "removed"
        assert targets["scale_cache_50"]["action"] == "removed"
        assert not source_dir.exists()
        assert not scale_dir.exists()


def test_cleanup_refuses_to_remove_targets_with_tracked_files() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_cleanup")
    with TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        tracked_file = repo_root / "runs" / "tracked.txt"
        tracked_file.parent.mkdir(parents=True)
        tracked_file.write_text("tracked\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=repo_root, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(
            ["git", "add", "runs/tracked.txt"],
            cwd=repo_root,
            check=True,
            stdout=subprocess.DEVNULL,
        )

        report = module.build_cleanup_report(repo_root=repo_root, apply=True)
        targets = {row["id"]: row for row in report["targets"]}

        assert targets["benchmark_runs"]["action"] == "skipped_tracked_files"
        assert targets["benchmark_runs"]["tracked_file_count"] == 1
        assert targets["benchmark_runs"]["tracked_files_sample"] == ["runs/tracked.txt"]
        assert tracked_file.exists()


def test_cleanup_refuses_to_remove_targets_tracked_by_nested_git_checkout() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_cleanup")
    with TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        alpasim_root = repo_root / "workspace" / "alpasim"
        tracked_file = alpasim_root / "outputs" / "tracked.txt"
        tracked_file.parent.mkdir(parents=True)
        tracked_file.write_text("tracked\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=repo_root, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "init"], cwd=alpasim_root, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(
            ["git", "add", "outputs/tracked.txt"],
            cwd=alpasim_root,
            check=True,
            stdout=subprocess.DEVNULL,
        )

        report = module.build_cleanup_report(repo_root=repo_root, apply=True)
        targets = {row["id"]: row for row in report["targets"]}

        assert targets["alpasim_outputs"]["action"] == "skipped_tracked_files"
        assert targets["alpasim_outputs"]["tracked_files_sample"] == [
            "workspace/alpasim/outputs/tracked.txt"
        ]
        assert tracked_file.exists()


def test_cleanup_main_writes_json_report() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_cleanup")
    with TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        output = repo_root / "cleanup.json"
        (repo_root / ".ruff_cache").mkdir()

        with patch.object(
            sys,
            "argv",
            [
                "wod2sim-benchmark-cleanup",
                "--repo-root",
                str(repo_root),
                "--created-at",
                "2026-07-06",
                "--output",
                str(output),
                "--json",
            ],
        ):
            returncode = module.main()

        report = json.loads(output.read_text(encoding="utf-8"))

    assert returncode == 0
    assert report["generator"]["command"] == "wod2sim-benchmark-cleanup"
    assert report["apply"] is False
    assert any(
        row["id"] == "ruff_cache" and row["action"] == "would_remove" for row in report["targets"]
    )
