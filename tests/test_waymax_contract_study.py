from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import wod2sim.experiments.waymax_contract_study as study
from wod2sim.experiments.waymax_contract_study import (
    METRIC_NAMES,
    OUTPUT_FUTURE_POINTS,
    ROLLOUT_STEPS,
    WAYMAX_COMMIT,
    WAYMAX_DATA_RELATIVE_PATH,
    RoutePath,
    _command_proxy_route,
    _contract_diagnostics,
    _extract_sdc_metrics,
    _finite_float,
    _plan_trajectory,
    _policy_contrast,
    _route_distance,
    _scenario_fingerprint,
    _sdc_index,
    _select_route,
    _state_timestamp_us,
    _trajectory_action,
    _verify_waymax_checkout,
    advance_pose,
    load_retained_study,
    summarize_scenario_rows,
)


def test_route_controller_advances_from_current_pose_without_jumping() -> None:
    route = RoutePath(
        xy=np.asarray([[0.0, 0.0], [10.0, 0.0]], dtype=np.float64),
        arc_length=np.asarray([0.0, 10.0], dtype=np.float64),
    )

    x, y, yaw = advance_pose(
        x=5.0,
        y=0.0,
        yaw=0.0,
        speed_mps=2.0,
        route=route,
    )

    assert x == 5.2
    assert y == 0.0
    assert yaw == 0.0


def test_removed_route_uses_a_proxy_with_the_same_route_controller_contract() -> None:
    proxy = _command_proxy_route(x=3.0, y=-2.0, yaw=math.pi / 2.0)

    x, y, yaw = advance_pose(
        x=3.0,
        y=-2.0,
        yaw=math.pi / 2.0,
        speed_mps=4.0,
        route=proxy,
    )

    assert math.isclose(x, 3.0, abs_tol=1e-12)
    assert math.isclose(y, -1.6, abs_tol=1e-12)
    assert math.isclose(yaw, math.pi / 2.0, abs_tol=1e-12)


def test_route_independent_motion_and_stationary_pose_are_exact() -> None:
    moving = advance_pose(
        x=1.0,
        y=2.0,
        yaw=math.pi,
        speed_mps=3.0,
        route=None,
    )
    stationary = advance_pose(
        x=1.0,
        y=2.0,
        yaw=0.7,
        speed_mps=0.0,
        route=_command_proxy_route(x=1.0, y=2.0, yaw=0.7),
    )

    assert moving == pytest.approx((0.7, 2.0, math.pi))
    assert stationary == (1.0, 2.0, 0.7)


def test_policy_contrast_uses_paired_position_and_heading_traces() -> None:
    full_trace = [[float(step), 0.0] for step in range(ROLLOUT_STEPS + 1)]
    removed_trace = [[float(step), step / ROLLOUT_STEPS] for step in range(ROLLOUT_STEPS + 1)]

    contrast = _policy_contrast(
        {"position_trace_xy": full_trace, "final_heading_rad": 0.0},
        {"position_trace_xy": removed_trace, "final_heading_rad": 0.5},
    )

    assert contrast["endpoint_difference_m"] == 1.0
    assert contrast["mean_displacement_divergence_m"] == 0.5
    assert contrast["final_heading_difference_rad"] == 0.5
    assert len(contrast["displacement_divergence_over_time_m"]) == ROLLOUT_STEPS + 1


def test_policy_contrast_rejects_unpaired_trace_shapes() -> None:
    with pytest.raises(ValueError, match="invalid position trace"):
        _policy_contrast(
            {"position_trace_xy": [[0.0, 0.0]], "final_heading_rad": 0.0},
            {"position_trace_xy": [[0.0, 0.0]], "final_heading_rad": 0.0},
        )


def test_contract_audit_rejects_only_route_dependent_removed_route_arm() -> None:
    common = {
        "session_uuid": "study-arm",
        "route_source": "command_proxy",
        "route_waypoint_count": 201,
        "timestamp_us": 1_000_000,
    }

    route_following = _contract_diagnostics(
        **common,
        route_geometry_required=True,
    )
    constant_velocity = _contract_diagnostics(
        **common,
        route_geometry_required=False,
    )

    assert route_following == ["semantic.command_only"]
    assert constant_velocity == []


def test_contract_audit_rejects_missing_route_before_drive() -> None:
    diagnostics = _contract_diagnostics(
        session_uuid="missing-route",
        route_source="missing",
        route_waypoint_count=0,
        timestamp_us=1_000_000,
    )

    assert diagnostics == ["semantic.route_missing"]


def test_factorial_summary_reports_interaction_and_negative_control() -> None:
    rows = [
        _eligible_row(route_following_difference=2.0),
        {
            "eligible": False,
            "contract_diagnostics": ["semantic.route_missing"],
        },
    ]

    summary = summarize_scenario_rows(rows)

    assert summary["comparison_eligible_scenarios"] == 1
    assert summary["route_unavailable_scenarios"] == 1
    assert summary["closed_loop_steps_total"] == ROLLOUT_STEPS * 4
    assert summary["endpoint_difference_m"]["route_following"]["median"] == 2.0
    assert summary["endpoint_difference_m"]["constant_velocity"]["max"] == 0.0
    assert summary["difference_in_differences_endpoint_m"]["mean"] == 2.0
    assert summary["negative_control_invariant_scenarios"] == 1
    assert all(
        check["supported_for_fixture"]
        for check in summary["predeclared_check_results"].values()
    )


def test_factorial_summary_requires_an_eligible_pair() -> None:
    with pytest.raises(ValueError, match="no comparison-eligible scenarios"):
        summarize_scenario_rows(
            [{"eligible": False, "contract_diagnostics": ["semantic.route_missing"]}]
        )


def test_retained_waymax_artifact_recomputes_from_scenario_rows() -> None:
    root = (
        Path(__file__).resolve().parents[1]
        / "artifacts"
        / "external"
        / "waymax_contract_study"
    )

    retained = load_retained_study(root)

    assert retained["available"] is True
    assert retained["behavior"]["comparison_eligible_scenarios"] == 19
    assert retained["behavior"]["negative_control_invariant_scenarios"] == 19
    assert all(
        row["arms"][policy]["command_proxy"]["policy_input_contract"][
            "route_waypoint_count"
        ]
        == 201
        for row in _retained_scenario_rows(root)
        if row["eligible"]
        for policy in ("route_following", "constant_velocity")
    )
    assert all(
        result["supported_for_fixture"]
        for result in retained["behavior"]["predeclared_check_results"].values()
    )


def test_retained_loader_reports_absent_artifacts(tmp_path: Path) -> None:
    assert load_retained_study(tmp_path) == {"available": False}


def test_route_selection_and_policy_plans_use_the_declared_signature() -> None:
    state = _dummy_state()

    route = _select_route(state)
    route_following = _plan_trajectory(
        state,
        policy="route_following",
        route_condition="full_route",
    )
    constant_velocity = _plan_trajectory(
        state,
        policy="constant_velocity",
        route_condition="full_route",
    )

    assert route is not None
    assert route.xy.tolist() == [[0.0, 0.0], [0.0, 5.0], [0.0, 10.0]]
    assert _route_distance(state) == 0.0
    assert route_following.shape == (OUTPUT_FUTURE_POINTS, 2)
    assert constant_velocity.shape == (OUTPUT_FUTURE_POINTS, 2)
    assert route_following[0] == pytest.approx([0.0, 0.2])
    assert constant_velocity[0] == pytest.approx([0.2, 0.0])


def test_route_selection_rejects_missing_or_degenerate_geometry() -> None:
    absent = _dummy_state(route_valid_points=0)
    degenerate = _dummy_state(route_valid_points=1)

    assert _select_route(absent) is None
    assert _select_route(degenerate) is None
    with pytest.raises(ValueError, match="lost its on-route path"):
        _route_distance(absent)
    with pytest.raises(ValueError, match="no route representation"):
        _plan_trajectory(
            absent,
            policy="route_following",
            route_condition="full_route",
        )


@pytest.mark.parametrize(
    ("policy", "condition", "message"),
    [
        ("unknown", "full_route", "unsupported policy"),
        ("route_following", "unknown", "unsupported route condition"),
    ],
)
def test_planner_rejects_unknown_factor_levels(
    policy: str,
    condition: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _plan_trajectory(_dummy_state(), policy=policy, route_condition=condition)


def test_trajectory_action_controls_only_the_sdc() -> None:
    state = _dummy_state()
    trajectory = np.zeros((OUTPUT_FUTURE_POINTS, 2), dtype=np.float32)
    trajectory[:, 1] = np.arange(1, OUTPUT_FUTURE_POINTS + 1) * 0.2
    datatypes = SimpleNamespace(
        Action=lambda *, data, valid: SimpleNamespace(data=data, valid=valid)
    )

    action = _trajectory_action(
        state,
        trajectory=trajectory,
        datatypes=datatypes,
        jnp=np,
    )

    assert action.data.shape == (2, 5)
    assert action.valid[:, 0].tolist() == [True, False]
    assert action.data[0, :3] == pytest.approx([0.0, 0.2, math.pi / 2.0])
    assert action.data[0, 3:] == pytest.approx([0.0, 2.0], abs=1e-6)
    with pytest.raises(ValueError, match="unexpected planned trajectory shape"):
        _trajectory_action(
            state,
            trajectory=trajectory[:-1],
            datatypes=datatypes,
            jnp=np,
        )


def test_metric_extraction_checks_validity_and_finiteness() -> None:
    results = {
        name: SimpleNamespace(
            value=np.asarray([1.0, 2.0]),
            valid=np.asarray([True, True]),
        )
        for name in METRIC_NAMES
    }

    assert set(_extract_sdc_metrics(results, 0)) == set(METRIC_NAMES)
    results[METRIC_NAMES[0]] = SimpleNamespace(
        value=np.asarray([math.nan, 2.0]),
        valid=np.asarray([True, True]),
    )
    with pytest.raises(ValueError, match="invalid for the SDC"):
        _extract_sdc_metrics(results, 0)
    with pytest.raises(ValueError, match="expected finite value"):
        _finite_float(math.inf)


def test_state_identity_helpers_require_exactly_one_sdc() -> None:
    state = _dummy_state()
    fingerprint = _scenario_fingerprint(state)

    assert len(fingerprint) == 64
    assert _scenario_fingerprint(state) == fingerprint
    assert _sdc_index(state) == 0
    assert _state_timestamp_us(state) == 1_000_000

    state.object_metadata.is_sdc = np.asarray([True, True])
    with pytest.raises(ValueError, match="expected exactly one SDC"):
        _sdc_index(state)


def test_waymax_checkout_gate_requires_commit_and_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "waymax"
    with pytest.raises(ValueError, match="has no .git directory"):
        _verify_waymax_checkout(root)

    (root / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        study.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="wrong-commit\n"),
    )
    with pytest.raises(ValueError, match="must be at"):
        _verify_waymax_checkout(root)

    monkeypatch.setattr(
        study.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=f"{WAYMAX_COMMIT}\n"),
    )
    with pytest.raises(ValueError, match="fixture is missing"):
        _verify_waymax_checkout(root)

    fixture = root / WAYMAX_DATA_RELATIVE_PATH
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"fixture")
    _verify_waymax_checkout(root)


def _dummy_state(*, route_valid_points: int = 3) -> SimpleNamespace:
    route_xy = np.asarray([[[0.0, 0.0], [0.0, 5.0], [0.0, 10.0]]])
    route_valid = np.zeros((1, 3), dtype=bool)
    route_valid[0, :route_valid_points] = True
    current = SimpleNamespace(
        x=np.asarray([[0.0], [5.0]]),
        y=np.asarray([[0.0], [5.0]]),
        xy=np.asarray([[[0.0, 0.0]], [[5.0, 5.0]]]),
        yaw=np.asarray([[0.0], [0.0]]),
        vel_x=np.asarray([[2.0], [0.0]]),
        vel_y=np.asarray([[0.0], [0.0]]),
        timestamp_micros=np.asarray([[1_000_000], [1_000_000]]),
    )
    return SimpleNamespace(
        object_metadata=SimpleNamespace(
            ids=np.asarray([101, 202]),
            is_sdc=np.asarray([True, False]),
        ),
        current_sim_trajectory=current,
        log_trajectory=SimpleNamespace(
            num_objects=2,
            xy=np.asarray([[[0.0, 0.0]], [[5.0, 5.0]]]),
            valid=np.asarray([[True], [True]]),
        ),
        sdc_paths=SimpleNamespace(
            xy=route_xy,
            valid=route_valid,
            on_route=np.asarray([[True]]),
            arc_length=np.asarray([[0.0, 5.0, 10.0]]),
        ),
    )


def _retained_scenario_rows(root: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (root / "scenario-results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def _eligible_row(*, route_following_difference: float) -> dict[str, Any]:
    zero_metrics = {name: 0.0 for name in METRIC_NAMES}
    clean_arm = {
        "mean_route_distance_m": 0.25,
        "final_metrics": zero_metrics,
        "contract_diagnostics": [],
    }
    command_proxy_arm = {
        "mean_route_distance_m": 0.75,
        "final_metrics": zero_metrics,
        "contract_diagnostics": ["semantic.command_only"],
    }
    return {
        "eligible": True,
        "arms": {
            "route_following": {
                "full_route": clean_arm,
                "command_proxy": command_proxy_arm,
            },
            "constant_velocity": {
                "full_route": clean_arm,
                "command_proxy": clean_arm,
            },
        },
        "contrasts": {
            "route_following": {
                "endpoint_difference_m": route_following_difference,
                "displacement_divergence_over_time_m": [
                    route_following_difference * step / ROLLOUT_STEPS
                    for step in range(ROLLOUT_STEPS + 1)
                ],
            },
            "constant_velocity": {
                "endpoint_difference_m": 0.0,
                "displacement_divergence_over_time_m": [
                    0.0 for _ in range(ROLLOUT_STEPS + 1)
                ],
            },
        },
        "difference_in_differences_endpoint_m": route_following_difference,
    }
