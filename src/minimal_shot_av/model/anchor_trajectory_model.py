from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .learned_trajectory_model import (
    FEATURE_DIM,
    FUTURE_WAYPOINTS,
    OUTPUT_DIM,
    _frame_features,
    _json_trajectory,
    _normalized_feature_matrix,
    _output_from_trajectory,
    _trajectory_from_output,
)
from .rfs_metric import Trajectory
from .wod_e2e import WodE2EPreferenceFrame


@dataclass(frozen=True)
class AnchorResidualTrajectoryModel:
    feature_mean: list[float]
    feature_scale: list[float]
    anchors: list[list[float]]
    anchor_feature_centers: list[list[float]]
    anchor_logit_weights: list[list[float]]
    anchor_logit_bias: list[float]
    residual_weights: list[list[list[float]]]
    residual_bias: list[list[float]]
    residual_modes: list[list[list[float]]]
    residual_scales: list[list[float]]
    ridge: float
    train_rows: int
    anchor_iterations: int
    seed: int

    def candidate_trajectories(
        self,
        past_trajectory: Sequence[tuple[float, float]],
        *,
        intent: int,
        init_speed_mps: float,
        top_k: int,
        residual_modes_per_anchor: int = 0,
    ) -> list[tuple[str, Trajectory, float]]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        features = _normalized_feature_matrix(
            [_frame_features(past_trajectory, intent=intent, init_speed_mps=init_speed_mps)],
            self.feature_mean,
            self.feature_scale,
        )[0]
        logits = np.asarray(self.anchor_logit_bias, dtype=np.float64) + features @ np.asarray(
            self.anchor_logit_weights,
            dtype=np.float64,
        )
        order = np.argsort(-logits)[: min(top_k, len(self.anchors))]
        candidates: list[tuple[str, Trajectory, float]] = []
        for rank, anchor_index in enumerate(order):
            anchor = np.asarray(self.anchors[int(anchor_index)], dtype=np.float64)
            weights = np.asarray(self.residual_weights[int(anchor_index)], dtype=np.float64)
            bias = np.asarray(self.residual_bias[int(anchor_index)], dtype=np.float64)
            output = anchor + bias + features @ weights
            confidence = float(logits[int(anchor_index)])
            candidates.append(
                (
                    f"anchor_residual_{int(anchor_index)}_rank{rank}",
                    _trajectory_from_output(output),
                    confidence,
                )
            )
            for mode_index, (mode, scale) in enumerate(
                zip(self.residual_modes[int(anchor_index)], self.residual_scales[int(anchor_index)])
            ):
                if mode_index >= residual_modes_per_anchor:
                    break
                mode_vector = np.asarray(mode, dtype=np.float64) * float(scale)
                for suffix, sign in (("plus", 1.0), ("minus", -1.0)):
                    candidates.append(
                        (
                            f"anchor_residual_{int(anchor_index)}_rank{rank}_pc{mode_index + 1}_{suffix}",
                            _trajectory_from_output(output + sign * mode_vector),
                            confidence,
                        )
                    )
        return candidates

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_type": "anchor_residual_trajectory_model_v1",
            "future_waypoints": FUTURE_WAYPOINTS,
            "feature_dim": FEATURE_DIM,
            "output_dim": OUTPUT_DIM,
            "feature_mean": self.feature_mean,
            "feature_scale": self.feature_scale,
            "anchors": self.anchors,
            "anchor_feature_centers": self.anchor_feature_centers,
            "anchor_logit_weights": self.anchor_logit_weights,
            "anchor_logit_bias": self.anchor_logit_bias,
            "residual_weights": self.residual_weights,
            "residual_bias": self.residual_bias,
            "residual_modes": self.residual_modes,
            "residual_scales": self.residual_scales,
            "ridge": self.ridge,
            "train_rows": self.train_rows,
            "anchor_iterations": self.anchor_iterations,
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AnchorResidualTrajectoryModel":
        if payload.get("model_type") != "anchor_residual_trajectory_model_v1":
            raise ValueError(f"unsupported trajectory model type: {payload.get('model_type')!r}")
        return cls(
            feature_mean=[float(value) for value in payload["feature_mean"]],
            feature_scale=[float(value) for value in payload["feature_scale"]],
            anchors=[[float(value) for value in row] for row in payload["anchors"]],
            anchor_feature_centers=[
                [float(value) for value in row] for row in payload["anchor_feature_centers"]
            ],
            anchor_logit_weights=[
                [float(value) for value in row] for row in payload["anchor_logit_weights"]
            ],
            anchor_logit_bias=[float(value) for value in payload["anchor_logit_bias"]],
            residual_weights=[
                [[float(value) for value in row] for row in matrix]
                for matrix in payload["residual_weights"]
            ],
            residual_bias=[[float(value) for value in row] for row in payload["residual_bias"]],
            residual_modes=[
                [[float(value) for value in row] for row in modes]
                for modes in payload.get("residual_modes", [])
            ],
            residual_scales=[
                [float(value) for value in scales] for scales in payload.get("residual_scales", [])
            ],
            ridge=float(payload["ridge"]),
            train_rows=int(payload["train_rows"]),
            anchor_iterations=int(payload["anchor_iterations"]),
            seed=int(payload["seed"]),
        )

    @classmethod
    def load(cls, path: str | Path) -> "AnchorResidualTrajectoryModel":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fit_anchor_residual_trajectory_model(
    frames: Iterable[WodE2EPreferenceFrame],
    *,
    anchor_count: int,
    ridge: float,
    anchor_iterations: int,
    seed: int,
    residual_modes_per_anchor: int = 0,
) -> AnchorResidualTrajectoryModel:
    rows = [frame for frame in frames if len(frame.future_trajectory) == FUTURE_WAYPOINTS]
    if not rows:
        raise ValueError("no frames with 20-waypoint future trajectories")
    if anchor_count <= 0:
        raise ValueError("anchor_count must be positive")
    if anchor_count > len(rows):
        raise ValueError("anchor_count cannot exceed number of training rows")

    x = np.asarray(
        [
            _frame_features(frame.past_trajectory, intent=frame.intent, init_speed_mps=frame.init_speed_mps)
            for frame in rows
        ],
        dtype=np.float64,
    )
    y = np.asarray([_output_from_trajectory(frame.future_trajectory) for frame in rows], dtype=np.float64)
    feature_mean = x.mean(axis=0)
    feature_scale = x.std(axis=0)
    feature_scale[feature_scale < 1e-8] = 1.0
    x_norm = (x - feature_mean) / feature_scale
    anchors, labels = _kmeans(y, anchor_count=anchor_count, iterations=anchor_iterations, seed=seed)
    anchor_logit_bias, anchor_logit_weights = _fit_anchor_logits(
        x_norm,
        labels,
        anchor_count=anchor_count,
        ridge=ridge,
    )
    residual_weights: list[list[list[float]]] = []
    residual_bias: list[list[float]] = []
    residual_modes: list[list[list[float]]] = []
    residual_scales: list[list[float]] = []
    anchor_feature_centers: list[list[float]] = []
    for anchor_index in range(anchor_count):
        mask = labels == anchor_index
        if not np.any(mask):
            anchor_feature_centers.append(np.zeros(FEATURE_DIM, dtype=np.float64).tolist())
            residual_weights.append(np.zeros((FEATURE_DIM, OUTPUT_DIM), dtype=np.float64).tolist())
            residual_bias.append(np.zeros(OUTPUT_DIM, dtype=np.float64).tolist())
            residual_modes.append([])
            residual_scales.append([])
            continue
        anchor_feature_centers.append(x_norm[mask].mean(axis=0).tolist())
        target_residuals = y[mask] - anchors[anchor_index]
        bias, weights = _fit_ridge_residual(x_norm[mask], target_residuals, ridge=ridge)
        residual_weights.append(weights.tolist())
        residual_bias.append(bias.tolist())
        predictions = bias + x_norm[mask] @ weights
        modes, scales = _residual_modes(
            target_residuals - predictions,
            max_modes=residual_modes_per_anchor,
        )
        residual_modes.append(modes)
        residual_scales.append(scales)
    return AnchorResidualTrajectoryModel(
        feature_mean=feature_mean.tolist(),
        feature_scale=feature_scale.tolist(),
        anchors=anchors.tolist(),
        anchor_feature_centers=anchor_feature_centers,
        anchor_logit_weights=anchor_logit_weights.tolist(),
        anchor_logit_bias=anchor_logit_bias.tolist(),
        residual_weights=residual_weights,
        residual_bias=residual_bias,
        residual_modes=residual_modes,
        residual_scales=residual_scales,
        ridge=float(ridge),
        train_rows=len(rows),
        anchor_iterations=int(anchor_iterations),
        seed=int(seed),
    )


def anchor_candidate_payloads(
    frames: Iterable[WodE2EPreferenceFrame],
    model: AnchorResidualTrajectoryModel,
    *,
    source: str = "wod_anchor_residual_non_text",
    top_k: int,
    residual_modes_per_anchor: int = 0,
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for frame in frames:
        for candidate_index, (candidate_name, trajectory, confidence) in enumerate(
            model.candidate_trajectories(
                frame.past_trajectory,
                intent=frame.intent,
                init_speed_mps=frame.init_speed_mps,
                top_k=top_k,
                residual_modes_per_anchor=residual_modes_per_anchor,
            )
        ):
            payloads.append(
                {
                    "frame_name": frame.frame_name,
                    "source": source,
                    "candidate_name": candidate_name,
                    "candidate_index": candidate_index,
                    "confidence": confidence,
                    "trajectory_20wp_4hz": _json_trajectory(trajectory),
                }
            )
    return payloads


def _fit_ridge_residual(x: np.ndarray, y: np.ndarray, *, ridge: float) -> tuple[np.ndarray, np.ndarray]:
    design = np.concatenate([np.ones((x.shape[0], 1), dtype=np.float64), x], axis=1)
    penalty = np.eye(design.shape[1], dtype=np.float64) * float(ridge)
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return coefficients[0], coefficients[1:]


def _fit_anchor_logits(
    x: np.ndarray,
    labels: np.ndarray,
    *,
    anchor_count: int,
    ridge: float,
) -> tuple[np.ndarray, np.ndarray]:
    targets = np.zeros((x.shape[0], anchor_count), dtype=np.float64)
    targets[np.arange(x.shape[0]), labels] = 1.0
    return _fit_ridge_residual(x, targets, ridge=ridge)


def _residual_modes(residuals: np.ndarray, *, max_modes: int) -> tuple[list[list[float]], list[float]]:
    if max_modes <= 0 or residuals.shape[0] < 2:
        return [], []
    _, singular_values, components = np.linalg.svd(residuals, full_matrices=False)
    count = min(max_modes, components.shape[0])
    scales = (singular_values[:count] / np.sqrt(max(1, residuals.shape[0] - 1))).tolist()
    return components[:count].tolist(), [float(scale) for scale in scales]


def _kmeans(
    rows: np.ndarray,
    *,
    anchor_count: int,
    iterations: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    if iterations <= 0:
        raise ValueError("anchor_iterations must be positive")
    rng = np.random.default_rng(seed)
    initial_indices = rng.choice(rows.shape[0], size=anchor_count, replace=False)
    centers = rows[initial_indices].copy()
    labels = np.zeros(rows.shape[0], dtype=np.int64)
    for _ in range(iterations):
        distances = np.linalg.norm(rows[:, None, :] - centers[None, :, :], axis=2)
        labels = np.argmin(distances, axis=1)
        for index in range(anchor_count):
            mask = labels == index
            if np.any(mask):
                centers[index] = rows[mask].mean(axis=0)
    distances = np.linalg.norm(rows[:, None, :] - centers[None, :, :], axis=2)
    labels = np.argmin(distances, axis=1)
    return centers, labels
