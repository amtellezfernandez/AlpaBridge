"""Shared-engine case execution with stdlib-only fake commands."""
import json
import sys

import pytest

pytest.importorskip("benchstudio")

import benchstudio as bs
from alpabridge.benchstudio import AlpaSimPipeline
from alpabridge.cli.commands import run_alpasim_scene_batch as batch


def configure(tmp_path, monkeypatch, *, max_retries=0, timeout=5, scenes=("fake-a", "fake-b")):
    monkeypatch.setattr("alpabridge.benchstudio.shutil.which", lambda value: str(value))
    monkeypatch.setattr(batch, "_run_scene_with_retries", lambda *a, **kw: pytest.fail("legacy loop used"))
    return AlpaSimPipeline(model="route_following", alpasim_root=tmp_path,
        config=bs.EvaluationConfig(output_dir=tmp_path / "out", timeout=timeout, max_retries=max_retries),
        scene_ids=scenes)


def test_engine_owns_batch_and_each_retry_has_fresh_artifacts(tmp_path, monkeypatch):
    pipeline = configure(tmp_path, monkeypatch, max_retries=1)
    launches, cleanups = [], []
    def command(args, *, scene_id, run_dir):
        launches.append((scene_id, run_dir))
        # First attempt writes an aggregate but fails. Second exits zero WITHOUT
        # aggregate: stale artifacts must not make it successful.
        code = ('import pathlib,sys; p=pathlib.Path(sys.argv[2])/"aggregate"; '
                'p.mkdir(parents=True); (p/"metrics_results.txt").write_text("synthetic"); '
                'sys.exit(3)' if run_dir.name == "attempt-0001" else 'pass')
        return [sys.executable, "-c", code, "--run-dir", str(run_dir)]
    monkeypatch.setattr(batch, "_scene_command", command)
    monkeypatch.setattr(batch, "_cleanup_failed_scene", lambda command, **kw: cleanups.append(command))
    assert isinstance(pipeline.engine, bs.EvaluationEngine)
    result = pipeline.run()
    assert not result.completed and not result.successful
    assert len(launches) == len(cleanups) == 2
    assert launches[0][1] != launches[1][1]
    assert all(scene == "fake-a" for scene, path in launches)
    rows = [json.loads(line) for line in (tmp_path / "out/cases.jsonl").read_text().splitlines()]
    assert [row["completed"] for row in rows] == [False, False]
    assert result.report["runs"][0]["attempts"] == 2


def test_native_cli_selecting_benchstudio_uses_the_same_engine(tmp_path, monkeypatch):
    pipeline = configure(tmp_path, monkeypatch, scenes=("fake-a",))
    monkeypatch.setattr(batch, "_scene_command", lambda args, scene_id, run_dir: [
        sys.executable, "-c", 'import pathlib,sys; p=pathlib.Path(sys.argv[2])/"aggregate"; '
        'p.mkdir(parents=True); (p/"metrics_results.txt").write_text("synthetic")',
        "--run-dir", str(run_dir)])
    monkeypatch.setattr(batch, "_cleanup_failed_scene", lambda *a, **kw: None)
    report = batch.execute_batch(pipeline.args)
    assert len(report["completed_runs"]) == 1
    assert (tmp_path / "out/execution.json").exists()
    assert (tmp_path / "out/cases.jsonl").exists()
    plan = json.loads((tmp_path / "out/benchmark.json").read_text())
    assert plan["mode"] == "protocol" and plan["case_count"] == 1
    assert plan["cases"][0]["dimensions"]["scene"] == "fake-a"


def test_native_cli_rejects_completed_but_unaudited_results(tmp_path, monkeypatch):
    pipeline = configure(tmp_path, monkeypatch, scenes=("fake-a",))
    monkeypatch.setattr(batch, "_parse_args", lambda: pipeline.args)
    monkeypatch.setattr(batch, "_scene_command", lambda args, scene_id, run_dir: [
        sys.executable, "-c", 'import pathlib,sys; p=pathlib.Path(sys.argv[2])/"aggregate"; '
        'p.mkdir(parents=True); (p/"metrics_results.txt").write_text("synthetic")',
        "--run-dir", str(run_dir)])
    monkeypatch.setattr(batch, "_cleanup_failed_scene", lambda *a, **kw: None)
    assert batch.main() == 1
    report = json.loads((tmp_path / "out/batch-status.json").read_text())
    assert len(report["completed_runs"]) == 1


def test_alpasim_exposes_a_complete_scene_benchmark(tmp_path, monkeypatch):
    pipeline = configure(tmp_path, monkeypatch, scenes=("fake-a", "fake-b"))
    check = pipeline.check()
    assert check.mode == "protocol" and check.cases == check.executions == 2
    assert pipeline.engine.benchmark is pipeline.benchmark
    assert len(pipeline.benchmark.cases) == 2
    assert pipeline.benchmark.environment_revision == "UNVERIFIED_NATIVE_ENVIRONMENT"
    assert not check.native_verified


def test_alpasim_revisions_are_explicit_declarations(tmp_path):
    pipeline = AlpaSimPipeline(model="route_following", alpasim_root=tmp_path,
        output_dir=tmp_path / "out", scene_ids=("fake-a", "fake-b"),
        benchmark_revision="reviewed-calendar-r2", evaluator_revision="native-audit-r3",
        environment_revision="caller-stack-r4")
    plan = pipeline.benchmark.describe()
    assert plan["revision"] == "reviewed-calendar-r2"
    assert plan["environment_revision"] == "caller-stack-r4"
    assert plan["evaluator_revision"] == "native-audit-r3"
    assert not (tmp_path / "out").exists()


def test_timeout_cleans_and_stops_without_using_retry_budget(tmp_path, monkeypatch):
    pipeline = configure(tmp_path, monkeypatch, max_retries=5, timeout=1)
    monkeypatch.setattr(batch, "_scene_command", lambda args, scene_id, run_dir: [
        sys.executable, "-c", "import time; time.sleep(60)", "--run-dir", str(run_dir)])
    cleanups = []
    monkeypatch.setattr(batch, "_cleanup_failed_scene", lambda *a, **kw: cleanups.append(True))
    with pytest.raises(bs.ProcessFailure, match="timed out"):
        pipeline.run()
    assert cleanups == [True]
    record = json.loads((tmp_path / "out/execution.json").read_text())
    assert record["status"] == "execution_failed"
    native = json.loads((tmp_path / "out/batch-status.json").read_text())
    assert native["runs"][0]["attempts"] == 1
    assert len(list((tmp_path / "out").glob("*/attempt-*"))) == 1


def test_cleanup_failure_is_retained_and_never_retried(tmp_path, monkeypatch):
    pipeline = configure(tmp_path, monkeypatch, max_retries=5, scenes=("fake-a",))
    monkeypatch.setattr(batch, "_scene_command", lambda args, scene_id, run_dir: [
        sys.executable, "-c", 'import pathlib,sys; p=pathlib.Path(sys.argv[2]); '
        '(p/"docker-compose.yaml").write_text("synthetic"); '
        '(p/"aggregate").mkdir(); (p/"aggregate/metrics_results.txt").write_text("synthetic")',
        "--run-dir", str(run_dir)])
    original = bs.ProcessCommand.execute
    cleanup = []
    def execute(command, *args, **kwargs):
        if command.name == "cleanup":
            cleanup.append(command)
            raise bs.ProcessFailure("synthetic cleanup failure")
        return original(command, *args, **kwargs)
    monkeypatch.setattr(bs.ProcessCommand, "execute", execute)
    with pytest.raises(bs.ProcessFailure, match="cleanup failure"):
        pipeline.run()
    assert len(cleanup) == 1 and cleanup[0].timeout == 30
    assert cleanup[0].argv[:2] == ("docker", "compose")
    native = json.loads((tmp_path / "out/batch-status.json").read_text())
    assert native["runs"][0]["result"] == "failed"


def test_scene_error_remains_primary_when_cleanup_also_fails(tmp_path, monkeypatch):
    pipeline = configure(tmp_path, monkeypatch, max_retries=5, scenes=("fake-a",))
    def command(args, *, scene_id, run_dir):
        (run_dir / "docker-compose.yaml").write_text("synthetic")
        return ["synthetic-command", "--run-dir", str(run_dir)]
    monkeypatch.setattr(batch, "_scene_command", command)
    def execute(command, *args, **kwargs):
        if command.name == "cleanup":
            raise bs.ProcessFailure("cleanup failure")
        raise ValueError("native execution failure")
    monkeypatch.setattr(bs.ProcessCommand, "execute", execute)
    with pytest.raises(ValueError, match="native execution failure") as caught:
        pipeline.run()
    assert isinstance(caught.value.__cause__, bs.ProcessFailure)
    rows = (tmp_path / "out/cases.jsonl").read_text().splitlines()
    assert len(rows) == 1
