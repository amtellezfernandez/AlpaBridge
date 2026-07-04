from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .learned_trajectory_model import FUTURE_WAYPOINTS, PAST_WAYPOINTS, OUTPUT_DIM, _trajectory_from_output
from .rfs_metric import RfsReference, Trajectory
from .wod_e2e import WodE2EPreferenceFrame


NEURAL_PLANNER_MODEL_TYPE = "neural_system2_planner_v1"
PLANNER_FRAME_CACHE_SCHEMA = "wod_neural_system2_planner_frames_v1"


@dataclass(frozen=True)
class PlannerTrainingTensors:
    frame_names: list[str]
    past: np.ndarray
    intent: np.ndarray
    speed: np.ndarray
    external: np.ndarray
    target: np.ndarray
    critic_trajectories: np.ndarray
    critic_scores: np.ndarray
    critic_mask: np.ndarray
    external_embedding_dimension: int


@dataclass(frozen=True)
class NeuralSystem2Planner:
    past_mean: list[list[float]]
    past_scale: list[list[float]]
    speed_mean: float
    speed_scale: float
    external_embedding_dimension: int
    model_config: dict[str, int | float | str]
    state_dict: dict[str, Any]
    train_rows: int
    seed: int

    def candidate_trajectories_for_frame(
        self,
        frame: WodE2EPreferenceFrame,
        *,
        top_k: int = 8,
        refine_steps: int = 0,
        refine_step_size: float = 0.03,
        smoothness_weight: float = 0.03,
        trust_region_weight: float = 0.03,
    ) -> list[tuple[str, Trajectory, float]]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if refine_steps < 0:
            raise ValueError("refine_steps must be non-negative")
        torch = _import_torch()
        module = _planner_module_from_payload(torch, self)
        module.eval()
        with torch.no_grad():
            past, intent, speed, external = self._tensors_for_frame(torch, frame)
            context, logits, trajectories = module(past, intent, speed, external)
        if refine_steps:
            trajectories = _refine_trajectories(
                torch,
                module,
                context,
                trajectories,
                steps=refine_steps,
                step_size=refine_step_size,
                smoothness_weight=smoothness_weight,
                trust_region_weight=trust_region_weight,
            )
        with torch.no_grad():
            utility = module.score_candidates(context, trajectories)[0]
            scores = utility + 0.05 * logits[0]
            order = torch.argsort(scores, descending=True)[: min(int(top_k), int(trajectories.shape[1]))]
            results: list[tuple[str, Trajectory, float]] = []
            for rank, mode_index_tensor in enumerate(order):
                mode_index = int(mode_index_tensor.detach().cpu())
                output = trajectories[0, mode_index].detach().cpu().numpy().astype(float)
                confidence = float(scores[mode_index].detach().cpu()) * 10.0
                results.append(
                    (
                        f"neural_system2_mode_{mode_index}_rank{rank}",
                        _trajectory_from_output(output),
                        confidence,
                    )
                )
            return results

    def score_trajectory(self, frame: WodE2EPreferenceFrame, trajectory: Trajectory) -> float:
        torch = _import_torch()
        module = _planner_module_from_payload(torch, self)
        module.eval()
        with torch.no_grad():
            past, intent, speed, external = self._tensors_for_frame(torch, frame)
            context, _logits, _trajectories = module(past, intent, speed, external)
            candidate = torch.as_tensor([[_future_output(trajectory)]], dtype=torch.float32)
            score = module.score_candidates(context, candidate)[0, 0]
        return float(score.detach().cpu()) * 10.0

    def _tensors_for_frame(self, torch, frame: WodE2EPreferenceFrame):
        return (
            torch.as_tensor([_normalized_past(frame.past_trajectory, self.past_mean, self.past_scale)]).float(),
            torch.as_tensor([int(frame.intent)], dtype=torch.long),
            torch.as_tensor([[_normalized_speed(frame.init_speed_mps, self.speed_mean, self.speed_scale)]]).float(),
            torch.as_tensor(
                [_external_embedding(frame.external_embedding, self.external_embedding_dimension)]
            ).float(),
        )

    @classmethod
    def load(cls, path: str | Path) -> "NeuralSystem2Planner":
        torch = _import_torch()
        payload = torch.load(Path(path), map_location="cpu", weights_only=False)
        if payload.get("model_type") != NEURAL_PLANNER_MODEL_TYPE:
            raise ValueError(f"unsupported neural planner type: {payload.get('model_type')!r}")
        return cls(
            past_mean=[[float(value) for value in row] for row in payload["past_mean"]],
            past_scale=[[float(value) for value in row] for row in payload["past_scale"]],
            speed_mean=float(payload["speed_mean"]),
            speed_scale=float(payload["speed_scale"]),
            external_embedding_dimension=int(payload.get("external_embedding_dimension", 0)),
            model_config=dict(payload["model_config"]),
            state_dict=payload["state_dict"],
            train_rows=int(payload["train_rows"]),
            seed=int(payload["seed"]),
        )

    def save(self, path: str | Path) -> None:
        torch = _import_torch()
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "model_type": NEURAL_PLANNER_MODEL_TYPE,
                "past_mean": self.past_mean,
                "past_scale": self.past_scale,
                "speed_mean": float(self.speed_mean),
                "speed_scale": float(self.speed_scale),
                "external_embedding_dimension": int(self.external_embedding_dimension),
                "model_config": self.model_config,
                "state_dict": self.state_dict,
                "train_rows": int(self.train_rows),
                "seed": int(self.seed),
            },
            output_path,
        )


def fit_neural_system2_planner(
    frames: Iterable[WodE2EPreferenceFrame],
    *,
    hidden_dim: int = 256,
    layers: int = 3,
    heads: int = 8,
    modes: int = 12,
    epochs: int = 80,
    batch_size: int = 128,
    learning_rate: float = 3e-4,
    max_reference_candidates: int = 8,
    confidence_weight: float = 0.2,
    critic_weight: float = 1.0,
    smoothness_weight: float = 0.02,
    generator_utility_weight: float = 0.04,
    diversity_weight: float = 0.0,
    decoder_type: str = "mode_query",
    seed: int = 17,
    device: str = "auto",
) -> tuple[NeuralSystem2Planner, dict[str, Any]]:
    torch = _import_torch()
    _validate_training_args(hidden_dim, layers, heads, modes, epochs, batch_size, learning_rate)
    tensors = build_planner_training_tensors(frames, max_reference_candidates=max_reference_candidates)
    if not tensors.frame_names:
        raise ValueError("no frames with 20-waypoint future trajectories")
    selected_device = _select_torch_device(torch, device)
    torch.manual_seed(int(seed))

    past_mean = tensors.past.mean(axis=0)
    past_scale = tensors.past.std(axis=0)
    past_scale[past_scale < 1e-6] = 1.0
    speed_mean = float(tensors.speed.mean())
    speed_scale = float(tensors.speed.std())
    if speed_scale < 1e-6:
        speed_scale = 1.0

    past_tensor = torch.as_tensor(
        (tensors.past - past_mean) / past_scale,
        dtype=torch.float32,
        device=selected_device,
    )
    speed_tensor = torch.as_tensor(
        (tensors.speed - speed_mean) / speed_scale,
        dtype=torch.float32,
        device=selected_device,
    )
    external_tensor = torch.as_tensor(tensors.external, dtype=torch.float32, device=selected_device)
    intent_tensor = torch.as_tensor(tensors.intent, dtype=torch.long, device=selected_device)
    target_tensor = torch.as_tensor(tensors.target, dtype=torch.float32, device=selected_device)
    critic_traj_tensor = torch.as_tensor(tensors.critic_trajectories, dtype=torch.float32, device=selected_device)
    critic_score_tensor = torch.as_tensor(tensors.critic_scores, dtype=torch.float32, device=selected_device)
    critic_mask_tensor = torch.as_tensor(tensors.critic_mask, dtype=torch.float32, device=selected_device)

    config = {
        "hidden_dim": int(hidden_dim),
        "layers": int(layers),
        "heads": int(heads),
        "modes": int(modes),
        "external_embedding_dimension": int(tensors.external_embedding_dimension),
        "decoder_type": str(decoder_type),
    }
    module = _TorchNeuralSystem2Planner(torch, **_module_config(config)).to(selected_device)
    optimizer = torch.optim.AdamW(module.parameters(), lr=float(learning_rate), weight_decay=1e-4)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(int(seed))
    row_count = len(tensors.frame_names)
    history: list[dict[str, float]] = []
    for epoch in range(int(epochs)):
        order = torch.randperm(row_count, generator=generator).to(selected_device)
        totals = {
            "loss": 0.0,
            "trajectory_loss": 0.0,
            "confidence_loss": 0.0,
            "critic_loss": 0.0,
            "smoothness_loss": 0.0,
            "utility_loss": 0.0,
            "diversity_loss": 0.0,
        }
        for start in range(0, row_count, int(batch_size)):
            batch = order[start : start + int(batch_size)]
            context, logits, trajectories = module(
                past_tensor[batch],
                intent_tensor[batch],
                speed_tensor[batch],
                external_tensor[batch],
            )
            loss, parts = _planner_loss(
                torch,
                module,
                context,
                logits,
                trajectories,
                target_tensor[batch],
                critic_traj_tensor[batch],
                critic_score_tensor[batch],
                critic_mask_tensor[batch],
                confidence_weight=confidence_weight,
                critic_weight=critic_weight,
                smoothness_weight=smoothness_weight,
                generator_utility_weight=generator_utility_weight,
                diversity_weight=diversity_weight,
            )
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            batch_size_actual = int(len(batch))
            for key in totals:
                totals[key] += float(parts[key].detach().cpu()) * batch_size_actual
        history.append({"epoch": float(epoch + 1), **{key: value / row_count for key, value in totals.items()}})

    model = NeuralSystem2Planner(
        past_mean=past_mean.astype(float).tolist(),
        past_scale=past_scale.astype(float).tolist(),
        speed_mean=speed_mean,
        speed_scale=speed_scale,
        external_embedding_dimension=tensors.external_embedding_dimension,
        model_config=config,
        state_dict={key: value.detach().cpu() for key, value in module.state_dict().items()},
        train_rows=row_count,
        seed=int(seed),
    )
    metadata = {
        "schema": "wod_neural_system2_planner_train_report_v1",
        "device": str(selected_device),
        "torch_version": str(torch.__version__),
        "cuda_available": bool(torch.cuda.is_available()),
        "history": history,
        "train_rows": row_count,
        "hidden_dim": int(hidden_dim),
        "layers": int(layers),
        "heads": int(heads),
        "modes": int(modes),
        "decoder_type": str(decoder_type),
        "max_reference_candidates": int(max_reference_candidates),
        "external_embedding_dimension": int(tensors.external_embedding_dimension),
        "diversity_weight": float(diversity_weight),
    }
    return model, metadata


def build_planner_training_tensors(
    frames: Iterable[WodE2EPreferenceFrame],
    *,
    max_reference_candidates: int = 8,
) -> PlannerTrainingTensors:
    if max_reference_candidates <= 0:
        raise ValueError("max_reference_candidates must be positive")
    rows = [frame for frame in frames if len(frame.future_trajectory) == FUTURE_WAYPOINTS]
    external_dim = _external_embedding_dimension(rows)
    frame_names: list[str] = []
    past_rows: list[list[list[float]]] = []
    intents: list[int] = []
    speeds: list[list[float]] = []
    externals: list[list[float]] = []
    targets: list[list[float]] = []
    critic_trajectories: list[list[list[float]]] = []
    critic_scores: list[list[float]] = []
    critic_mask: list[list[float]] = []
    for frame in rows:
        bank = _critic_bank_for_frame(frame, max_candidates=max_reference_candidates)
        if not bank:
            continue
        frame_names.append(frame.frame_name)
        past_rows.append(_pad_recent_points(frame.past_trajectory))
        intents.append(int(frame.intent))
        speeds.append([float(frame.init_speed_mps)])
        externals.append(_external_embedding(frame.external_embedding, external_dim))
        targets.append(_future_output(_planner_target_trajectory(frame)))
        bank_trajectories = [_future_output(trajectory) for trajectory, _score in bank]
        bank_scores = [float(score) / 10.0 for _trajectory, score in bank]
        while len(bank_trajectories) < max_reference_candidates:
            bank_trajectories.append([0.0] * OUTPUT_DIM)
            bank_scores.append(0.0)
        mask = [1.0] * len(bank) + [0.0] * (max_reference_candidates - len(bank))
        critic_trajectories.append(bank_trajectories[:max_reference_candidates])
        critic_scores.append(bank_scores[:max_reference_candidates])
        critic_mask.append(mask[:max_reference_candidates])
    return PlannerTrainingTensors(
        frame_names=frame_names,
        past=np.asarray(past_rows, dtype=np.float32).reshape((-1, PAST_WAYPOINTS, 2)),
        intent=np.asarray(intents, dtype=np.int64),
        speed=np.asarray(speeds, dtype=np.float32).reshape((-1, 1)),
        external=np.asarray(externals, dtype=np.float32).reshape((len(frame_names), external_dim)),
        target=np.asarray(targets, dtype=np.float32).reshape((-1, OUTPUT_DIM)),
        critic_trajectories=np.asarray(critic_trajectories, dtype=np.float32).reshape(
            (-1, max_reference_candidates, OUTPUT_DIM)
        ),
        critic_scores=np.asarray(critic_scores, dtype=np.float32).reshape((-1, max_reference_candidates)),
        critic_mask=np.asarray(critic_mask, dtype=np.float32).reshape((-1, max_reference_candidates)),
        external_embedding_dimension=int(external_dim),
    )


def save_neural_planner_frame_cache(
    frames: Iterable[WodE2EPreferenceFrame],
    path: str | Path,
    *,
    append: bool = False,
) -> int:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    mode = "a" if append else "w"
    with output_path.open(mode, encoding="utf-8") as output:
        for frame in frames:
            if len(frame.future_trajectory) != FUTURE_WAYPOINTS:
                continue
            output.write(json.dumps(_planner_frame_to_dict(frame), sort_keys=True) + "\n")
            count += 1
    return count


def load_neural_planner_frame_cache(path: str | Path) -> list[WodE2EPreferenceFrame]:
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return []
    if text.lstrip().startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and "frames" in payload:
            schema = payload.get("schema")
            if schema == "wod_preference_frames_v1":
                return [_planner_frame_from_dict(frame) for frame in payload.get("frames", [])]
            if schema == PLANNER_FRAME_CACHE_SCHEMA:
                return [_planner_frame_from_dict(frame) for frame in payload.get("frames", [])]
            raise ValueError(f"unsupported neural planner frame cache schema: {schema!r}")
    frames: list[WodE2EPreferenceFrame] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            frames.append(_planner_frame_from_dict(json.loads(line)))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid neural planner frame cache row {line_number}") from exc
    return frames


def trajectory_constraint_penalty(trajectory: Sequence[tuple[float, float]]) -> float:
    points = np.asarray([[float(x), float(y)] for x, y in trajectory], dtype=np.float64)
    return float(_trajectory_penalty_np(points[None, :, :])[0])


def _planner_loss(
    torch,
    module,
    context,
    logits,
    trajectories,
    target,
    critic_trajectories,
    critic_scores,
    critic_mask,
    *,
    confidence_weight: float,
    critic_weight: float,
    smoothness_weight: float,
    generator_utility_weight: float,
    diversity_weight: float,
):
    per_mode = torch.nn.functional.smooth_l1_loss(
        trajectories,
        target[:, None, :].expand_as(trajectories),
        reduction="none",
    ).mean(dim=2)
    trajectory_loss, best_mode = per_mode.min(dim=1)
    confidence_loss = torch.nn.functional.cross_entropy(logits, best_mode)
    critic_pred = module.score_candidates(context, critic_trajectories)
    critic_error = (critic_pred - critic_scores) * critic_mask
    critic_loss = (critic_error * critic_error).sum() / torch.clamp(critic_mask.sum(), min=1.0)
    smoothness_loss = _torch_smoothness_penalty(torch, trajectories).mean()
    generated_utility = module.score_candidates(context, trajectories).max(dim=1).values
    utility_loss = -generated_utility.mean()
    diversity_loss = -_torch_mode_diversity_reward(torch, trajectories)
    total = (
        trajectory_loss.mean()
        + confidence_weight * confidence_loss
        + critic_weight * critic_loss
        + smoothness_weight * smoothness_loss
        + generator_utility_weight * utility_loss
        + diversity_weight * diversity_loss
    )
    return total, {
        "loss": total,
        "trajectory_loss": trajectory_loss.mean(),
        "confidence_loss": confidence_loss,
        "critic_loss": critic_loss,
        "smoothness_loss": smoothness_loss,
        "utility_loss": utility_loss,
        "diversity_loss": diversity_loss,
    }


def _refine_trajectories(
    torch,
    module,
    context,
    trajectories,
    *,
    steps: int,
    step_size: float,
    smoothness_weight: float,
    trust_region_weight: float,
):
    refined = trajectories.detach().clone().requires_grad_(True)
    anchor = trajectories.detach().clone()
    optimizer = torch.optim.Adam([refined], lr=float(step_size))
    for _ in range(int(steps)):
        utility = module.score_candidates(context, refined).mean()
        smoothness = _torch_smoothness_penalty(torch, refined).mean()
        trust = torch.mean((refined - anchor) * (refined - anchor))
        feasibility = _torch_feasibility_penalty(torch, refined).mean()
        loss = -(utility - smoothness_weight * smoothness - trust_region_weight * trust - 0.03 * feasibility)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
    return refined.detach()


def _planner_module_from_payload(torch, payload: NeuralSystem2Planner):
    module = _TorchNeuralSystem2Planner(torch, **_module_config(payload.model_config))
    module.load_state_dict(payload.state_dict)
    return module


def _module_config(config: dict[str, int | float | str]) -> dict[str, int | str]:
    return {
        "hidden_dim": int(config["hidden_dim"]),
        "layers": int(config["layers"]),
        "heads": int(config["heads"]),
        "modes": int(config["modes"]),
        "external_embedding_dimension": int(config.get("external_embedding_dimension", 0)),
        "decoder_type": str(config.get("decoder_type", "linear")),
    }


def _validate_training_args(
    hidden_dim: int,
    layers: int,
    heads: int,
    modes: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
) -> None:
    if min(hidden_dim, layers, heads, modes, epochs, batch_size) <= 0 or learning_rate <= 0.0:
        raise ValueError("hidden_dim, layers, heads, modes, epochs, batch_size, and learning_rate must be positive")
    if hidden_dim % heads != 0:
        raise ValueError("hidden_dim must be divisible by heads")


def _critic_bank_for_frame(
    frame: WodE2EPreferenceFrame,
    *,
    max_candidates: int,
) -> list[tuple[Trajectory, float]]:
    bank: list[tuple[Trajectory, float]] = []
    if len(frame.future_trajectory) == FUTURE_WAYPOINTS:
        bank.append((frame.future_trajectory, 10.0))
    references = sorted(frame.references, key=lambda reference: float(reference.score), reverse=True)
    for reference in references:
        if len(reference.trajectory) != FUTURE_WAYPOINTS:
            continue
        bank.append((reference.trajectory, float(np.clip(reference.score, 0.0, 10.0))))
        if len(bank) >= max_candidates:
            break
    return bank[:max_candidates]


def _planner_target_trajectory(frame: WodE2EPreferenceFrame) -> Trajectory:
    valid_references = [
        reference for reference in frame.references if len(reference.trajectory) == FUTURE_WAYPOINTS
    ]
    if valid_references:
        best = max(valid_references, key=lambda reference: float(reference.score))
        if float(best.score) >= 8.0:
            return best.trajectory
    return frame.future_trajectory


def _planner_frame_to_dict(frame: WodE2EPreferenceFrame) -> dict[str, Any]:
    return {
        "schema": PLANNER_FRAME_CACHE_SCHEMA,
        "frame_name": frame.frame_name,
        "past_trajectory": _json_trajectory(frame.past_trajectory),
        "future_trajectory": _json_trajectory(frame.future_trajectory),
        "intent": int(frame.intent),
        "init_speed_mps": float(frame.init_speed_mps),
        "scene_tokens": frame.scene_tokens,
        "external_embedding": frame.external_embedding,
        "references": [
            {
                "label": reference.label,
                "trajectory": _json_trajectory(reference.trajectory),
                "score": float(reference.score),
            }
            for reference in frame.references
        ],
    }


def _planner_frame_from_dict(payload: dict[str, Any]) -> WodE2EPreferenceFrame:
    return WodE2EPreferenceFrame(
        frame_name=str(payload["frame_name"]),
        past_trajectory=_trajectory_from_payload(payload["past_trajectory"]),
        future_trajectory=_trajectory_from_payload(payload["future_trajectory"]),
        intent=int(payload["intent"]),
        init_speed_mps=float(payload["init_speed_mps"]),
        references=[
            RfsReference(
                label=str(reference["label"]),
                trajectory=_trajectory_from_payload(reference["trajectory"]),
                score=float(reference["score"]),
            )
            for reference in payload.get("references", [])
        ],
        scene_tokens=_optional_float_list(payload.get("scene_tokens")),
        external_embedding=_optional_float_list(payload.get("external_embedding")),
    )


def _normalized_past(
    trajectory: Sequence[tuple[float, float]],
    mean: Sequence[Sequence[float]],
    scale: Sequence[Sequence[float]],
) -> list[list[float]]:
    past = np.asarray(_pad_recent_points(trajectory), dtype=np.float32)
    return ((past - np.asarray(mean, dtype=np.float32)) / np.asarray(scale, dtype=np.float32)).tolist()


def _normalized_speed(value: float, mean: float, scale: float) -> float:
    return float((float(value) - float(mean)) / float(scale))


def _pad_recent_points(trajectory: Sequence[tuple[float, float]]) -> list[list[float]]:
    points = [[float(x), float(y)] for x, y in trajectory[-PAST_WAYPOINTS:]]
    if not points:
        points = [[0.0, 0.0]]
    while len(points) < PAST_WAYPOINTS:
        points.insert(0, points[0])
    return points


def _future_output(trajectory: Sequence[tuple[float, float]]) -> list[float]:
    points = [(float(x), float(y)) for x, y in trajectory[:FUTURE_WAYPOINTS]]
    if not points:
        points = [(0.0, 0.0)]
    while len(points) < FUTURE_WAYPOINTS:
        points.append(points[-1])
    values: list[float] = []
    for x, y in points[:FUTURE_WAYPOINTS]:
        values.extend([x, y])
    return values


def _external_embedding(values: Sequence[float] | None, dimension: int) -> list[float]:
    if dimension <= 0:
        return []
    if values is None:
        return [0.0] * dimension
    result = [float(value) for value in values[:dimension]]
    return result + [0.0] * (dimension - len(result))


def _external_embedding_dimension(frames: Sequence[WodE2EPreferenceFrame]) -> int:
    for frame in frames:
        if frame.external_embedding:
            return len(frame.external_embedding)
    return 0


def _json_trajectory(trajectory: Trajectory) -> list[list[float]]:
    return [[float(x), float(y)] for x, y in trajectory]


def _trajectory_from_payload(payload: Sequence[Sequence[object]]) -> Trajectory:
    return [(float(point[0]), float(point[1])) for point in payload]


def _optional_float_list(payload: object) -> list[float] | None:
    if payload is None:
        return None
    return [float(value) for value in payload]


def _trajectory_penalty_np(points: np.ndarray) -> np.ndarray:
    if points.shape[1] < 2:
        return np.zeros(points.shape[0], dtype=np.float64)
    deltas = points[:, 1:] - points[:, :-1]
    reverse = np.maximum(0.0, -deltas[:, :, 0]).mean(axis=1)
    lateral = np.maximum(0.0, np.abs(points[:, :, 1]).max(axis=1) - 8.0)
    if points.shape[1] < 3:
        accel = np.zeros(points.shape[0], dtype=np.float64)
    else:
        second = points[:, 2:] - 2.0 * points[:, 1:-1] + points[:, :-2]
        accel = np.mean(np.sum(second * second, axis=2), axis=1)
    return reverse + 0.05 * lateral + 0.1 * accel


def _torch_smoothness_penalty(torch, trajectories):
    points = trajectories.reshape((trajectories.shape[0], trajectories.shape[1], FUTURE_WAYPOINTS, 2))
    second = points[:, :, 2:] - 2.0 * points[:, :, 1:-1] + points[:, :, :-2]
    return torch.mean(second * second, dim=(2, 3))


def _torch_feasibility_penalty(torch, trajectories):
    points = trajectories.reshape((trajectories.shape[0], trajectories.shape[1], FUTURE_WAYPOINTS, 2))
    deltas = points[:, :, 1:] - points[:, :, :-1]
    reverse = torch.relu(-deltas[:, :, :, 0]).mean(dim=2)
    lateral = torch.relu(torch.max(torch.abs(points[:, :, :, 1]), dim=2).values - 8.0)
    return reverse + 0.05 * lateral


def _torch_mode_diversity_reward(torch, trajectories):
    if trajectories.shape[1] < 2:
        return trajectories.new_tensor(0.0)
    points = trajectories.reshape((trajectories.shape[0], trajectories.shape[1], FUTURE_WAYPOINTS, 2))
    endpoint = points[:, :, -1, :]
    pairwise = torch.cdist(endpoint, endpoint, p=2)
    eye = torch.eye(pairwise.shape[1], device=pairwise.device, dtype=torch.bool).unsqueeze(0)
    pairwise = pairwise.masked_fill(eye, float("inf"))
    nearest = torch.min(pairwise, dim=2).values
    return torch.log1p(torch.clamp(nearest, max=12.0)).mean()


def _import_torch():
    try:
        import torch
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyTorch is required for neural system-2 WOD planner training/inference") from exc
    return torch


def _select_torch_device(torch, requested: str):
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("requested CUDA training, but torch.cuda.is_available() is false")
    if requested not in {"cpu", "cuda"}:
        raise ValueError("device must be one of: auto, cpu, cuda")
    return torch.device(requested)


class _TorchNeuralSystem2Planner:
    def __new__(
        cls,
        torch,
        *,
        hidden_dim: int,
        layers: int,
        heads: int,
        modes: int,
        external_embedding_dimension: int,
        decoder_type: str = "linear",
    ):
        class Model(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                if decoder_type not in {"linear", "mode_query"}:
                    raise ValueError("decoder_type must be one of: linear, mode_query")
                self.past_projection = torch.nn.Linear(2, hidden_dim)
                self.intent_embedding = torch.nn.Embedding(8, hidden_dim)
                self.speed_projection = torch.nn.Linear(1, hidden_dim)
                self.external_projection = (
                    torch.nn.Linear(external_embedding_dimension, hidden_dim)
                    if external_embedding_dimension > 0
                    else None
                )
                encoder_layer = torch.nn.TransformerEncoderLayer(
                    d_model=hidden_dim,
                    nhead=heads,
                    dim_feedforward=hidden_dim * 4,
                    dropout=0.05,
                    batch_first=True,
                    activation="gelu",
                )
                self.encoder = torch.nn.TransformerEncoder(encoder_layer, num_layers=layers)
                self.decoder_type = decoder_type
                if decoder_type == "mode_query":
                    self.mode_embedding = torch.nn.Embedding(modes, hidden_dim)
                    self.mode_decoder = torch.nn.Sequential(
                        torch.nn.Linear(hidden_dim * 2, hidden_dim),
                        torch.nn.GELU(),
                        torch.nn.Linear(hidden_dim, hidden_dim),
                        torch.nn.GELU(),
                    )
                    self.logit_head = torch.nn.Linear(hidden_dim, 1)
                    self.trajectory_head = torch.nn.Linear(hidden_dim, OUTPUT_DIM)
                else:
                    self.logit_head = torch.nn.Linear(hidden_dim, modes)
                    self.trajectory_head = torch.nn.Linear(hidden_dim, modes * OUTPUT_DIM)
                self.trajectory_encoder = torch.nn.Sequential(
                    torch.nn.Linear(OUTPUT_DIM, hidden_dim),
                    torch.nn.GELU(),
                    torch.nn.Linear(hidden_dim, hidden_dim),
                    torch.nn.GELU(),
                )
                self.critic_head = torch.nn.Sequential(
                    torch.nn.Linear(hidden_dim * 2, hidden_dim),
                    torch.nn.GELU(),
                    torch.nn.Linear(hidden_dim, 1),
                    torch.nn.Sigmoid(),
                )
                self.modes = modes

            def forward(self, past, intent, speed, external):
                tokens = [self.past_projection(past)]
                tokens.append(self.intent_embedding(torch.clamp(intent, 0, 7)).unsqueeze(1))
                tokens.append(self.speed_projection(speed).unsqueeze(1))
                if self.external_projection is not None:
                    tokens.append(self.external_projection(external).unsqueeze(1))
                encoded = self.encoder(torch.cat(tokens, dim=1))
                context = encoded.mean(dim=1)
                if self.decoder_type == "mode_query":
                    mode_indices = torch.arange(self.modes, device=context.device)
                    mode_tokens = self.mode_embedding(mode_indices).unsqueeze(0).expand((context.shape[0], -1, -1))
                    context_tokens = context[:, None, :].expand((-1, self.modes, -1))
                    mode_features = self.mode_decoder(torch.cat([context_tokens, mode_tokens], dim=2))
                    logits = self.logit_head(mode_features).squeeze(-1)
                    trajectories = self.trajectory_head(mode_features)
                else:
                    logits = self.logit_head(context)
                    trajectories = self.trajectory_head(context).reshape((-1, self.modes, OUTPUT_DIM))
                return context, logits, trajectories

            def score_candidates(self, context, trajectories):
                if trajectories.ndim != 3:
                    raise ValueError("trajectories must have shape [batch, candidates, output_dim]")
                candidate_count = trajectories.shape[1]
                traj_features = self.trajectory_encoder(trajectories.reshape((-1, OUTPUT_DIM)))
                context_features = context[:, None, :].expand((-1, candidate_count, -1)).reshape(
                    (-1, context.shape[1])
                )
                scores = self.critic_head(torch.cat([context_features, traj_features], dim=1))
                return scores.reshape((-1, candidate_count))

        return Model()
