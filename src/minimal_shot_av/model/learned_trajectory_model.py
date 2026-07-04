from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .rfs_metric import Trajectory
from .wod_e2e import WodE2EPreferenceFrame


PAST_WAYPOINTS = 16
FUTURE_WAYPOINTS = 20
BASE_FEATURE_DIM = PAST_WAYPOINTS * 4 + 6
TEMPORAL_SUMMARY_DIM = 24
FEATURE_DIM = BASE_FEATURE_DIM
OUTPUT_DIM = FUTURE_WAYPOINTS * 2
FEATURE_SET_BASE = "base"
FEATURE_SET_TEMPORAL = "temporal_summary"
FEATURE_SET_EXTERNAL_EMBEDDINGS = "external_embeddings"
RESIDUAL_GROUP_OFF = "off"
RESIDUAL_GROUP_INTENT = "intent"
RESIDUAL_GROUP_SPEED = "speed"
RESIDUAL_GROUP_INTENT_SPEED = "intent_speed"
RESIDUAL_GROUPINGS = {
    RESIDUAL_GROUP_OFF,
    RESIDUAL_GROUP_INTENT,
    RESIDUAL_GROUP_SPEED,
    RESIDUAL_GROUP_INTENT_SPEED,
}


@dataclass(frozen=True)
class RidgeTrajectoryModel:
    feature_mean: list[float]
    feature_scale: list[float]
    weights: list[list[float]]
    bias: list[float]
    residual_modes: list[list[float]]
    residual_scales: list[float]
    ridge: float
    train_rows: int
    feature_set: str = FEATURE_SET_BASE
    external_embedding_dimension: int = 0
    residual_grouping: str = RESIDUAL_GROUP_OFF
    residual_groups: dict[str, dict[str, object]] | None = None

    def predict(
        self,
        past_trajectory: Sequence[tuple[float, float]],
        *,
        intent: int,
        init_speed_mps: float,
    ) -> Trajectory:
        features = _normalized_feature_matrix(
            [
                _frame_features(
                    past_trajectory,
                    intent=intent,
                    init_speed_mps=init_speed_mps,
                    feature_set=self.feature_set,
                    external_embedding=[0.0 for _ in range(self.external_embedding_dimension)],
                )
            ],
            self.feature_mean,
            self.feature_scale,
        )
        output = np.asarray(self.bias, dtype=np.float64) + features[0] @ np.asarray(self.weights, dtype=np.float64)
        return _trajectory_from_output(output)

    def predict_frame(self, frame: WodE2EPreferenceFrame) -> Trajectory:
        features = _normalized_feature_matrix(
            [
                _frame_features(
                    frame.past_trajectory,
                    intent=frame.intent,
                    init_speed_mps=frame.init_speed_mps,
                    feature_set=self.feature_set,
                    external_embedding=frame.external_embedding,
                )
            ],
            self.feature_mean,
            self.feature_scale,
        )
        output = np.asarray(self.bias, dtype=np.float64) + features[0] @ np.asarray(self.weights, dtype=np.float64)
        return _trajectory_from_output(output)

    def candidate_trajectories(
        self,
        past_trajectory: Sequence[tuple[float, float]],
        *,
        intent: int,
        init_speed_mps: float,
        max_residual_modes: int = 3,
        include_pairwise_residuals: bool = False,
    ) -> list[tuple[str, Trajectory]]:
        mean_output = _output_from_trajectory(
            self.predict(past_trajectory, intent=intent, init_speed_mps=init_speed_mps)
        )
        candidates = [("ridge_mean", _trajectory_from_output(mean_output))]
        mode_vectors: list[np.ndarray] = []
        for mode_index, (mode, scale) in enumerate(zip(self.residual_modes, self.residual_scales)):
            if mode_index >= max_residual_modes:
                break
            mode_vector = np.asarray(mode, dtype=np.float64) * float(scale)
            mode_vectors.append(mode_vector)
            candidates.append(
                (f"ridge_residual_pc{mode_index + 1}_plus", _trajectory_from_output(mean_output + mode_vector))
            )
            candidates.append(
                (f"ridge_residual_pc{mode_index + 1}_minus", _trajectory_from_output(mean_output - mode_vector))
            )
        if include_pairwise_residuals and len(mode_vectors) >= 2:
            for left_index in range(len(mode_vectors)):
                for right_index in range(left_index + 1, len(mode_vectors)):
                    combined = mode_vectors[left_index] + mode_vectors[right_index]
                    candidates.append(
                        (
                            f"ridge_residual_pc{left_index + 1}_{right_index + 1}_plus",
                            _trajectory_from_output(mean_output + combined),
                        )
                    )
                    candidates.append(
                        (
                            f"ridge_residual_pc{left_index + 1}_{right_index + 1}_minus",
                            _trajectory_from_output(mean_output - combined),
                        )
                    )
        candidates.extend(
            self._context_residual_candidates(
                mean_output,
                intent=intent,
                init_speed_mps=init_speed_mps,
                max_residual_modes=max_residual_modes,
            )
        )
        return candidates

    def candidate_trajectories_for_frame(
        self,
        frame: WodE2EPreferenceFrame,
        *,
        max_residual_modes: int = 3,
        include_pairwise_residuals: bool = False,
    ) -> list[tuple[str, Trajectory]]:
        if self.feature_set != FEATURE_SET_EXTERNAL_EMBEDDINGS:
            return self.candidate_trajectories(
                frame.past_trajectory,
                intent=frame.intent,
                init_speed_mps=frame.init_speed_mps,
                max_residual_modes=max_residual_modes,
                include_pairwise_residuals=include_pairwise_residuals,
            )
        mean_output = _output_from_trajectory(self.predict_frame(frame))
        candidates = [("ridge_scene_mean", _trajectory_from_output(mean_output))]
        mode_vectors: list[np.ndarray] = []
        for mode_index, (mode, scale) in enumerate(zip(self.residual_modes, self.residual_scales)):
            if mode_index >= max_residual_modes:
                break
            mode_vector = np.asarray(mode, dtype=np.float64) * float(scale)
            mode_vectors.append(mode_vector)
            candidates.append(
                (f"ridge_scene_residual_pc{mode_index + 1}_plus", _trajectory_from_output(mean_output + mode_vector))
            )
            candidates.append(
                (f"ridge_scene_residual_pc{mode_index + 1}_minus", _trajectory_from_output(mean_output - mode_vector))
            )
        if include_pairwise_residuals and len(mode_vectors) >= 2:
            for left_index in range(len(mode_vectors)):
                for right_index in range(left_index + 1, len(mode_vectors)):
                    combined = mode_vectors[left_index] + mode_vectors[right_index]
                    candidates.append(
                        (
                            f"ridge_scene_residual_pc{left_index + 1}_{right_index + 1}_plus",
                            _trajectory_from_output(mean_output + combined),
                        )
                    )
                    candidates.append(
                        (
                            f"ridge_scene_residual_pc{left_index + 1}_{right_index + 1}_minus",
                            _trajectory_from_output(mean_output - combined),
                        )
                    )
        candidates.extend(
            self._context_residual_candidates(
                mean_output,
                intent=frame.intent,
                init_speed_mps=frame.init_speed_mps,
                max_residual_modes=max_residual_modes,
            )
        )
        return candidates

    def _context_residual_candidates(
        self,
        mean_output: np.ndarray,
        *,
        intent: int,
        init_speed_mps: float,
        max_residual_modes: int,
    ) -> list[tuple[str, Trajectory]]:
        if self.residual_grouping == RESIDUAL_GROUP_OFF or not self.residual_groups:
            return []
        key = _residual_group_key(
            self.residual_grouping,
            intent=intent,
            init_speed_mps=init_speed_mps,
        )
        group = self.residual_groups.get(key)
        if group is None:
            return []
        offset = np.asarray(group["offset"], dtype=np.float64)
        candidates = [
            (
                f"context_residual_{_safe_candidate_key(key)}_mean",
                _trajectory_from_output(mean_output + offset),
            )
        ]
        modes = group.get("modes", [])
        scales = group.get("scales", [])
        for mode_index, (mode, scale) in enumerate(zip(modes, scales)):
            if mode_index >= max_residual_modes:
                break
            mode_vector = np.asarray(mode, dtype=np.float64) * float(scale)
            candidates.append(
                (
                    f"context_residual_{_safe_candidate_key(key)}_pc{mode_index + 1}_plus",
                    _trajectory_from_output(mean_output + offset + mode_vector),
                )
            )
            candidates.append(
                (
                    f"context_residual_{_safe_candidate_key(key)}_pc{mode_index + 1}_minus",
                    _trajectory_from_output(mean_output + offset - mode_vector),
                )
            )
        return candidates

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_type": "ridge_trajectory_model_v1",
            "past_waypoints": PAST_WAYPOINTS,
            "future_waypoints": FUTURE_WAYPOINTS,
            "feature_dim": len(self.feature_mean),
            "feature_set": self.feature_set,
            "external_embedding_dimension": self.external_embedding_dimension,
            "output_dim": OUTPUT_DIM,
            "feature_mean": self.feature_mean,
            "feature_scale": self.feature_scale,
            "weights": self.weights,
            "bias": self.bias,
            "residual_modes": self.residual_modes,
            "residual_scales": self.residual_scales,
            "residual_grouping": self.residual_grouping,
            "residual_groups": self.residual_groups or {},
            "ridge": self.ridge,
            "train_rows": self.train_rows,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RidgeTrajectoryModel":
        if payload.get("model_type") != "ridge_trajectory_model_v1":
            raise ValueError(f"unsupported trajectory model type: {payload.get('model_type')!r}")
        feature_set = str(payload.get("feature_set", FEATURE_SET_BASE))
        _validate_feature_set(feature_set)
        residual_grouping = str(payload.get("residual_grouping", RESIDUAL_GROUP_OFF))
        _validate_residual_grouping(residual_grouping)
        return cls(
            feature_mean=[float(value) for value in payload["feature_mean"]],
            feature_scale=[float(value) for value in payload["feature_scale"]],
            weights=[[float(value) for value in row] for row in payload["weights"]],
            bias=[float(value) for value in payload["bias"]],
            residual_modes=[[float(value) for value in row] for row in payload.get("residual_modes", [])],
            residual_scales=[float(value) for value in payload.get("residual_scales", [])],
            residual_grouping=residual_grouping,
            residual_groups=_residual_groups_from_payload(payload.get("residual_groups", {})),
            ridge=float(payload["ridge"]),
            train_rows=int(payload["train_rows"]),
            feature_set=feature_set,
            external_embedding_dimension=int(payload.get("external_embedding_dimension", 0)),
        )

    @classmethod
    def load(cls, path: str | Path) -> "RidgeTrajectoryModel":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fit_ridge_trajectory_model(
    frames: Iterable[WodE2EPreferenceFrame],
    *,
    ridge: float = 30.0,
    residual_modes: int = 3,
    feature_set: str = FEATURE_SET_BASE,
    residual_grouping: str = RESIDUAL_GROUP_OFF,
) -> RidgeTrajectoryModel:
    _validate_feature_set(feature_set)
    _validate_residual_grouping(residual_grouping)
    rows = [frame for frame in frames if len(frame.future_trajectory) == FUTURE_WAYPOINTS]
    if not rows:
        raise ValueError("no frames with 20-waypoint future trajectories")
    external_embedding_dimension = (
        _external_embedding_dimension(rows)
        if feature_set == FEATURE_SET_EXTERNAL_EMBEDDINGS
        else 0
    )
    x = np.asarray(
        [
            _frame_features(
                frame.past_trajectory,
                intent=frame.intent,
                init_speed_mps=frame.init_speed_mps,
                feature_set=feature_set,
                external_embedding=frame.external_embedding,
            )
            for frame in rows
        ],
        dtype=np.float64,
    )
    y = np.asarray([_output_from_trajectory(frame.future_trajectory) for frame in rows], dtype=np.float64)
    feature_mean = x.mean(axis=0)
    feature_scale = x.std(axis=0)
    feature_scale[feature_scale < 1e-8] = 1.0
    x_norm = (x - feature_mean) / feature_scale
    design = np.concatenate([np.ones((x_norm.shape[0], 1)), x_norm], axis=1)
    penalty = np.eye(design.shape[1], dtype=np.float64) * float(ridge)
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    predictions = design @ coefficients
    residuals = y - predictions
    modes, scales = _residual_modes(residuals, residual_modes)
    residual_groups = _fit_residual_groups(rows, residuals, residual_modes, grouping=residual_grouping)
    return RidgeTrajectoryModel(
        feature_mean=feature_mean.tolist(),
        feature_scale=feature_scale.tolist(),
        weights=coefficients[1:].tolist(),
        bias=coefficients[0].tolist(),
        residual_modes=modes,
        residual_scales=scales,
        residual_grouping=residual_grouping,
        residual_groups=residual_groups,
        ridge=float(ridge),
        train_rows=len(rows),
        feature_set=feature_set,
        external_embedding_dimension=external_embedding_dimension,
    )


def learned_candidate_payloads(
    frames: Iterable[WodE2EPreferenceFrame],
    model: RidgeTrajectoryModel,
    *,
    source: str = "wod_ridge_trajectory_non_text",
    max_residual_modes: int = 3,
    include_pairwise_residuals: bool = False,
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for frame in frames:
        candidates = model.candidate_trajectories(
            frame.past_trajectory,
            intent=frame.intent,
            init_speed_mps=frame.init_speed_mps,
            max_residual_modes=max_residual_modes,
            include_pairwise_residuals=include_pairwise_residuals,
        )
        for candidate_index, (candidate_name, trajectory) in enumerate(candidates):
            payloads.append(
                {
                    "frame_name": frame.frame_name,
                    "source": source,
                    "candidate_name": candidate_name,
                    "candidate_index": candidate_index,
                    "trajectory_20wp_4hz": _json_trajectory(trajectory),
                }
            )
    return payloads


def write_learned_candidate_jsonl(
    frames: Iterable[WodE2EPreferenceFrame],
    path: str | Path,
    model: RidgeTrajectoryModel,
    *,
    source: str = "wod_ridge_trajectory_non_text",
    max_residual_modes: int = 3,
    include_pairwise_residuals: bool = False,
) -> int:
    count = 0
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as stream:
        for payload in learned_candidate_payloads(
            frames,
            model,
            source=source,
            max_residual_modes=max_residual_modes,
            include_pairwise_residuals=include_pairwise_residuals,
        ):
            stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
            count += 1
    return count


def _frame_features(
    past_trajectory: Sequence[tuple[float, float]],
    *,
    intent: int,
    init_speed_mps: float,
    feature_set: str = FEATURE_SET_BASE,
    external_embedding: Sequence[float] | None = None,
) -> list[float]:
    _validate_feature_set(feature_set)
    past = _pad_recent_points(past_trajectory, PAST_WAYPOINTS)
    deltas = [(0.0, 0.0)]
    deltas.extend(
        (past[index][0] - past[index - 1][0], past[index][1] - past[index - 1][1])
        for index in range(1, len(past))
    )
    intent_one_hot = [1.0 if int(intent) == value else 0.0 for value in (0, 1, 2, 3)]
    features = [
        *[coordinate for point in past for coordinate in point],
        *[coordinate for point in deltas for coordinate in point],
        float(init_speed_mps),
        1.0,
        *intent_one_hot,
    ]
    if feature_set == FEATURE_SET_TEMPORAL:
        features.extend(_temporal_summary_features(past))
    if feature_set == FEATURE_SET_EXTERNAL_EMBEDDINGS:
        features.extend(_temporal_summary_features(past))
        features.extend(_validated_external_embedding(external_embedding))
    return features


def _temporal_summary_features(past: Sequence[tuple[float, float]]) -> list[float]:
    points = [(float(x), float(y)) for x, y in past]
    intervals = [
        (points[index][0] - points[index - 1][0], points[index][1] - points[index - 1][1])
        for index in range(1, len(points))
    ]
    speeds = np.asarray([float(np.hypot(dx, dy) * 4.0) for dx, dy in intervals], dtype=np.float64)
    accelerations = np.diff(speeds) * 4.0 if len(speeds) >= 2 else np.asarray([0.0], dtype=np.float64)
    headings = _interval_headings(intervals)
    heading_deltas = _wrapped_diffs(headings)
    recent_speeds = speeds[-4:] if len(speeds) >= 4 else speeds
    recent_accelerations = accelerations[-4:] if len(accelerations) >= 4 else accelerations
    recent_heading_deltas = heading_deltas[-4:] if len(heading_deltas) >= 4 else heading_deltas
    displacement_x = points[-1][0] - points[0][0]
    displacement_y = points[-1][1] - points[0][1]
    displacement = float(np.hypot(displacement_x, displacement_y))
    final_heading = headings[-1] if len(headings) else 0.0
    return [
        _safe_mean(speeds),
        _safe_std(speeds),
        _safe_min(speeds),
        _safe_max(speeds),
        _safe_mean(recent_speeds),
        float(speeds[-1]) if len(speeds) else 0.0,
        _safe_mean(accelerations),
        _safe_std(accelerations),
        _safe_mean(recent_accelerations),
        float(accelerations[-1]) if len(accelerations) else 0.0,
        displacement_x,
        displacement_y,
        displacement,
        float(points[-1][1]),
        float(max(y for _, y in points) - min(y for _, y in points)),
        float(np.sin(final_heading)),
        float(np.cos(final_heading)),
        _safe_mean(heading_deltas),
        _safe_std(heading_deltas),
        _safe_mean(recent_heading_deltas),
        float(np.sum(np.abs(heading_deltas))) if len(heading_deltas) else 0.0,
        float(np.sum(np.abs(recent_heading_deltas))) if len(recent_heading_deltas) else 0.0,
        float(np.mean(speeds < 0.5)) if len(speeds) else 1.0,
        float(np.mean(np.abs([point[1] for point in points]) > 0.5)),
    ]


def _interval_headings(intervals: Sequence[tuple[float, float]]) -> np.ndarray:
    headings: list[float] = []
    last_heading = 0.0
    for dx, dy in intervals:
        if abs(dx) > 1e-8 or abs(dy) > 1e-8:
            last_heading = float(np.arctan2(dy, dx))
        headings.append(last_heading)
    return np.asarray(headings, dtype=np.float64)


def _wrapped_diffs(values: np.ndarray) -> np.ndarray:
    if len(values) < 2:
        return np.asarray([0.0], dtype=np.float64)
    diffs = np.diff(values)
    return (diffs + np.pi) % (2.0 * np.pi) - np.pi


def _safe_mean(values: np.ndarray) -> float:
    return float(np.mean(values)) if len(values) else 0.0


def _safe_std(values: np.ndarray) -> float:
    return float(np.std(values)) if len(values) else 0.0


def _safe_min(values: np.ndarray) -> float:
    return float(np.min(values)) if len(values) else 0.0


def _safe_max(values: np.ndarray) -> float:
    return float(np.max(values)) if len(values) else 0.0


def _validate_feature_set(feature_set: str) -> None:
    if feature_set not in {FEATURE_SET_BASE, FEATURE_SET_TEMPORAL, FEATURE_SET_EXTERNAL_EMBEDDINGS}:
        raise ValueError(f"unsupported trajectory feature set: {feature_set!r}")


def _validated_external_embedding(values: Sequence[float] | None) -> list[float]:
    if values is None:
        raise ValueError("external embedding trajectory features require attached frame embeddings")
    embedding = [float(value) for value in values]
    if not embedding:
        raise ValueError("external embedding trajectory features require non-empty embeddings")
    return embedding


def _external_embedding_dimension(frames: Sequence[WodE2EPreferenceFrame]) -> int:
    dimension: int | None = None
    for frame in frames:
        embedding = _validated_external_embedding(frame.external_embedding)
        if dimension is None:
            dimension = len(embedding)
        elif len(embedding) != dimension:
            raise ValueError("external embedding dimensions must be consistent")
    return int(dimension or 0)


def _pad_recent_points(
    trajectory: Sequence[tuple[float, float]],
    target_len: int,
) -> list[tuple[float, float]]:
    points = [(float(x), float(y)) for x, y in trajectory]
    if not points:
        points = [(0.0, 0.0)]
    if len(points) >= target_len:
        return points[-target_len:]
    return [points[0]] * (target_len - len(points)) + points


def _normalized_feature_matrix(
    rows: list[list[float]],
    mean: Sequence[float],
    scale: Sequence[float],
) -> np.ndarray:
    x = np.asarray(rows, dtype=np.float64)
    return (x - np.asarray(mean, dtype=np.float64)) / np.asarray(scale, dtype=np.float64)


def _output_from_trajectory(trajectory: Sequence[tuple[float, float]]) -> np.ndarray:
    if len(trajectory) != FUTURE_WAYPOINTS:
        raise ValueError(f"expected {FUTURE_WAYPOINTS} future waypoints")
    return np.asarray([coordinate for point in trajectory for coordinate in point], dtype=np.float64)


def _trajectory_from_output(output: Sequence[float]) -> Trajectory:
    values = [float(value) for value in output]
    if len(values) != OUTPUT_DIM:
        raise ValueError(f"expected {OUTPUT_DIM} trajectory output values")
    return [(values[index], values[index + 1]) for index in range(0, OUTPUT_DIM, 2)]


def _residual_modes(residuals: np.ndarray, count: int) -> tuple[list[list[float]], list[float]]:
    if count <= 0 or residuals.shape[0] < 2:
        return [], []
    _, singular_values, vt = np.linalg.svd(residuals, full_matrices=False)
    mode_count = min(count, len(singular_values), vt.shape[0])
    scales = (singular_values[:mode_count] / max(1.0, float(residuals.shape[0] - 1)) ** 0.5).tolist()
    return vt[:mode_count].tolist(), [float(scale) for scale in scales]


def _fit_residual_groups(
    frames: Sequence[WodE2EPreferenceFrame],
    residuals: np.ndarray,
    residual_modes: int,
    *,
    grouping: str,
) -> dict[str, dict[str, object]]:
    if grouping == RESIDUAL_GROUP_OFF:
        return {}
    groups: dict[str, list[int]] = {}
    for index, frame in enumerate(frames):
        key = _residual_group_key(
            grouping,
            intent=frame.intent,
            init_speed_mps=frame.init_speed_mps,
        )
        groups.setdefault(key, []).append(index)
    result: dict[str, dict[str, object]] = {}
    for key, indices in groups.items():
        group_residuals = residuals[np.asarray(indices, dtype=np.int64)]
        offset = group_residuals.mean(axis=0)
        centered = group_residuals - offset
        modes, scales = _residual_modes(centered, min(residual_modes, max(0, len(indices) - 1)))
        result[key] = {
            "offset": offset.tolist(),
            "modes": modes,
            "scales": scales,
            "train_rows": len(indices),
        }
    return result


def _residual_groups_from_payload(payload: object) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for key, group in dict(payload).items():
        group_payload = dict(group)
        result[str(key)] = {
            "offset": [float(value) for value in group_payload.get("offset", [])],
            "modes": [
                [float(value) for value in row]
                for row in group_payload.get("modes", [])
            ],
            "scales": [float(value) for value in group_payload.get("scales", [])],
            "train_rows": int(group_payload.get("train_rows", 0)),
        }
    return result


def _residual_group_key(grouping: str, *, intent: int, init_speed_mps: float) -> str:
    _validate_residual_grouping(grouping)
    intent_key = f"intent:{int(intent)}"
    speed_key = f"speed:{_speed_bin(init_speed_mps)}"
    if grouping == RESIDUAL_GROUP_INTENT:
        return intent_key
    if grouping == RESIDUAL_GROUP_SPEED:
        return speed_key
    if grouping == RESIDUAL_GROUP_INTENT_SPEED:
        return f"{intent_key}|{speed_key}"
    raise ValueError("residual group key is undefined for off grouping")


def _speed_bin(speed_mps: float) -> str:
    speed = float(speed_mps)
    if speed < 0.5:
        return "stopped_or_creep"
    if speed < 5.0:
        return "slow"
    if speed < 13.5:
        return "urban"
    return "fast"


def _safe_candidate_key(key: str) -> str:
    return key.replace(":", "_").replace("|", "_")


def _validate_residual_grouping(grouping: str) -> None:
    if grouping not in RESIDUAL_GROUPINGS:
        raise ValueError(f"unsupported residual grouping: {grouping!r}")


def _json_trajectory(trajectory: Trajectory) -> list[list[float]]:
    return [[round(float(x), 4), round(float(y), 4)] for x, y in trajectory]
