from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .learned_trajectory_model import (
    FEATURE_SET_TEMPORAL,
    _frame_features,
    _json_trajectory,
    _output_from_trajectory,
    _trajectory_from_output,
)
from .rfs_metric import Trajectory
from .wod_e2e import WodCameraImage, WodE2EPreferenceFrame


FEATURE_MODE_EGO_TEMPORAL = "ego_temporal"
FEATURE_MODE_SCENE_TOKENS = "scene_tokens"
FEATURE_MODE_EXTERNAL_EMBEDDINGS = "external_embeddings"
LATENT_SOURCE_ALL = "all"
LATENT_SOURCE_SCENE = "scene"
CAMERA_NAMES = [
    "FRONT",
    "FRONT_LEFT",
    "FRONT_RIGHT",
    "SIDE_LEFT",
    "SIDE_RIGHT",
    "REAR_LEFT",
    "REAR",
    "REAR_RIGHT",
]


WORLD_SUMMARY_FEATURES = [
    "future_final_x",
    "future_final_y",
    "future_total_distance",
    "future_lateral_range",
    "future_mean_speed_mps",
    "future_max_speed_mps",
    "future_mean_abs_accel_mps2",
    "future_mean_abs_heading_change",
]
SCENE_TOKEN_CACHE_SCHEMA = "wod_scene_tokens_v1"
EXTERNAL_FRAME_EMBEDDING_CACHE_SCHEMA = "external_frame_embeddings_v1"
WORLD_PRIOR_MASK_OFF = "off"
WORLD_PRIOR_MASK_TAIL = "tail"
WORLD_PRIOR_MASK_RANDOM = "random"
WORLD_PRIOR_MASK_MIXED = "mixed"


@dataclass(frozen=True)
class WorldExperience:
    frame_name: str
    intent: int
    init_speed_mps: float
    embedding: list[float]
    future_summary: dict[str, float]
    future_trajectory: Trajectory


@dataclass(frozen=True)
class WorldPrediction:
    embedding: list[float]
    future_summary: dict[str, float]
    nearest_experiences: list[tuple[str, float]]
    trajectory: Trajectory


@dataclass(frozen=True)
class LatentPredictiveWorldPriorPrediction:
    target_embedding: list[float]
    predicted_summary: dict[str, float]


@dataclass(frozen=True)
class LearnedWorldModel:
    feature_mean: list[float]
    feature_scale: list[float]
    latent_axes: list[list[float]]
    feature_mode: str
    latent_source: str
    scene_token_names: list[str]
    summary_mean: list[float]
    summary_weights: list[list[float]]
    trajectory_mean: list[float]
    trajectory_weights: list[list[float]]
    experiences: list[WorldExperience]
    ridge: float
    latent_dim: int
    train_rows: int
    external_embedding_dimension: int = 0

    def encode(
        self,
        past_trajectory: Sequence[tuple[float, float]],
        *,
        intent: int,
        init_speed_mps: float,
    ) -> list[float]:
        raw = _frame_features(
            past_trajectory,
            intent=intent,
            init_speed_mps=init_speed_mps,
            feature_set=FEATURE_SET_TEMPORAL,
        )
        if self.latent_source == LATENT_SOURCE_SCENE:
            if self.feature_mode in {FEATURE_MODE_SCENE_TOKENS, FEATURE_MODE_EXTERNAL_EMBEDDINGS}:
                raw = [0.0 for _ in range(len(self.feature_mean))]
        elif self.feature_mode == FEATURE_MODE_SCENE_TOKENS:
            raw = [*raw, *[0.0 for _ in self.scene_token_names]]
        elif self.feature_mode == FEATURE_MODE_EXTERNAL_EMBEDDINGS:
            raw = [*raw, *[0.0 for _ in range(self.external_embedding_dimension)]]
        normalized = _normalize_row(raw, self.feature_mean, self.feature_scale)
        return (normalized @ np.asarray(self.latent_axes, dtype=np.float64).T).tolist()

    def encode_frame(self, frame: WodE2EPreferenceFrame) -> list[float]:
        raw = _world_latent_features(
            frame,
            feature_mode=self.feature_mode,
            latent_source=self.latent_source,
        )
        normalized = _normalize_row(raw, self.feature_mean, self.feature_scale)
        return (normalized @ np.asarray(self.latent_axes, dtype=np.float64).T).tolist()

    def predict(
        self,
        past_trajectory: Sequence[tuple[float, float]],
        *,
        intent: int,
        init_speed_mps: float,
        nearest: int = 3,
    ) -> WorldPrediction:
        embedding = self.encode(past_trajectory, intent=intent, init_speed_mps=init_speed_mps)
        return self._predict_from_embedding(embedding, nearest=nearest)

    def predict_frame(self, frame: WodE2EPreferenceFrame, *, nearest: int = 3) -> WorldPrediction:
        return self._predict_from_embedding(self.encode_frame(frame), nearest=nearest)

    def _predict_from_embedding(self, embedding: Sequence[float], *, nearest: int = 3) -> WorldPrediction:
        embedding = [float(value) for value in embedding]
        embedding_array = np.asarray(embedding, dtype=np.float64)
        summary = np.asarray(self.summary_mean, dtype=np.float64) + embedding_array @ np.asarray(
            self.summary_weights,
            dtype=np.float64,
        )
        trajectory_output = np.asarray(self.trajectory_mean, dtype=np.float64) + embedding_array @ np.asarray(
            self.trajectory_weights,
            dtype=np.float64,
        )
        return WorldPrediction(
            embedding=embedding,
            future_summary={
                name: float(value)
                for name, value in zip(WORLD_SUMMARY_FEATURES, summary.tolist())
            },
            nearest_experiences=self.retrieve(embedding, limit=nearest),
            trajectory=_trajectory_from_output(trajectory_output),
        )

    def retrieve(self, embedding: Sequence[float], *, limit: int = 3) -> list[tuple[str, float]]:
        if limit <= 0:
            return []
        query = np.asarray(embedding, dtype=np.float64)
        neighbors = [
            (experience.frame_name, float(np.linalg.norm(query - np.asarray(experience.embedding, dtype=np.float64))))
            for experience in self.experiences
        ]
        neighbors.sort(key=lambda item: (item[1], item[0]))
        return neighbors[:limit]

    def candidate_payloads(
        self,
        frames: Iterable[WodE2EPreferenceFrame],
        *,
        source: str = "wod_learned_world_model",
        memory_top_k: int = 0,
        max_neighbor_distance: float | None = None,
    ) -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        for frame in frames:
            for candidate_index, (candidate_name, trajectory, prediction) in enumerate(
                self.candidate_trajectories(
                    frame,
                    memory_top_k=memory_top_k,
                    max_neighbor_distance=max_neighbor_distance,
                )
            ):
                payloads.append(
                    {
                        "frame_name": frame.frame_name,
                        "source": source,
                        "candidate_name": candidate_name,
                        "candidate_index": candidate_index,
                        "trajectory_20wp_4hz": _json_trajectory(trajectory),
                        "world_embedding": [float(value) for value in prediction.embedding],
                        "world_summary": prediction.future_summary,
                        "nearest_experiences": [
                            {"frame_name": frame_name, "distance": distance}
                            for frame_name, distance in prediction.nearest_experiences
                        ],
                    }
                )
        return payloads

    def candidate_trajectories(
        self,
        frame: WodE2EPreferenceFrame,
        *,
        memory_top_k: int = 0,
        max_neighbor_distance: float | None = None,
    ) -> list[tuple[str, Trajectory, WorldPrediction]]:
        nearest_count = max(1, memory_top_k) if max_neighbor_distance is not None else memory_top_k
        prediction = self.predict_frame(frame, nearest=nearest_count)
        if max_neighbor_distance is not None:
            nearest_distance = prediction.nearest_experiences[0][1] if prediction.nearest_experiences else float("inf")
            if nearest_distance > max_neighbor_distance:
                return []
        if self.feature_mode == FEATURE_MODE_SCENE_TOKENS:
            prefix = "world_scene"
        elif self.feature_mode == FEATURE_MODE_EXTERNAL_EMBEDDINGS:
            prefix = "world_external"
        else:
            prefix = "world_ego"
        candidates: list[tuple[str, Trajectory, WorldPrediction]] = [
            (f"{prefix}_imagined_future", prediction.trajectory, prediction)
        ]
        if memory_top_k <= 0:
            return candidates
        experiences_by_name = {experience.frame_name: experience for experience in self.experiences}
        for rank, (frame_name, _) in enumerate(prediction.nearest_experiences[:memory_top_k], start=1):
            experience = experiences_by_name.get(frame_name)
            if experience is None:
                continue
            candidates.append((f"{prefix}_memory_neighbor_{rank}", experience.future_trajectory, prediction))
        return candidates

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_type": "learned_world_model_v1",
            "feature_set": FEATURE_SET_TEMPORAL,
            "feature_mode": self.feature_mode,
            "latent_source": self.latent_source,
            "scene_token_names": self.scene_token_names,
            "external_embedding_dimension": self.external_embedding_dimension,
            "world_summary_features": WORLD_SUMMARY_FEATURES,
            "feature_mean": self.feature_mean,
            "feature_scale": self.feature_scale,
            "latent_axes": self.latent_axes,
            "summary_mean": self.summary_mean,
            "summary_weights": self.summary_weights,
            "trajectory_mean": self.trajectory_mean,
            "trajectory_weights": self.trajectory_weights,
            "experiences": [
                {
                    "frame_name": experience.frame_name,
                    "intent": experience.intent,
                    "init_speed_mps": experience.init_speed_mps,
                    "embedding": experience.embedding,
                    "future_summary": experience.future_summary,
                    "future_trajectory": _json_trajectory(experience.future_trajectory),
                }
                for experience in self.experiences
            ],
            "ridge": self.ridge,
            "latent_dim": self.latent_dim,
            "train_rows": self.train_rows,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LearnedWorldModel":
        if payload.get("model_type") != "learned_world_model_v1":
            raise ValueError(f"unsupported world model type: {payload.get('model_type')!r}")
        feature_mode = str(payload.get("feature_mode", FEATURE_MODE_EGO_TEMPORAL))
        _validate_feature_mode(feature_mode)
        latent_source = str(payload.get("latent_source", LATENT_SOURCE_ALL))
        _validate_latent_source(latent_source, feature_mode=feature_mode)
        token_names = [str(value) for value in payload.get("scene_token_names", [])]
        if feature_mode == FEATURE_MODE_SCENE_TOKENS and not token_names:
            token_names = scene_token_names()
        external_dimension = int(payload.get("external_embedding_dimension", 0))
        if feature_mode == FEATURE_MODE_EXTERNAL_EMBEDDINGS and external_dimension <= 0:
            raise ValueError("external embedding world model requires external_embedding_dimension")
        return cls(
            feature_mean=[float(value) for value in payload["feature_mean"]],
            feature_scale=[float(value) for value in payload["feature_scale"]],
            latent_axes=[[float(value) for value in row] for row in payload["latent_axes"]],
            feature_mode=feature_mode,
            latent_source=latent_source,
            scene_token_names=token_names,
            summary_mean=[float(value) for value in payload["summary_mean"]],
            summary_weights=[[float(value) for value in row] for row in payload["summary_weights"]],
            trajectory_mean=[float(value) for value in payload["trajectory_mean"]],
            trajectory_weights=[[float(value) for value in row] for row in payload["trajectory_weights"]],
            experiences=[
                WorldExperience(
                    frame_name=str(row["frame_name"]),
                    intent=int(row["intent"]),
                    init_speed_mps=float(row["init_speed_mps"]),
                    embedding=[float(value) for value in row["embedding"]],
                    future_summary={key: float(value) for key, value in row["future_summary"].items()},
                    future_trajectory=[(float(x), float(y)) for x, y in row["future_trajectory"]],
                )
                for row in payload.get("experiences", [])
            ],
            ridge=float(payload["ridge"]),
            latent_dim=int(payload["latent_dim"]),
            train_rows=int(payload["train_rows"]),
            external_embedding_dimension=external_dimension,
        )

    @classmethod
    def load(cls, path: str | Path) -> "LearnedWorldModel":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class LatentPredictiveWorldPrior:
    context_feature_mean: list[float]
    context_feature_scale: list[float]
    target_summary_mean: list[float]
    target_summary_scale: list[float]
    target_axes: list[list[float]]
    context_weights: list[list[float]]
    feature_mode: str
    latent_source: str
    scene_token_names: list[str]
    ridge: float
    latent_dim: int
    train_rows: int
    residual_error_mean: float
    residual_error_scale: float
    context_mask_mode: str = WORLD_PRIOR_MASK_OFF
    external_embedding_dimension: int = 0

    def predict_frame(self, frame: WodE2EPreferenceFrame) -> LatentPredictiveWorldPriorPrediction:
        context = _world_latent_features(
            frame,
            feature_mode=self.feature_mode,
            latent_source=self.latent_source,
        )
        normalized = _normalize_row(context, self.context_feature_mean, self.context_feature_scale)
        embedding = normalized @ np.asarray(self.context_weights, dtype=np.float64)
        summary = _decode_target_summary(
            embedding,
            target_axes=np.asarray(self.target_axes, dtype=np.float64),
            target_summary_mean=self.target_summary_mean,
            target_summary_scale=self.target_summary_scale,
        )
        return LatentPredictiveWorldPriorPrediction(
            target_embedding=[float(value) for value in embedding.tolist()],
            predicted_summary={
                name: float(value)
                for name, value in zip(WORLD_SUMMARY_FEATURES, summary.tolist())
            },
        )

    def encode_trajectory(self, trajectory: Trajectory) -> list[float]:
        summary = np.asarray(_future_summary_vector(trajectory), dtype=np.float64)
        mean = np.asarray(self.target_summary_mean, dtype=np.float64)
        scale = np.asarray(self.target_summary_scale, dtype=np.float64)
        axes = np.asarray(self.target_axes, dtype=np.float64)
        normalized = (summary - mean) / np.where(np.abs(scale) > 1e-12, scale, 1.0)
        return (normalized @ axes.T).tolist()

    def candidate_features(self, frame: WodE2EPreferenceFrame, trajectory: Trajectory) -> dict[str, float]:
        prediction = self.predict_frame(frame)
        predicted_embedding = np.asarray(prediction.target_embedding, dtype=np.float64)
        candidate_embedding = np.asarray(self.encode_trajectory(trajectory), dtype=np.float64)
        latent_error = float(np.linalg.norm(candidate_embedding - predicted_embedding))
        latent_error_z = (latent_error - float(self.residual_error_mean)) / max(1e-6, float(self.residual_error_scale))
        candidate_summary = np.asarray(_future_summary_vector(trajectory), dtype=np.float64)
        predicted_summary = np.asarray(
            [prediction.predicted_summary[name] for name in WORLD_SUMMARY_FEATURES],
            dtype=np.float64,
        )
        progress_error = abs(float(candidate_summary[0] - predicted_summary[0]))
        lateral_error = abs(float(candidate_summary[1] - predicted_summary[1])) + abs(
            float(candidate_summary[3] - predicted_summary[3])
        )
        speed_error = abs(float(candidate_summary[4] - predicted_summary[4])) + abs(
            float(candidate_summary[5] - predicted_summary[5])
        )
        heading_error = abs(float(candidate_summary[7] - predicted_summary[7]))
        return {
            "world_prior_latent_error": latent_error,
            "world_prior_latent_error_log": float(math.log1p(max(0.0, latent_error))),
            "world_prior_latent_error_z": float(latent_error_z),
            "world_prior_progress_error": progress_error,
            "world_prior_lateral_error": lateral_error,
            "world_prior_speed_error": speed_error,
            "world_prior_heading_error": heading_error,
            "world_prior_constraint_cost": float(
                max(0.0, latent_error_z)
                + 0.05 * progress_error
                + 0.25 * lateral_error
                + 0.10 * speed_error
                + heading_error
            ),
            "world_prior_predicted_final_x": float(predicted_summary[0]),
            "world_prior_predicted_final_y": float(predicted_summary[1]),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_type": "latent_predictive_world_prior_v1",
            "feature_set": FEATURE_SET_TEMPORAL,
            "feature_mode": self.feature_mode,
            "latent_source": self.latent_source,
            "scene_token_names": self.scene_token_names,
            "external_embedding_dimension": self.external_embedding_dimension,
            "world_summary_features": WORLD_SUMMARY_FEATURES,
            "context_feature_mean": self.context_feature_mean,
            "context_feature_scale": self.context_feature_scale,
            "target_summary_mean": self.target_summary_mean,
            "target_summary_scale": self.target_summary_scale,
            "target_axes": self.target_axes,
            "context_weights": self.context_weights,
            "ridge": self.ridge,
            "latent_dim": self.latent_dim,
            "train_rows": self.train_rows,
            "residual_error_mean": self.residual_error_mean,
            "residual_error_scale": self.residual_error_scale,
            "context_mask_mode": self.context_mask_mode,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LatentPredictiveWorldPrior":
        if payload.get("model_type") != "latent_predictive_world_prior_v1":
            raise ValueError(f"unsupported world prior type: {payload.get('model_type')!r}")
        feature_mode = str(payload.get("feature_mode", FEATURE_MODE_EGO_TEMPORAL))
        _validate_feature_mode(feature_mode)
        latent_source = str(payload.get("latent_source", LATENT_SOURCE_ALL))
        _validate_latent_source(latent_source, feature_mode=feature_mode)
        token_names = [str(value) for value in payload.get("scene_token_names", [])]
        if feature_mode == FEATURE_MODE_SCENE_TOKENS and not token_names:
            token_names = scene_token_names()
        external_dimension = int(payload.get("external_embedding_dimension", 0))
        if feature_mode == FEATURE_MODE_EXTERNAL_EMBEDDINGS and external_dimension <= 0:
            raise ValueError("external embedding world prior requires external_embedding_dimension")
        return cls(
            context_feature_mean=[float(value) for value in payload["context_feature_mean"]],
            context_feature_scale=[float(value) for value in payload["context_feature_scale"]],
            target_summary_mean=[float(value) for value in payload["target_summary_mean"]],
            target_summary_scale=[float(value) for value in payload["target_summary_scale"]],
            target_axes=[[float(value) for value in row] for row in payload["target_axes"]],
            context_weights=[[float(value) for value in row] for row in payload["context_weights"]],
            feature_mode=feature_mode,
            latent_source=latent_source,
            scene_token_names=token_names,
            ridge=float(payload["ridge"]),
            latent_dim=int(payload["latent_dim"]),
            train_rows=int(payload["train_rows"]),
            residual_error_mean=float(payload["residual_error_mean"]),
            residual_error_scale=float(payload["residual_error_scale"]),
            context_mask_mode=str(payload.get("context_mask_mode", WORLD_PRIOR_MASK_OFF)),
            external_embedding_dimension=external_dimension,
        )

    @classmethod
    def load(cls, path: str | Path) -> "LatentPredictiveWorldPrior":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fit_world_model(
    frames: Iterable[WodE2EPreferenceFrame],
    *,
    latent_dim: int = 8,
    ridge: float = 10.0,
    feature_mode: str = FEATURE_MODE_EGO_TEMPORAL,
    latent_source: str = LATENT_SOURCE_ALL,
) -> LearnedWorldModel:
    rows = [frame for frame in frames if len(frame.future_trajectory) == 20]
    if not rows:
        raise ValueError("no frames with 20-waypoint future trajectories")
    if latent_dim <= 0:
        raise ValueError("latent_dim must be positive")
    _validate_feature_mode(feature_mode)
    _validate_latent_source(latent_source, feature_mode=feature_mode)

    x = np.asarray(
        [
            _world_latent_features(
                frame,
                feature_mode=feature_mode,
                latent_source=latent_source,
            )
            for frame in rows
        ],
        dtype=np.float64,
    )
    feature_mean = x.mean(axis=0)
    feature_scale = x.std(axis=0)
    feature_scale[feature_scale < 1e-8] = 1.0
    x_norm = (x - feature_mean) / feature_scale
    axes = _principal_axes(x_norm, latent_dim)
    embeddings = x_norm @ axes.T
    summaries = np.asarray([_future_summary_vector(frame.future_trajectory) for frame in rows], dtype=np.float64)
    trajectories = np.asarray([_output_from_trajectory(frame.future_trajectory) for frame in rows], dtype=np.float64)

    summary_mean = summaries.mean(axis=0)
    trajectory_mean = trajectories.mean(axis=0)
    summary_weights = _fit_latent_regression(embeddings, summaries - summary_mean, ridge)
    trajectory_weights = _fit_latent_regression(embeddings, trajectories - trajectory_mean, ridge)
    experiences = [
        WorldExperience(
            frame_name=frame.frame_name,
            intent=frame.intent,
            init_speed_mps=frame.init_speed_mps,
            embedding=[float(value) for value in embedding],
            future_summary={
                name: float(value)
                for name, value in zip(WORLD_SUMMARY_FEATURES, summary.tolist())
            },
            future_trajectory=[(float(x), float(y)) for x, y in frame.future_trajectory],
        )
        for frame, embedding, summary in zip(rows, embeddings, summaries)
    ]
    return LearnedWorldModel(
        feature_mean=feature_mean.tolist(),
        feature_scale=feature_scale.tolist(),
        latent_axes=axes.tolist(),
        feature_mode=feature_mode,
        latent_source=latent_source,
        scene_token_names=scene_token_names() if feature_mode == FEATURE_MODE_SCENE_TOKENS else [],
        summary_mean=summary_mean.tolist(),
        summary_weights=summary_weights.tolist(),
        trajectory_mean=trajectory_mean.tolist(),
        trajectory_weights=trajectory_weights.tolist(),
        experiences=experiences,
        ridge=float(ridge),
        latent_dim=int(axes.shape[0]),
        train_rows=len(rows),
        external_embedding_dimension=(
            _external_embedding_dimension(rows)
            if feature_mode == FEATURE_MODE_EXTERNAL_EMBEDDINGS
            else 0
        ),
    )


def fit_latent_predictive_world_prior(
    frames: Iterable[WodE2EPreferenceFrame],
    *,
    latent_dim: int = 6,
    ridge: float = 10.0,
    feature_mode: str = FEATURE_MODE_EGO_TEMPORAL,
    latent_source: str = LATENT_SOURCE_ALL,
    context_mask_mode: str = WORLD_PRIOR_MASK_OFF,
    seed: int = 0,
) -> LatentPredictiveWorldPrior:
    rows = [frame for frame in frames if len(frame.future_trajectory) == 20]
    if not rows:
        raise ValueError("no frames with 20-waypoint future trajectories")
    if latent_dim <= 0:
        raise ValueError("latent_dim must be positive")
    _validate_feature_mode(feature_mode)
    _validate_latent_source(latent_source, feature_mode=feature_mode)
    _validate_world_prior_mask_mode(context_mask_mode)
    rng = np.random.default_rng(int(seed))
    context_rows: list[WodE2EPreferenceFrame] = []
    target_frames: list[WodE2EPreferenceFrame] = []
    for frame in rows:
        for masked_frame in _masked_world_prior_training_frames(
            frame,
            feature_mode=feature_mode,
            latent_source=latent_source,
            mask_mode=context_mask_mode,
            rng=rng,
        ):
            context_rows.append(masked_frame)
            target_frames.append(frame)
    context = np.asarray(
        [
            _world_latent_features(
                frame,
                feature_mode=feature_mode,
                latent_source=latent_source,
            )
            for frame in context_rows
        ],
        dtype=np.float64,
    )
    context_mean = context.mean(axis=0)
    context_scale = context.std(axis=0)
    context_scale[context_scale < 1e-8] = 1.0
    context_norm = (context - context_mean) / context_scale
    summaries = np.asarray([_future_summary_vector(frame.future_trajectory) for frame in target_frames], dtype=np.float64)
    target_mean = summaries.mean(axis=0)
    target_scale = summaries.std(axis=0)
    target_scale[target_scale < 1e-8] = 1.0
    target_norm = (summaries - target_mean) / target_scale
    target_axes = _principal_axes(target_norm, latent_dim)
    target_embeddings = target_norm @ target_axes.T
    context_weights = _fit_latent_regression(context_norm, target_embeddings, ridge)
    predicted_embeddings = context_norm @ context_weights
    residual_errors = np.linalg.norm(target_embeddings - predicted_embeddings, axis=1)
    residual_scale = float(residual_errors.std())
    if residual_scale < 1e-8:
        residual_scale = 1.0
    return LatentPredictiveWorldPrior(
        context_feature_mean=context_mean.tolist(),
        context_feature_scale=context_scale.tolist(),
        target_summary_mean=target_mean.tolist(),
        target_summary_scale=target_scale.tolist(),
        target_axes=target_axes.tolist(),
        context_weights=context_weights.tolist(),
        feature_mode=feature_mode,
        latent_source=latent_source,
        scene_token_names=scene_token_names() if feature_mode == FEATURE_MODE_SCENE_TOKENS else [],
        ridge=float(ridge),
        latent_dim=int(target_axes.shape[0]),
        train_rows=len(context_rows),
        residual_error_mean=float(residual_errors.mean()),
        residual_error_scale=residual_scale,
        context_mask_mode=context_mask_mode,
        external_embedding_dimension=(
            _external_embedding_dimension(rows)
            if feature_mode == FEATURE_MODE_EXTERNAL_EMBEDDINGS
            else 0
        ),
    )


def scene_token_names() -> list[str]:
    names = [
        "scene_camera_count",
        "scene_payload_bytes_total_log",
        "scene_payload_bytes_mean_log",
        "scene_byte_mean",
        "scene_byte_std",
        "scene_luma_mean",
        "scene_luma_std",
        "scene_edge_mean",
    ]
    for camera_name in CAMERA_NAMES:
        prefix = f"scene_camera_{camera_name.lower()}"
        names.extend(
            [
                f"{prefix}_present",
                f"{prefix}_bytes_log",
                f"{prefix}_byte_mean",
                f"{prefix}_byte_std",
                f"{prefix}_luma_mean",
                f"{prefix}_luma_std",
                f"{prefix}_edge_mean",
            ]
        )
    return names


def scene_token_features(frame: WodE2EPreferenceFrame) -> list[float]:
    if frame.scene_tokens is not None:
        tokens = [float(value) for value in frame.scene_tokens]
        expected = len(scene_token_names())
        if len(tokens) != expected:
            raise ValueError(f"cached scene token length {len(tokens)} does not match expected {expected}")
        return tokens
    stats_by_name = {image.name: _camera_token_stats(image) for image in frame.camera_images}
    total_bytes = sum(stats.bytes_len for stats in stats_by_name.values())
    count = len(stats_by_name)
    byte_means = [stats.byte_mean for stats in stats_by_name.values()]
    byte_stds = [stats.byte_std for stats in stats_by_name.values()]
    luma_means = [stats.luma_mean for stats in stats_by_name.values()]
    luma_stds = [stats.luma_std for stats in stats_by_name.values()]
    edge_means = [stats.edge_mean for stats in stats_by_name.values()]
    values = [
        float(count),
        _log1p(total_bytes),
        _log1p(total_bytes / count) if count else 0.0,
        _mean_or_zero(byte_means),
        _mean_or_zero(byte_stds),
        _mean_or_zero(luma_means),
        _mean_or_zero(luma_stds),
        _mean_or_zero(edge_means),
    ]
    for camera_name in CAMERA_NAMES:
        stats = stats_by_name.get(camera_name, _EMPTY_CAMERA_STATS)
        values.extend(
            [
                1.0 if stats.bytes_len else 0.0,
                _log1p(stats.bytes_len),
                stats.byte_mean,
                stats.byte_std,
                stats.luma_mean,
                stats.luma_std,
                stats.edge_mean,
            ]
        )
    return values


def scene_token_cache_payload(frames: Iterable[WodE2EPreferenceFrame]) -> dict[str, object]:
    return scene_token_cache_mapping_payload(
        {
            frame.frame_name: scene_token_features(frame)
            for frame in frames
        }
    )


def scene_token_cache_mapping_payload(cache: dict[str, Sequence[float]]) -> dict[str, object]:
    return {
        "schema": SCENE_TOKEN_CACHE_SCHEMA,
        "token_names": scene_token_names(),
        "frames": {name: [float(value) for value in values] for name, values in cache.items()},
    }


def write_scene_token_cache(frames: Iterable[WodE2EPreferenceFrame], path: str | Path) -> int:
    rows = list(frames)
    payload = scene_token_cache_payload(rows)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(rows)


def write_scene_token_cache_mapping(cache: dict[str, Sequence[float]], path: str | Path) -> int:
    payload = scene_token_cache_mapping_payload(cache)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(cache)


def external_embedding_cache_payload(
    cache: dict[str, Sequence[float]],
    *,
    source: str,
) -> dict[str, object]:
    dimension = _validate_external_embedding_cache(cache)
    return {
        "schema": EXTERNAL_FRAME_EMBEDDING_CACHE_SCHEMA,
        "source": str(source),
        "dimension": int(dimension),
        "frames": {name: [float(value) for value in values] for name, values in cache.items()},
    }


def write_external_embedding_cache(
    cache: dict[str, Sequence[float]],
    path: str | Path,
    *,
    source: str,
) -> int:
    payload = external_embedding_cache_payload(cache, source=source)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(cache)


def load_scene_token_cache(path: str | Path) -> dict[str, list[float]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != SCENE_TOKEN_CACHE_SCHEMA:
        raise ValueError(f"unsupported scene token cache schema: {payload.get('schema')!r}")
    token_names = [str(value) for value in payload.get("token_names", [])]
    expected_names = scene_token_names()
    if token_names != expected_names:
        raise ValueError("scene token cache token_names do not match current feature schema")
    frames = payload.get("frames", {})
    if not isinstance(frames, dict):
        raise ValueError("scene token cache frames must be an object")
    expected_len = len(expected_names)
    cache: dict[str, list[float]] = {}
    for frame_name, values in frames.items():
        tokens = [float(value) for value in values]
        if len(tokens) != expected_len:
            raise ValueError(f"scene token cache row {frame_name!r} has {len(tokens)} values, expected {expected_len}")
        cache[str(frame_name)] = tokens
    return cache


def load_external_embedding_cache(path: str | Path) -> dict[str, list[float]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != EXTERNAL_FRAME_EMBEDDING_CACHE_SCHEMA:
        raise ValueError(f"unsupported external embedding cache schema: {payload.get('schema')!r}")
    source = payload.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError("external embedding cache source must be a non-empty string")
    if "dimension" not in payload:
        raise ValueError("external embedding cache must declare dimension")
    frames = payload.get("frames", {})
    if not isinstance(frames, dict):
        raise ValueError("external embedding cache frames must be an object")
    cache = {str(frame_name): [float(value) for value in values] for frame_name, values in frames.items()}
    dimension = _validate_external_embedding_cache(cache)
    declared_dimension = int(payload.get("dimension", dimension))
    if declared_dimension != dimension:
        raise ValueError(f"external embedding cache declared dimension {declared_dimension}, got {dimension}")
    return cache


def attach_scene_token_cache(
    frames: Iterable[WodE2EPreferenceFrame],
    cache: dict[str, list[float]],
    *,
    require_all: bool = True,
) -> list[WodE2EPreferenceFrame]:
    attached: list[WodE2EPreferenceFrame] = []
    missing: list[str] = []
    for frame in frames:
        tokens = cache.get(frame.frame_name)
        if tokens is None:
            missing.append(frame.frame_name)
            if require_all:
                continue
            attached.append(frame)
            continue
        attached.append(replace(frame, scene_tokens=[float(value) for value in tokens], camera_images=[]))
    if missing and require_all:
        examples = ", ".join(missing[:3])
        raise KeyError(f"scene token cache missing {len(missing)} frame(s), including {examples}")
    return attached


def attach_external_embedding_cache(
    frames: Iterable[WodE2EPreferenceFrame],
    cache: dict[str, Sequence[float]],
    *,
    require_all: bool = True,
) -> list[WodE2EPreferenceFrame]:
    _validate_external_embedding_cache({name: list(values) for name, values in cache.items()})
    attached: list[WodE2EPreferenceFrame] = []
    missing: list[str] = []
    for frame in frames:
        embedding = cache.get(frame.frame_name)
        if embedding is None:
            missing.append(frame.frame_name)
            if require_all:
                continue
            attached.append(frame)
            continue
        attached.append(replace(frame, external_embedding=[float(value) for value in embedding]))
    if missing and require_all:
        examples = ", ".join(missing[:3])
        raise KeyError(f"external embedding cache missing {len(missing)} frame(s), including {examples}")
    return attached


def external_embedding_dimension(frames: Iterable[WodE2EPreferenceFrame]) -> int:
    return _external_embedding_dimension(list(frames))


@dataclass(frozen=True)
class _CameraTokenStats:
    bytes_len: int
    byte_mean: float
    byte_std: float
    luma_mean: float
    luma_std: float
    edge_mean: float


_EMPTY_CAMERA_STATS = _CameraTokenStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)


def _world_frame_features(frame: WodE2EPreferenceFrame, *, feature_mode: str) -> list[float]:
    _validate_feature_mode(feature_mode)
    features = _frame_features(
        frame.past_trajectory,
        intent=frame.intent,
        init_speed_mps=frame.init_speed_mps,
        feature_set=FEATURE_SET_TEMPORAL,
    )
    if feature_mode == FEATURE_MODE_SCENE_TOKENS:
        return [*features, *scene_token_features(frame)]
    if feature_mode == FEATURE_MODE_EXTERNAL_EMBEDDINGS:
        return [*features, *external_embedding_features(frame)]
    return features


def _world_latent_features(
    frame: WodE2EPreferenceFrame,
    *,
    feature_mode: str,
    latent_source: str,
) -> list[float]:
    _validate_latent_source(latent_source, feature_mode=feature_mode)
    if latent_source == LATENT_SOURCE_ALL:
        return _world_frame_features(frame, feature_mode=feature_mode)
    if feature_mode == FEATURE_MODE_SCENE_TOKENS:
        return scene_token_features(frame)
    if feature_mode == FEATURE_MODE_EXTERNAL_EMBEDDINGS:
        return external_embedding_features(frame)
    return _world_frame_features(frame, feature_mode=feature_mode)


def external_embedding_features(frame: WodE2EPreferenceFrame) -> list[float]:
    if frame.external_embedding is None:
        raise ValueError(f"frame {frame.frame_name!r} is missing external embedding")
    values = [float(value) for value in frame.external_embedding]
    if not values:
        raise ValueError(f"frame {frame.frame_name!r} has an empty external embedding")
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"frame {frame.frame_name!r} has a non-finite external embedding value")
    return values


def _camera_token_stats(image: WodCameraImage) -> _CameraTokenStats:
    payload = np.frombuffer(image.jpeg, dtype=np.uint8)
    byte_mean = float(payload.mean() / 255.0) if payload.size else 0.0
    byte_std = float(payload.std() / 255.0) if payload.size else 0.0
    luma_mean, luma_std, edge_mean = _jpeg_luma_stats(image.jpeg)
    return _CameraTokenStats(
        bytes_len=len(image.jpeg),
        byte_mean=byte_mean,
        byte_std=byte_std,
        luma_mean=luma_mean,
        luma_std=luma_std,
        edge_mean=edge_mean,
    )


def _jpeg_luma_stats(jpeg: bytes) -> tuple[float, float, float]:
    image = _decode_jpeg_luma(jpeg)
    if image is None or image.size == 0:
        return (0.0, 0.0, 0.0)
    normalized = image.astype(np.float32) / 255.0
    dx = np.abs(np.diff(normalized, axis=1)).mean() if normalized.shape[1] > 1 else 0.0
    dy = np.abs(np.diff(normalized, axis=0)).mean() if normalized.shape[0] > 1 else 0.0
    return (float(normalized.mean()), float(normalized.std()), float((dx + dy) * 0.5))


def _decode_jpeg_luma(jpeg: bytes) -> np.ndarray | None:
    try:
        from PIL import Image

        from io import BytesIO

        with Image.open(BytesIO(jpeg)) as image:
            return np.asarray(image.convert("L"))
    except Exception:
        return None


def _validate_feature_mode(feature_mode: str) -> None:
    if feature_mode not in {FEATURE_MODE_EGO_TEMPORAL, FEATURE_MODE_SCENE_TOKENS, FEATURE_MODE_EXTERNAL_EMBEDDINGS}:
        raise ValueError(f"unsupported world model feature mode: {feature_mode}")


def _validate_world_prior_mask_mode(mask_mode: str) -> None:
    if mask_mode not in {
        WORLD_PRIOR_MASK_OFF,
        WORLD_PRIOR_MASK_TAIL,
        WORLD_PRIOR_MASK_RANDOM,
        WORLD_PRIOR_MASK_MIXED,
    }:
        raise ValueError(f"unsupported world prior mask mode: {mask_mode}")


def _validate_latent_source(latent_source: str, *, feature_mode: str) -> None:
    if latent_source not in {LATENT_SOURCE_ALL, LATENT_SOURCE_SCENE}:
        raise ValueError(f"unsupported world model latent source: {latent_source}")
    if latent_source == LATENT_SOURCE_SCENE and feature_mode == FEATURE_MODE_EGO_TEMPORAL:
        raise ValueError("scene latent source requires scene_tokens or external_embeddings world mode")


def _validate_external_embedding_cache(cache: dict[str, Sequence[float]]) -> int:
    if not cache:
        raise ValueError("external embedding cache must contain at least one frame")
    dimension: int | None = None
    for frame_name, values in cache.items():
        vector = [float(value) for value in values]
        if not vector:
            raise ValueError(f"external embedding row {frame_name!r} is empty")
        if not all(math.isfinite(value) for value in vector):
            raise ValueError(f"external embedding row {frame_name!r} has a non-finite value")
        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise ValueError(f"external embedding row {frame_name!r} has {len(vector)} values, expected {dimension}")
    return int(dimension or 0)


def _external_embedding_dimension(frames: list[WodE2EPreferenceFrame]) -> int:
    cache = {
        frame.frame_name: external_embedding_features(frame)
        for frame in frames
        if frame.external_embedding is not None
    }
    return _validate_external_embedding_cache(cache)


def _principal_axes(x_norm: np.ndarray, latent_dim: int) -> np.ndarray:
    _, _, vh = np.linalg.svd(x_norm, full_matrices=False)
    available = min(latent_dim, vh.shape[0])
    axes = vh[:available]
    if available == latent_dim:
        return axes
    padding = np.zeros((latent_dim - available, x_norm.shape[1]), dtype=np.float64)
    return np.concatenate([axes, padding], axis=0)


def _fit_latent_regression(embeddings: np.ndarray, target: np.ndarray, ridge: float) -> np.ndarray:
    penalty = np.eye(embeddings.shape[1], dtype=np.float64) * float(ridge)
    return np.linalg.solve(embeddings.T @ embeddings + penalty, embeddings.T @ target)


def _masked_world_prior_training_frames(
    frame: WodE2EPreferenceFrame,
    *,
    feature_mode: str,
    latent_source: str,
    mask_mode: str,
    rng: np.random.Generator,
) -> list[WodE2EPreferenceFrame]:
    variants = [frame]
    if mask_mode in {WORLD_PRIOR_MASK_TAIL, WORLD_PRIOR_MASK_MIXED}:
        variants.append(_masked_world_prior_frame(frame, feature_mode=feature_mode, latent_source=latent_source, mode="tail", rng=rng))
    if mask_mode in {WORLD_PRIOR_MASK_RANDOM, WORLD_PRIOR_MASK_MIXED}:
        variants.append(
            _masked_world_prior_frame(frame, feature_mode=feature_mode, latent_source=latent_source, mode="random", rng=rng)
        )
    return variants


def _masked_world_prior_frame(
    frame: WodE2EPreferenceFrame,
    *,
    feature_mode: str,
    latent_source: str,
    mode: str,
    rng: np.random.Generator,
) -> WodE2EPreferenceFrame:
    masked_past = _masked_past_trajectory(frame.past_trajectory, mode=mode, rng=rng)
    masked_scene_tokens = frame.scene_tokens
    masked_external_embedding = frame.external_embedding
    if feature_mode == FEATURE_MODE_SCENE_TOKENS or latent_source == LATENT_SOURCE_SCENE:
        if masked_scene_tokens is not None:
            masked_scene_tokens = _masked_vector(masked_scene_tokens, mode=mode, rng=rng)
        if feature_mode == FEATURE_MODE_EXTERNAL_EMBEDDINGS and masked_external_embedding is not None:
            masked_external_embedding = _masked_vector(masked_external_embedding, mode=mode, rng=rng)
    elif feature_mode == FEATURE_MODE_EXTERNAL_EMBEDDINGS and masked_external_embedding is not None:
        masked_external_embedding = _masked_vector(masked_external_embedding, mode=mode, rng=rng)
    return replace(
        frame,
        past_trajectory=masked_past,
        scene_tokens=None if masked_scene_tokens is None else [float(value) for value in masked_scene_tokens],
        external_embedding=(
            None if masked_external_embedding is None else [float(value) for value in masked_external_embedding]
        ),
    )


def _masked_past_trajectory(
    trajectory: Sequence[tuple[float, float]],
    *,
    mode: str,
    rng: np.random.Generator,
) -> Trajectory:
    points = [(float(x), float(y)) for x, y in trajectory]
    if len(points) <= 2:
        return points
    keep = max(2, int(math.ceil(len(points) * 0.5)))
    if mode == "tail":
        return points[-keep:]
    if mode != "random":
        raise ValueError(f"unsupported mask variant: {mode}")
    candidate_indices = list(range(max(0, len(points) - 1)))
    pick = sorted(rng.choice(candidate_indices, size=max(0, keep - 1), replace=False).tolist()) if keep > 1 else []
    indices = sorted({*pick, len(points) - 1})
    return [points[index] for index in indices]


def _masked_vector(
    values: Sequence[float],
    *,
    mode: str,
    rng: np.random.Generator,
) -> list[float]:
    array = np.asarray([float(value) for value in values], dtype=np.float64)
    if array.size <= 1:
        return array.tolist()
    keep = max(1, int(math.ceil(array.size * 0.5)))
    if mode == "tail":
        mask = np.zeros(array.size, dtype=np.float64)
        mask[:keep] = 1.0
        return (array * mask).tolist()
    if mode != "random":
        raise ValueError(f"unsupported mask variant: {mode}")
    indices = rng.choice(array.size, size=keep, replace=False)
    mask = np.zeros(array.size, dtype=np.float64)
    mask[indices] = 1.0
    return (array * mask).tolist()


def _decode_target_summary(
    embedding: np.ndarray,
    *,
    target_axes: np.ndarray,
    target_summary_mean: Sequence[float],
    target_summary_scale: Sequence[float],
) -> np.ndarray:
    mean = np.asarray(target_summary_mean, dtype=np.float64)
    scale = np.asarray(target_summary_scale, dtype=np.float64)
    normalized = embedding @ target_axes
    return mean + normalized * scale


def _normalize_row(
    row: Sequence[float],
    feature_mean: Sequence[float],
    feature_scale: Sequence[float],
) -> np.ndarray:
    values = np.asarray(row, dtype=np.float64)
    mean = np.asarray(feature_mean, dtype=np.float64)
    scale = np.asarray(feature_scale, dtype=np.float64)
    safe_scale = np.where(np.abs(scale) > 1e-12, scale, 1.0)
    return (values - mean) / safe_scale


def _future_summary_vector(trajectory: Trajectory) -> list[float]:
    if len(trajectory) != 20:
        raise ValueError("world summary expects exactly 20 future points")
    step_distances = [
        float(np.hypot(trajectory[0][0], trajectory[0][1])),
        *[
            float(
                np.hypot(
                    trajectory[index][0] - trajectory[index - 1][0],
                    trajectory[index][1] - trajectory[index - 1][1],
                )
            )
            for index in range(1, len(trajectory))
        ],
    ]
    speeds = [distance * 4.0 for distance in step_distances]
    accels = [(speeds[index] - speeds[index - 1]) * 4.0 for index in range(1, len(speeds))]
    y_values = [point[1] for point in trajectory]
    return [
        float(trajectory[-1][0]),
        float(trajectory[-1][1]),
        float(sum(step_distances)),
        float(max(y_values) - min(y_values)),
        float(sum(speeds) / len(speeds)),
        float(max(speeds)),
        float(sum(abs(value) for value in accels) / len(accels)) if accels else 0.0,
        float(_mean_abs_heading_change(trajectory)),
    ]


def _mean_abs_heading_change(trajectory: Trajectory) -> float:
    headings: list[float] = []
    previous = (0.0, 0.0)
    for point in trajectory:
        dx = point[0] - previous[0]
        dy = point[1] - previous[1]
        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            headings.append(float(np.arctan2(dy, dx)))
        previous = point
    if len(headings) < 2:
        return 0.0
    changes = [
        abs(_wrap_angle(headings[index] - headings[index - 1]))
        for index in range(1, len(headings))
    ]
    return float(sum(changes) / len(changes))


def _wrap_angle(angle: float) -> float:
    return float((angle + np.pi) % (2.0 * np.pi) - np.pi)


def _mean_or_zero(values: Sequence[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _log1p(value: float) -> float:
    return math.log1p(max(0.0, float(value)))
