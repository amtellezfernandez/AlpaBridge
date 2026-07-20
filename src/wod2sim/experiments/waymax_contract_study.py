from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from wod2sim.audit.trace_diagnostics import DEFAULT_CONTEXT, diagnose_contract_trace

WAYMAX_REPOSITORY = "https://github.com/waymo-research/waymax.git"
WAYMAX_COMMIT = "a64dfec9be8576b60d9cecc94f406d9812d4a7d0"
WAYMAX_DATA_RELATIVE_PATH = Path("waymax/dataloader/testdata/tfrecord_with_routes")
WAYMAX_DATA_SHA256 = "aba63d14b00d133803db04f49a3263447beafd8ca3010ea535ca7dfff0635ba5"
TELEMETRY_SCHEMA = "wod2sim_contract_telemetry_v4"
ROLLOUT_STEPS = 50
OUTPUT_FUTURE_POINTS = 50
STEP_SECONDS = 0.1
ROUTE_LOOKAHEAD_SECONDS = 0.5
MIN_ROUTE_LOOKAHEAD_M = 2.0
ENDPOINT_CHANGE_THRESHOLD_M = 0.1
MATERIAL_ENDPOINT_CHANGE_THRESHOLD_M = 1.0
ROUTE_DISTANCE_EQUAL_TOLERANCE_M = 1e-6
NEGATIVE_CONTROL_INVARIANCE_TOLERANCE_M = 1e-6
COMMAND_PROXY_INTENT = "KEEP_HEADING"
POLICIES = ("route_following", "constant_velocity")
ROUTE_CONDITIONS = ("full_route", "command_proxy")
METRIC_NAMES = (
    "log_divergence",
    "overlap",
    "offroad",
    "sdc_wrongway",
    "sdc_off_route",
    "sdc_progression",
    "kinematic_infeasibility",
)


@dataclass(frozen=True)
class RoutePath:
    xy: np.ndarray
    arc_length: np.ndarray


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the WOD2Sim route-contract ablation on Waymax's pinned 20-scenario "
            "WOMD fixture."
        )
    )
    parser.add_argument(
        "--waymax-root",
        required=True,
        type=Path,
        help="Waymax checkout pinned to the expected commit.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/external/waymax_contract_study"),
    )
    parser.add_argument(
        "--scenario-limit",
        type=int,
        default=None,
        help="Optional smoke-test limit. Omit for the retained study.",
    )
    args = parser.parse_args()

    summary = run_study(
        waymax_root=args.waymax_root.resolve(),
        output_dir=args.output.resolve(),
        scenario_limit=args.scenario_limit,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def run_study(
    *,
    waymax_root: Path,
    output_dir: Path,
    scenario_limit: int | None = None,
) -> dict[str, Any]:
    if scenario_limit is not None and scenario_limit < 1:
        raise ValueError("scenario_limit must be positive")
    _verify_waymax_checkout(waymax_root)
    data_path = waymax_root / WAYMAX_DATA_RELATIVE_PATH
    data_sha256 = _sha256_file(data_path)
    if data_sha256 != WAYMAX_DATA_SHA256:
        raise ValueError(
            f"Waymax fixture hash mismatch: expected {WAYMAX_DATA_SHA256}, got {data_sha256}"
        )

    waymax = _import_waymax(waymax_root)
    dataset_config = waymax["config"].DatasetConfig(
        path=str(data_path),
        data_format=waymax["config"].DataFormat.TFRECORD,
        max_num_objects=128,
        include_sdc_paths=True,
        num_paths=30,
        num_points_per_path=200,
        repeat=1,
    )
    environment_config = waymax["config"].EnvironmentConfig(
        max_num_objects=128,
        init_steps=11,
        controlled_object=waymax["config"].ObjectType.SDC,
        compute_reward=False,
        metrics=waymax["config"].MetricsConfig(metrics_to_run=METRIC_NAMES),
    )
    environment = waymax["env"].BaseEnvironment(
        waymax["dynamics"].StateDynamics(),
        environment_config,
    )
    metric_fn = waymax["jax"].jit(environment.metrics)

    scenarios = waymax["dataloader"].simulator_state_generator(dataset_config)
    rows: list[dict[str, Any]] = []
    for scenario_index, scenario in enumerate(scenarios):
        if scenario_limit is not None and scenario_index >= scenario_limit:
            break
        rows.append(
            _run_scenario(
                scenario_index=scenario_index,
                scenario=scenario,
                environment=environment,
                metric_fn=metric_fn,
                waymax=waymax,
            )
        )

    expected_scenario_count = 20 if scenario_limit is None else scenario_limit
    if len(rows) != expected_scenario_count:
        raise ValueError(
            f"Waymax fixture yielded {len(rows)} scenarios; expected {expected_scenario_count}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    scenario_path = output_dir / "scenario-results.jsonl"
    scenario_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    scenario_sha256 = _sha256_file(scenario_path)
    behavior = summarize_scenario_rows(rows)
    implementation_hashes = _implementation_hashes()
    summary = {
        "schema": "wod2sim_waymax_contract_study_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "retained_full_study": scenario_limit is None,
        "runtime": {
            "name": "Waymax",
            "repository": WAYMAX_REPOSITORY,
            "commit": WAYMAX_COMMIT,
            "device": str(waymax["jax"].default_backend()),
            "python_version": sys.version.split()[0],
            "numpy_version": np.__version__,
            "jax_version": waymax["jax"].__version__,
            "jaxlib_version": waymax["jaxlib"].__version__,
            "tensorflow_version": waymax["tensorflow"].__version__,
        },
        "dataset": {
            "name": "Waymax bundled WOMD route fixture",
            "relative_path": str(WAYMAX_DATA_RELATIVE_PATH),
            "sha256": data_sha256,
            "license": "Waymax License Agreement for Non-Commercial Use",
            "raw_records_redistributed_by_wod2sim": False,
        },
        "design": {
            "scientific_question": (
                "Can a contract-aware integration layer distinguish policy degradation "
                "caused by missing decision-relevant inputs from genuine policy failure?"
            ),
            "primary_estimand": (
                "paired endpoint divergence(route_following) minus paired endpoint "
                "divergence(constant_velocity)"
            ),
            "predeclared_checks": {
                "H1_contract_sensitivity": (
                    "route-following median endpoint divergence exceeds "
                    f"{ENDPOINT_CHANGE_THRESHOLD_M} m"
                ),
                "H2_negative_control_invariance": (
                    "every constant-velocity endpoint divergence is at most "
                    f"{NEGATIVE_CONTROL_INVARIANCE_TOLERANCE_M} m"
                ),
                "H3_attribution_correctness": (
                    "only route-following with command-proxy geometry is classified "
                    "as a semantic-contract violation"
                ),
            },
            "factorial_design": {
                "policies": {
                    "route_following": {
                        "controller": "constant-speed no-jump pure pursuit",
                        "signature": ["ego_pose", "ego_velocity", "route_geometry"],
                    },
                    "constant_velocity": {
                        "controller": "constant velocity in the current heading",
                        "signature": ["ego_pose", "ego_velocity"],
                    },
                },
                "route_conditions": {
                    "full_route": "valid WOMD sdc_paths.on_route geometry",
                    "command_proxy": (
                        "original WOMD geometry replaced at the adapter boundary by "
                        "a straight geometric proxy reconstructed from an intervention-"
                        f"defined {COMMAND_PROXY_INTENT} command"
                    ),
                },
            },
            "rollout_steps": ROLLOUT_STEPS,
            "step_seconds": STEP_SECONDS,
            "trajectory_horizon_seconds": OUTPUT_FUTURE_POINTS * STEP_SECONDS,
            "trajectory_future_points": OUTPUT_FUTURE_POINTS,
            "non_sdc_behavior": "Waymax log playback",
            "route_controller": {
                "type": "no-jump pure pursuit",
                "lookahead_seconds": ROUTE_LOOKAHEAD_SECONDS,
                "minimum_lookahead_m": MIN_ROUTE_LOOKAHEAD_M,
            },
            "intervention": (
                "Within each policy, the paired route conditions share scenario, initial "
                "state, horizon, frequency, dynamics, non-SDC log playback, and controller "
                "implementation. The route-following policy receives either the native "
                "geometry or a degraded command-derived proxy. Constant velocity ignores "
                "the same mutated route field and is the negative control."
            ),
            "command_proxy_provenance": (
                f"{COMMAND_PROXY_INTENT} is generated by the intervention operator; "
                "it is not read from the WOMD TFExample."
            ),
            "inference_scope": (
                "Paired descriptive evidence over the complete pinned fixture; the "
                "scenarios are not treated as a random sample from WOMD."
            ),
        },
        "behavior": behavior,
        "scenario_results": {
            "path": scenario_path.name,
            "sha256": scenario_sha256,
        },
        "implementation_sha256": implementation_hashes,
        "claim_boundary": (
            "This is a deterministic policy-by-route negative-control experiment on the "
            "20 scenarios bundled with the pinned Waymax checkout. It supports cross-"
            "runtime semantic-contract applicability and selective paired behavior "
            "consequences for this fixture. "
            "It is not a learned-policy benchmark, a representative WOMD sample, a safety "
            "comparison, a framework-superiority result, or a runtime-overhead measurement."
        ),
    }
    (output_dir / "results-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "wod2sim_waymax_contract_manifest_v1",
        "waymax_commit": WAYMAX_COMMIT,
        "waymax_data_sha256": data_sha256,
        "scenario_results_sha256": scenario_sha256,
        "results_summary_sha256": _sha256_file(output_dir / "results-summary.json"),
        "implementation_sha256": implementation_hashes,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def summarize_scenario_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if row.get("eligible") is True]
    unavailable = [row for row in rows if row.get("eligible") is not True]
    if not eligible:
        raise ValueError("Waymax study has no comparison-eligible scenarios")

    endpoint_differences = {
        policy: [
            _finite_float(row["contrasts"][policy]["endpoint_difference_m"])
            for row in eligible
        ]
        for policy in POLICIES
    }
    difference_in_differences = [
        _finite_float(row["difference_in_differences_endpoint_m"]) for row in eligible
    ]
    full_route_distances = [
        _finite_float(
            row["arms"]["route_following"]["full_route"]["mean_route_distance_m"]
        )
        for row in eligible
    ]
    reduced_route_distances = [
        _finite_float(
            row["arms"]["route_following"]["command_proxy"]["mean_route_distance_m"]
        )
        for row in eligible
    ]
    route_deltas = [
        full - reduced
        for full, reduced in zip(full_route_distances, reduced_route_distances, strict=True)
    ]

    displacement_curves = {
        policy: np.asarray(
            [
                row["contrasts"][policy]["displacement_divergence_over_time_m"]
                for row in eligible
            ],
            dtype=np.float64,
        )
        for policy in POLICIES
    }
    full_better = sum(delta < -ROUTE_DISTANCE_EQUAL_TOLERANCE_M for delta in route_deltas)
    reduced_better = sum(delta > ROUTE_DISTANCE_EQUAL_TOLERANCE_M for delta in route_deltas)
    equal = len(route_deltas) - full_better - reduced_better
    attribution = {
        "route_following_full_route_clean": _arm_diagnostic_count(
            eligible, "route_following", "full_route", []
        ),
        "route_following_command_proxy_semantic_fault": _arm_diagnostic_count(
            eligible,
            "route_following",
            "command_proxy",
            ["semantic.command_only"],
        ),
        "constant_velocity_full_route_clean": _arm_diagnostic_count(
            eligible, "constant_velocity", "full_route", []
        ),
        "constant_velocity_command_proxy_clean": _arm_diagnostic_count(
            eligible, "constant_velocity", "command_proxy", []
        ),
    }
    route_following_summary = _summarize_endpoint_differences(
        endpoint_differences["route_following"]
    )
    constant_velocity_summary = _summarize_endpoint_differences(
        endpoint_differences["constant_velocity"]
    )
    negative_control_invariant = sum(
        value <= NEGATIVE_CONTROL_INVARIANCE_TOLERANCE_M
        for value in endpoint_differences["constant_velocity"]
    )
    attribution_correct = all(value == len(eligible) for value in attribution.values())
    return {
        "scenario_count": len(rows),
        "comparison_eligible_scenarios": len(eligible),
        "route_unavailable_scenarios": len(unavailable),
        "route_unavailable_diagnostic_counts": _count_values(
            str(code)
            for row in unavailable
            for code in row.get("contract_diagnostics", [])
        ),
        "closed_loop_steps_per_arm": ROLLOUT_STEPS,
        "closed_loop_steps_total": len(eligible) * ROLLOUT_STEPS * 4,
        "finite_trajectory_plans": len(eligible) * ROLLOUT_STEPS * 4,
        "attribution": attribution,
        "endpoint_difference_m": {
            "route_following": route_following_summary,
            "constant_velocity": constant_velocity_summary,
        },
        "difference_in_differences_endpoint_m": {
            "mean": _rounded_mean(difference_in_differences),
            "median": _rounded_median(difference_in_differences),
            "max": round(max(difference_in_differences), 6),
            "positive_count": sum(value > 0.0 for value in difference_in_differences),
        },
        "negative_control_invariant_scenarios": negative_control_invariant,
        "predeclared_check_results": {
            "H1_contract_sensitivity": {
                "supported_for_fixture": (
                    route_following_summary["median"]
                    > ENDPOINT_CHANGE_THRESHOLD_M
                ),
                "criterion": (
                    "route-following median endpoint divergence exceeds "
                    f"{ENDPOINT_CHANGE_THRESHOLD_M} m"
                ),
            },
            "H2_negative_control_invariance": {
                "supported_for_fixture": negative_control_invariant == len(eligible),
                "criterion": (
                    "all constant-velocity endpoint divergences are at most "
                    f"{NEGATIVE_CONTROL_INVARIANCE_TOLERANCE_M} m"
                ),
            },
            "H3_attribution_correctness": {
                "supported_for_fixture": attribution_correct,
                "criterion": (
                    "only route-following with command-proxy geometry receives "
                    "semantic.command_only"
                ),
            },
        },
        "displacement_divergence_over_time_m": {
            policy: {
                "mean": [
                    round(float(value), 6)
                    for value in np.mean(displacement_curves[policy], axis=0)
                ],
                "median": [
                    round(float(value), 6)
                    for value in np.median(displacement_curves[policy], axis=0)
                ],
            }
            for policy in POLICIES
        },
        "mean_route_distance_m": {
            "route_following_full_route": _rounded_mean(full_route_distances),
            "route_following_command_proxy": _rounded_mean(reduced_route_distances),
            "paired_full_minus_command_proxy": _rounded_mean(route_deltas),
            "full_lower": full_better,
            "equal": equal,
            "command_proxy_lower": reduced_better,
        },
        "waymax_final_metrics": {
            policy: {
                condition: _summarize_metrics(
                    [
                        row["arms"][policy][condition]["final_metrics"]
                        for row in eligible
                    ]
                )
                for condition in ROUTE_CONDITIONS
            }
            for policy in POLICIES
        },
    }


def load_retained_study(root: Path) -> dict[str, Any]:
    summary_path = root / "results-summary.json"
    manifest_path = root / "manifest.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        return {"available": False}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if summary.get("schema") != "wod2sim_waymax_contract_study_v1":
        raise ValueError("unsupported Waymax study summary schema")
    if manifest.get("schema") != "wod2sim_waymax_contract_manifest_v1":
        raise ValueError("unsupported Waymax study manifest schema")
    if summary.get("retained_full_study") is not True:
        raise ValueError("retained Waymax evidence is not the full study")
    runtime = summary.get("runtime", {})
    dataset = summary.get("dataset", {})
    if runtime.get("commit") != WAYMAX_COMMIT:
        raise ValueError("retained Waymax commit does not match the protocol")
    if dataset.get("sha256") != WAYMAX_DATA_SHA256:
        raise ValueError("retained Waymax data hash does not match the protocol")
    if summary.get("implementation_sha256") != _implementation_hashes():
        raise ValueError("retained Waymax evidence was produced by different study code")

    scenario_info = summary.get("scenario_results", {})
    scenario_path = root / str(scenario_info.get("path", ""))
    scenario_sha256 = _sha256_file(scenario_path)
    if scenario_sha256 != scenario_info.get("sha256"):
        raise ValueError("Waymax scenario results do not match the summary hash")
    if scenario_sha256 != manifest.get("scenario_results_sha256"):
        raise ValueError("Waymax scenario results do not match the manifest hash")
    if _sha256_file(summary_path) != manifest.get("results_summary_sha256"):
        raise ValueError("Waymax summary does not match the manifest hash")

    rows = [
        json.loads(line)
        for line in scenario_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    recomputed = summarize_scenario_rows(rows)
    if recomputed != summary.get("behavior"):
        raise ValueError("Waymax aggregate does not reproduce from scenario rows")
    return {**summary, "available": True}


def _run_scenario(
    *,
    scenario_index: int,
    scenario: Any,
    environment: Any,
    metric_fn: Any,
    waymax: Mapping[str, Any],
) -> dict[str, Any]:
    initial_state = environment.reset(scenario)
    fingerprint = _scenario_fingerprint(initial_state)
    initial_route = _select_route(initial_state)
    if initial_route is None:
        diagnostics = _contract_diagnostics(
            session_uuid=f"waymax-{scenario_index:02d}",
            route_source="missing",
            route_waypoint_count=0,
            timestamp_us=_state_timestamp_us(initial_state),
        )
        return {
            "scenario_index": scenario_index,
            "scenario_fingerprint": fingerprint,
            "eligible": False,
            "exclusion_reason": "no valid sdc_paths.on_route geometry",
            "contract_diagnostics": diagnostics,
        }

    arms = {
        policy: {
            route_condition: _run_arm(
                scenario=scenario,
                scenario_index=scenario_index,
                policy=policy,
                route_condition=route_condition,
                environment=environment,
                metric_fn=metric_fn,
                waymax=waymax,
            )
            for route_condition in ROUTE_CONDITIONS
        }
        for policy in POLICIES
    }
    contrasts = {
        policy: _policy_contrast(arms[policy]["full_route"], arms[policy]["command_proxy"])
        for policy in POLICIES
    }
    if (
        contrasts["constant_velocity"]["endpoint_difference_m"]
        > NEGATIVE_CONTROL_INVARIANCE_TOLERANCE_M
    ):
        raise ValueError(
            f"scenario {scenario_index} violates the negative-control invariant"
        )
    return {
        "scenario_index": scenario_index,
        "scenario_fingerprint": fingerprint,
        "eligible": True,
        "difference_in_differences_endpoint_m": round(
            contrasts["route_following"]["endpoint_difference_m"]
            - contrasts["constant_velocity"]["endpoint_difference_m"],
            6,
        ),
        "contrasts": contrasts,
        "arms": arms,
    }


def _run_arm(
    *,
    scenario: Any,
    scenario_index: int,
    policy: str,
    route_condition: str,
    environment: Any,
    metric_fn: Any,
    waymax: Mapping[str, Any],
) -> dict[str, Any]:
    state = environment.reset(scenario)
    sdc_index = _sdc_index(state)
    start_xy = np.asarray(state.current_sim_trajectory.xy)[sdc_index, 0].astype(
        np.float64
    )
    position_trace = [start_xy.copy()]
    route_distances = [_route_distance(state)]
    route_source = (
        "womd_sdc_path" if route_condition == "full_route" else "command_proxy"
    )
    initial_route = _select_route(state)
    if route_condition == "full_route" and initial_route is None:
        raise ValueError(
            f"scenario {scenario_index} has no route geometry for {policy}/{route_condition}"
        )
    current = state.current_sim_trajectory
    received_route = (
        initial_route
        if route_condition == "full_route"
        else _command_proxy_route(
            x=float(current.x[sdc_index, 0]),
            y=float(current.y[sdc_index, 0]),
            yaw=float(current.yaw[sdc_index, 0]),
        )
    )
    if received_route is None:
        raise ValueError(f"scenario {scenario_index} has no received route representation")
    route_waypoint_count = int(received_route.xy.shape[0])
    contract_diagnostics = _contract_diagnostics(
        session_uuid=f"waymax-{scenario_index:02d}-{policy}-{route_condition}",
        route_source=route_source,
        route_waypoint_count=route_waypoint_count,
        timestamp_us=_state_timestamp_us(state),
        route_geometry_required=policy == "route_following",
    )
    all_plans_finite = True
    for _ in range(ROLLOUT_STEPS):
        trajectory = _plan_trajectory(
            state,
            policy=policy,
            route_condition=route_condition,
        )
        all_plans_finite = all_plans_finite and bool(np.isfinite(trajectory).all())
        state = environment.step(
            state,
            _trajectory_action(
                state,
                trajectory=trajectory,
                datatypes=waymax["datatypes"],
                jnp=waymax["jnp"],
            ),
        )
        position_trace.append(
            np.asarray(state.current_sim_trajectory.xy)[sdc_index, 0].astype(np.float64)
        )
        route_distances.append(_route_distance(state))
    if not all_plans_finite:
        raise ValueError(
            f"scenario {scenario_index} {policy}/{route_condition} produced a non-finite plan"
        )

    metric_results = metric_fn(state)
    waymax["jax"].tree_util.tree_map(_block_until_ready, metric_results)
    endpoint_xy = np.asarray(state.current_sim_trajectory.xy)[sdc_index, 0].astype(
        np.float64
    )
    return {
        "endpoint_xy": [round(float(value), 6) for value in endpoint_xy],
        "final_heading_rad": round(
            float(state.current_sim_trajectory.yaw[sdc_index, 0]), 6
        ),
        "position_trace_xy": [
            [round(float(value), 6) for value in position] for position in position_trace
        ],
        "distance_traveled_endpoint_m": round(
            float(np.linalg.norm(endpoint_xy - start_xy)), 6
        ),
        "mean_route_distance_m": round(float(np.mean(route_distances)), 6),
        "max_route_distance_m": round(float(np.max(route_distances)), 6),
        "trajectory_plans": ROLLOUT_STEPS,
        "finite_trajectory_plans": ROLLOUT_STEPS,
        "policy_input_contract": {
            "route_source": route_source,
            "route_waypoint_count": route_waypoint_count,
            "route_geometry_required": policy == "route_following",
            "command_proxy_intent": (
                COMMAND_PROXY_INTENT if route_condition == "command_proxy" else None
            ),
        },
        "final_metrics": _extract_sdc_metrics(metric_results, sdc_index),
        "contract_diagnostics": contract_diagnostics,
    }


def _plan_trajectory(
    state: Any,
    *,
    policy: str,
    route_condition: str,
) -> np.ndarray:
    if policy not in POLICIES:
        raise ValueError(f"unsupported policy: {policy}")
    if route_condition not in ROUTE_CONDITIONS:
        raise ValueError(f"unsupported route condition: {route_condition}")
    sdc_index = _sdc_index(state)
    current = state.current_sim_trajectory
    x = float(current.x[sdc_index, 0])
    y = float(current.y[sdc_index, 0])
    yaw = float(current.yaw[sdc_index, 0])
    speed_mps = math.hypot(
        float(current.vel_x[sdc_index, 0]),
        float(current.vel_y[sdc_index, 0]),
    )
    route_representation = (
        _select_route(state)
        if route_condition == "full_route"
        else _command_proxy_route(x=x, y=y, yaw=yaw)
    )
    if route_representation is None:
        raise ValueError("adapter has no route representation")
    route = route_representation if policy == "route_following" else None
    points: list[tuple[float, float]] = []
    for _ in range(OUTPUT_FUTURE_POINTS):
        x, y, yaw = advance_pose(
            x=x,
            y=y,
            yaw=yaw,
            speed_mps=speed_mps,
            route=route,
        )
        points.append((x, y))
    return np.asarray(points, dtype=np.float32)


def _policy_contrast(
    full_route: Mapping[str, Any],
    command_proxy: Mapping[str, Any],
) -> dict[str, Any]:
    full_trace = np.asarray(full_route["position_trace_xy"], dtype=np.float64)
    proxy_trace = np.asarray(command_proxy["position_trace_xy"], dtype=np.float64)
    if full_trace.shape != (ROLLOUT_STEPS + 1, 2) or proxy_trace.shape != full_trace.shape:
        raise ValueError("policy contrast received an invalid position trace")
    displacement = np.linalg.norm(full_trace - proxy_trace, axis=-1)
    heading_delta = float(full_route["final_heading_rad"]) - float(
        command_proxy["final_heading_rad"]
    )
    heading_difference = abs(math.atan2(math.sin(heading_delta), math.cos(heading_delta)))
    return {
        "endpoint_difference_m": round(float(displacement[-1]), 6),
        "mean_displacement_divergence_m": round(float(np.mean(displacement)), 6),
        "final_heading_difference_rad": round(heading_difference, 6),
        "displacement_divergence_over_time_m": [
            round(float(value), 6) for value in displacement
        ],
    }


def _command_proxy_route(*, x: float, y: float, yaw: float) -> RoutePath:
    arc_length = np.linspace(0.0, 200.0, 201, dtype=np.float64)
    direction = np.asarray([math.cos(yaw), math.sin(yaw)], dtype=np.float64)
    xy = np.asarray([x, y], dtype=np.float64) + arc_length[:, np.newaxis] * direction
    return RoutePath(xy=xy, arc_length=arc_length)


def advance_pose(
    *,
    x: float,
    y: float,
    yaw: float,
    speed_mps: float,
    route: RoutePath | None,
) -> tuple[float, float, float]:
    if speed_mps < 1e-3:
        return x, y, yaw
    step_distance = speed_mps * STEP_SECONDS
    if route is None:
        return (
            x + step_distance * math.cos(yaw),
            y + step_distance * math.sin(yaw),
            yaw,
        )

    position = np.asarray([x, y], dtype=np.float64)
    nearest_index = int(np.argmin(np.linalg.norm(route.xy - position, axis=-1)))
    target_arc = float(route.arc_length[nearest_index]) + max(
        MIN_ROUTE_LOOKAHEAD_M,
        speed_mps * ROUTE_LOOKAHEAD_SECONDS,
    )
    target_index = min(
        int(np.searchsorted(route.arc_length, target_arc, side="left")),
        len(route.arc_length) - 1,
    )
    direction = route.xy[target_index].astype(np.float64) - position
    norm = float(np.linalg.norm(direction))
    if norm < 1e-6:
        return (
            x + step_distance * math.cos(yaw),
            y + step_distance * math.sin(yaw),
            yaw,
        )
    direction /= norm
    next_yaw = math.atan2(float(direction[1]), float(direction[0]))
    return (
        x + step_distance * float(direction[0]),
        y + step_distance * float(direction[1]),
        next_yaw,
    )


def _trajectory_action(
    state: Any,
    *,
    trajectory: np.ndarray,
    datatypes: Any,
    jnp: Any,
) -> Any:
    if trajectory.shape != (OUTPUT_FUTURE_POINTS, 2):
        raise ValueError(f"unexpected planned trajectory shape: {trajectory.shape}")
    sdc_index = _sdc_index(state)
    current = state.current_sim_trajectory
    speed_mps = math.hypot(
        float(current.vel_x[sdc_index, 0]),
        float(current.vel_y[sdc_index, 0]),
    )
    delta = trajectory[0] - np.asarray(
        [float(current.x[sdc_index, 0]), float(current.y[sdc_index, 0])],
        dtype=np.float32,
    )
    yaw = (
        math.atan2(float(delta[1]), float(delta[0]))
        if float(np.linalg.norm(delta)) > 1e-6
        else float(current.yaw[sdc_index, 0])
    )
    num_objects = int(state.log_trajectory.num_objects)
    action_data = np.zeros((num_objects, 5), dtype=np.float32)
    action_valid = np.zeros((num_objects, 1), dtype=bool)
    action_data[sdc_index] = (
        float(trajectory[0, 0]),
        float(trajectory[0, 1]),
        yaw,
        speed_mps * math.cos(yaw),
        speed_mps * math.sin(yaw),
    )
    action_valid[sdc_index, 0] = True
    return datatypes.Action(
        data=jnp.asarray(action_data),
        valid=jnp.asarray(action_valid),
    )


def _select_route(state: Any) -> RoutePath | None:
    paths = state.sdc_paths
    if paths is None:
        return None
    sdc_index = _sdc_index(state)
    current_xy = np.asarray(state.current_sim_trajectory.xy)[sdc_index, 0]
    xy = np.asarray(paths.xy)
    valid = np.asarray(paths.valid, dtype=bool)
    on_route = np.asarray(paths.on_route, dtype=bool)[..., 0]
    distances = np.linalg.norm(xy - current_xy, axis=-1)
    distances = np.where(valid & on_route[:, np.newaxis], distances, np.inf)
    if not bool(np.isfinite(distances).any()):
        return None
    path_index = int(np.unravel_index(np.argmin(distances), distances.shape)[0])
    valid_indices = np.flatnonzero(valid[path_index])
    if valid_indices.size < 2:
        return None
    return RoutePath(
        xy=xy[path_index, valid_indices].astype(np.float64),
        arc_length=np.asarray(paths.arc_length)[path_index, valid_indices].astype(
            np.float64
        ),
    )


def _route_distance(state: Any) -> float:
    route = _select_route(state)
    if route is None:
        raise ValueError("comparison-eligible scenario lost its on-route path")
    sdc_index = _sdc_index(state)
    current_xy = np.asarray(state.current_sim_trajectory.xy)[sdc_index, 0]
    return float(np.min(np.linalg.norm(route.xy - current_xy, axis=-1)))


def _contract_diagnostics(
    *,
    session_uuid: str,
    route_source: str,
    route_waypoint_count: int,
    timestamp_us: int,
    route_geometry_required: bool = True,
) -> list[str]:
    common = {"schema": TELEMETRY_SCHEMA, "session_uuid": session_uuid}
    events = [
        {**common, "event": "start_session"},
        {
            **common,
            "event": "observation",
            "timestamp_us": timestamp_us,
            "observation_kind": "waymax_simulator_state",
        },
        {
            **common,
            "event": "route",
            "route_source": route_source,
            "route_waypoint_count": route_waypoint_count,
            "route_geometry_required": route_geometry_required,
        },
    ]
    if route_source != "missing":
        events.append(
            {
                **common,
                "event": "drive",
                "time_now_us": timestamp_us,
                "route_source": route_source,
                "route_waypoint_count": route_waypoint_count,
                "route_geometry_required": route_geometry_required,
                "trajectory_points": OUTPUT_FUTURE_POINTS + 1,
                "trajectory_future_points": OUTPUT_FUTURE_POINTS,
                "trajectory_expected_future_points": OUTPUT_FUTURE_POINTS,
                "trajectory_includes_current_pose": True,
                "trajectory_finite": True,
            }
        )
    events.append({**common, "event": "close_session"})
    return [
        diagnostic.code
        for diagnostic in diagnose_contract_trace(events, context=DEFAULT_CONTEXT)
    ]


def _extract_sdc_metrics(metric_results: Mapping[str, Any], sdc_index: int) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for name in METRIC_NAMES:
        result = metric_results[name]
        values = np.asarray(result.value)
        valids = np.asarray(result.valid)
        if values.ndim == 0:
            value = float(values)
            valid = bool(valids)
        else:
            value = float(values[sdc_index])
            valid = bool(valids[sdc_index])
        if not valid or not math.isfinite(value):
            raise ValueError(f"Waymax metric {name} is invalid for the SDC")
        metrics[name] = round(value, 6)
    return metrics


def _summarize_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        name: {
            "mean": _rounded_mean([_finite_float(row[name]) for row in rows]),
            "positive_count": sum(_finite_float(row[name]) > 0.0 for row in rows),
        }
        for name in METRIC_NAMES
    }


def _summarize_endpoint_differences(values: Sequence[float]) -> dict[str, Any]:
    return {
        "mean": _rounded_mean(values),
        "median": _rounded_median(values),
        "max": round(max(values), 6),
        "changed_count": sum(value > ENDPOINT_CHANGE_THRESHOLD_M for value in values),
        "material_change_count": sum(
            value > MATERIAL_ENDPOINT_CHANGE_THRESHOLD_M for value in values
        ),
    }


def _arm_diagnostic_count(
    rows: Sequence[Mapping[str, Any]],
    policy: str,
    route_condition: str,
    expected: Sequence[str],
) -> int:
    expected_codes = list(expected)
    return sum(
        list(row["arms"][policy][route_condition]["contract_diagnostics"])
        == expected_codes
        for row in rows
    )


def _scenario_fingerprint(state: Any) -> str:
    hasher = hashlib.sha256()
    for array in (
        state.object_metadata.ids,
        state.object_metadata.is_sdc,
        state.log_trajectory.xy,
        state.log_trajectory.valid,
        state.sdc_paths.xy,
        state.sdc_paths.valid,
        state.sdc_paths.on_route,
    ):
        contiguous = np.ascontiguousarray(np.asarray(array))
        hasher.update(str(contiguous.dtype).encode("ascii"))
        hasher.update(str(contiguous.shape).encode("ascii"))
        hasher.update(contiguous.tobytes())
    return hasher.hexdigest()


def _state_timestamp_us(state: Any) -> int:
    sdc_index = _sdc_index(state)
    return int(np.asarray(state.current_sim_trajectory.timestamp_micros)[sdc_index, 0])


def _sdc_index(state: Any) -> int:
    indices = np.flatnonzero(np.asarray(state.object_metadata.is_sdc, dtype=bool))
    if indices.size != 1:
        raise ValueError(f"expected exactly one SDC, found {indices.size}")
    return int(indices[0])


def _verify_waymax_checkout(root: Path) -> None:
    if not (root / ".git").exists():
        raise ValueError(f"Waymax checkout has no .git directory: {root}")
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != WAYMAX_COMMIT:
        raise ValueError(f"Waymax checkout must be at {WAYMAX_COMMIT}; found {commit}")
    data_path = root / WAYMAX_DATA_RELATIVE_PATH
    if not data_path.is_file():
        raise ValueError(f"Waymax WOMD fixture is missing: {data_path}")


def _import_waymax(root: Path) -> dict[str, Any]:
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    import jax
    import jax.numpy as jnp
    import jaxlib
    import tensorflow
    import waymax
    from waymax import config, dataloader, datatypes, dynamics, env

    imported = Path(waymax.__file__).resolve()
    if root.resolve() not in imported.parents:
        raise ValueError(f"imported Waymax from {imported}, not pinned checkout {root}")
    return {
        "config": config,
        "dataloader": dataloader,
        "datatypes": datatypes,
        "dynamics": dynamics,
        "env": env,
        "jax": jax,
        "jaxlib": jaxlib,
        "jnp": jnp,
        "tensorflow": tensorflow,
    }


def _implementation_hashes() -> dict[str, str]:
    repository_root = Path(__file__).resolve().parents[3]
    paths = (
        Path("src/wod2sim/experiments/waymax_contract_study.py"),
        Path("src/wod2sim/audit/trace_diagnostics.py"),
        Path("scripts/run_waymax_contract_study.sh"),
    )
    return {
        str(path): _sha256_file(repository_root / path)
        for path in paths
        if (repository_root / path).is_file()
    }


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _block_until_ready(value: Any) -> Any:
    return value.block_until_ready() if hasattr(value, "block_until_ready") else value


def _finite_float(value: Any) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"expected finite value, got {value!r}")
    return parsed


def _rounded_mean(values: Sequence[float]) -> float:
    return round(float(np.mean(np.asarray(values, dtype=np.float64))), 6)


def _rounded_median(values: Sequence[float]) -> float:
    return round(float(np.median(np.asarray(values, dtype=np.float64))), 6)


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    raise SystemExit(main())
