"""Saved native fixtures only: no driver, simulator or model execution."""
import json

import pytest

pytest.importorskip("benchstudio")

import benchstudio as bs
from alpabridge.benchstudio import AlpaSimPipeline, BatchResult, recipe
from test_batch_summary import _write_batch, _write_run


def test_shared_configuration_and_static_check(tmp_path, monkeypatch):
    monkeypatch.setattr("alpabridge.benchstudio.shutil.which", lambda value: str(value))
    pipeline = AlpaSimPipeline(model="route_following", alpasim_root=tmp_path,
        config=bs.EvaluationConfig(run_id="paired-driving", output_dir=tmp_path / "out", timeout=300),
        scene_ids=("scene-a",))
    report = pipeline.check()
    assert isinstance(report, bs.EvaluationCheck)
    assert report.configuration_valid and report.technical_ready
    assert report.cases == 1 and not report.native_verified
    assert pipeline.args.timeout == 300 and pipeline.args.run_id == "paired-driving"
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("config", [bs.EvaluationConfig(concurrency=2),
    bs.EvaluationConfig(batch_size=2), bs.EvaluationConfig(timeout=.5)])
def test_unsupported_execution_settings_fail_explicitly(tmp_path, config):
    from dataclasses import replace
    with pytest.raises(ValueError):
        AlpaSimPipeline(model="route_following", alpasim_root=tmp_path,
                       config=replace(config, output_dir=tmp_path / "out"))


def test_duplicate_configuration_is_not_silently_ignored(tmp_path):
    with pytest.raises(ValueError, match="belong in config"):
        AlpaSimPipeline(model="route_following", alpasim_root=tmp_path,
                       config=bs.EvaluationConfig(output_dir=tmp_path / "out"),
                       output_dir=tmp_path / "other")


@pytest.mark.parametrize("clean", [False, True])
def test_results_reuse_native_metrics_and_failure_contracts(tmp_path, monkeypatch, clean):
    _write_batch(tmp_path, route_contract_ok=clean)
    _write_run(tmp_path, "001_scene-a", collision_any=1, wrong_lane=0, progress=.4)
    _write_run(tmp_path, "002_scene-b", collision_any=0, wrong_lane=0, progress=.9)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: pytest.fail("launched process"))
    result = recipe.open_run(tmp_path)
    assert result.completed and result.successful == clean
    assert result.metrics["collision_any"]["mean"] == .5
    assert result.audit["failure_taxonomy"]["collision_scene_count"] == 1
    # This evaluates retained artifacts, not whether the driving task succeeded.
    assert result.audit["aggregate"]["planned_scene_count"] == 2


def test_corrupt_native_accounting_cannot_be_presented_as_success(tmp_path):
    _write_batch(tmp_path)
    path = tmp_path / "batch-status.json"
    report = json.loads(path.read_text())
    report["runs"].append(report["runs"][0])
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="accounting"):
        BatchResult.from_directory(tmp_path)
