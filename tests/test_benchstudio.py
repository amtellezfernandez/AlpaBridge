"""Only fake scene commands: no simulator, Docker invocation or learned model."""
import json
import sys

import pytest

# Optional integration: the public AlpaBridge test suite needs no private package.
pytest.importorskip("benchstudio")

from alpabridge.benchstudio import AlpaSimPipeline
from alpabridge.cli.commands import run_alpasim_scene_batch as batch


def test_configuration_is_inert_and_check_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "execute_batch", lambda args: pytest.fail("launched batch"))
    pipeline = AlpaSimPipeline(model="route_following", output_dir=tmp_path / "out",
                              alpasim_root=tmp_path, scene_ids=("fake-scene",))
    monkeypatch.setattr("alpabridge.benchstudio.shutil.which", lambda value: str(value))
    report = pipeline.check()
    assert report.technical_ready and not report.native_verified
    assert not (tmp_path / "out").exists()


def test_missing_checkpoint_blocks_before_execution(tmp_path, monkeypatch):
    monkeypatch.setattr("alpabridge.benchstudio.shutil.which", lambda value: str(value))
    pipeline = AlpaSimPipeline(model="token_dagger_bc", output_dir=tmp_path / "out",
                              alpasim_root=tmp_path, scene_ids=("fake-scene",))
    with pytest.raises(ValueError, match="requires checkpoint"):
        pipeline.run()
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("complete,exit_code", [(True, 0), (False, 0), (True, 7)])
def test_native_scene_contract_with_real_stdlib_process(tmp_path, monkeypatch, complete, exit_code):
    run = tmp_path / "scene"
    code = ('import pathlib,sys; p=pathlib.Path(sys.argv[2]); '
            'p.joinpath("aggregate").mkdir(parents=True,exist_ok=True); '
            + ('p.joinpath("aggregate/metrics_results.txt").write_text("synthetic"); ' if complete else '')
            + f'print("synthetic driver"); sys.exit({exit_code})')
    monkeypatch.setattr("alpabridge.benchstudio.shutil.which", lambda value: str(value))
    monkeypatch.setattr(batch, "_scene_command", lambda args, scene_id, run_dir:
        [sys.executable, "-c", code, "--run-dir", str(run_dir)])
    cleanups = []
    monkeypatch.setattr(batch, "_cleanup_failed_scene", lambda *a, **kw: cleanups.append(True))
    pipeline = AlpaSimPipeline(model="route_following", alpasim_root=tmp_path,
                              output_dir=run, scene_ids=("fake-scene",), max_retries=1)
    result = pipeline.run()
    success = complete and exit_code == 0
    assert result.completed == success
    attempts = 1 if success else 2
    assert result.report["runs"][0]["attempts"] == attempts
    receipts = list(run.glob("*/attempt-*/process-logs/scene.receipt.json"))
    assert len(receipts) == attempts
    assert all(json.loads(path.read_text())["exit_code"] == exit_code for path in receipts)
    assert len(cleanups) == attempts


def test_pipeline_discovery_cli_and_batch_accounting(tmp_path, monkeypatch):
    import benchstudio as bs
    from benchstudio.commands import main
    distribution = tmp_path / "alpabridge_integration_test-0.1.dist-info"
    distribution.mkdir()
    (distribution / "METADATA").write_text("Name: alpabridge-integration-test\nVersion: 0.1\n")
    (distribution / "entry_points.txt").write_text(
        '[benchstudio.pipelines]\nalpasim = alpabridge.benchstudio:recipe\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr("alpabridge.benchstudio.shutil.which", lambda value: str(value))
    monkeypatch.setattr(batch, "_scene_command", lambda args, scene_id, run_dir: [
        sys.executable, "-c", 'import pathlib,sys; p=pathlib.Path(sys.argv[2])/"aggregate"; '
        'p.mkdir(parents=True,exist_ok=True); (p/"metrics_results.txt").write_text("synthetic")',
        "--run-dir", str(run_dir)])
    evaluation = bs.pipeline("alpasim", model="route_following", output_dir=tmp_path / "out",
                             alpasim_root=tmp_path, scene_ids=("fake-scene",))
    assert main(["evaluate", "--recipe", "alpasim", "--model", "route_following",
                 "--output-dir", str(tmp_path / "out"), "--alpasim-root", str(tmp_path),
                 "--scene-id", "fake-scene", "--check"]) == 0
    assert not (tmp_path / "out").exists()
    result = evaluation.run()
    assert result.completed
    assert not result.successful  # Artifact presence alone is not a clean native audit.
    assert result.report["scene_count"] == 1
    assert "1/1 scenes completed" in result.summary()
    assert json.loads((tmp_path / "out/batch-manifest.json").read_text())["executor"] == "benchstudio"
    reopened = bs.open_run(tmp_path / "out", backend="alpasim")
    assert reopened.metrics == result.metrics
    assert reopened.audit["aggregate"] == result.audit["aggregate"]


def test_partial_batch_is_not_success():
    from alpabridge.benchstudio import BatchResult
    result = BatchResult({"failed_runs": [], "completed_runs": ["one"], "scene_count": 2})
    assert not result.successful


def test_interruption_cleans_native_containers_without_retry(tmp_path, monkeypatch):
    import benchstudio as bs
    cleanups = []
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(bs.ProcessCommand, "execute", interrupt)
    monkeypatch.setattr(batch, "_cleanup_failed_scene", lambda *a, **kw: cleanups.append(True))
    monkeypatch.setattr("alpabridge.benchstudio.shutil.which", lambda value: str(value))
    pipeline = AlpaSimPipeline(model="route_following", alpasim_root=tmp_path,
                              output_dir=tmp_path / "out", scene_ids=("fake-scene",), max_retries=5)
    with pytest.raises(KeyboardInterrupt):
        pipeline.run()
    assert cleanups == [True]


def test_old_benchstudio_fails_before_writing_batch(tmp_path, monkeypatch):
    import benchstudio as bs
    monkeypatch.delattr(bs.ProcessCommand, "execute")
    pipeline = AlpaSimPipeline(model="route_following", output_dir=tmp_path / "out",
                              alpasim_root=tmp_path, scene_ids=("fake-scene",))
    with pytest.raises(RuntimeError, match="execute support"):
        batch.execute_batch(pipeline.args)
    assert not (tmp_path / "out").exists()
