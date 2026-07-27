"""Extension point for policies servable behind AlpaBridge's AlpaSim driver service.

Every registered policy is served behind the same gRPC service, session
tracking, telemetry, and replica handling in ``driver_service.py`` - none of
that machinery is specific to any one policy. Register a new one with
``register_policy`` instead of editing ``AlpaBridgeDriverService`` directly,
and it becomes selectable the same way as any built-in model. Any
``BaseTrajectoryModel``-compatible policy can be evaluated through the same
interface this way, for research and benchmarking as much as for competition
(the AlpaSim E2E challenge is one deployment target among others).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Protocol


class PolicyContext(Protocol):
    model_camera_id: str
    checkpoint_path: Any
    tokenizer_checkpoint_path: Any
    device: str
    output_frequency_hz: int
    horizon_seconds: float


PolicyFactory = Callable[["PolicyContext"], Any]


@dataclass(frozen=True)
class DriverPolicy:
    name: str
    factory: PolicyFactory
    requires_checkpoint: bool = False
    requires_tokenizer_checkpoint: bool = False


_REGISTRY: dict[str, DriverPolicy] = {}


def register_policy(policy: DriverPolicy) -> None:
    if policy.name in _REGISTRY:
        raise ValueError(f"policy {policy.name!r} is already registered")
    _REGISTRY[policy.name] = policy


def available_policy_names() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def build_policy(name: str, adapter: PolicyContext) -> Any:
    policy = _REGISTRY.get(name)
    if policy is None:
        raise ValueError(f"Unsupported policy: {name}")
    if policy.requires_checkpoint and adapter.checkpoint_path is None:
        raise ValueError(f"{name} requires a checkpoint path")
    if policy.requires_tokenizer_checkpoint and adapter.tokenizer_checkpoint_path is None:
        raise ValueError(f"{name} requires a tokenizer checkpoint path")
    return policy.factory(adapter)


def _resample_config(adapter: PolicyContext) -> SimpleNamespace:
    return SimpleNamespace(
        horizon_seconds=adapter.horizon_seconds,
        point_count=int(round(adapter.output_frequency_hz * adapter.horizon_seconds)),
    )


def _build_constant_velocity(adapter: PolicyContext) -> Any:
    from alpabridge.simulator.baseline_drivers import ConstantVelocityAlpaSimModel

    return ConstantVelocityAlpaSimModel(
        camera_ids=[adapter.model_camera_id],
        context_length=1,
        output_frequency_hz=adapter.output_frequency_hz,
        config=_resample_config(adapter),
    )


def _build_route_following(adapter: PolicyContext) -> Any:
    from alpabridge.simulator.baseline_drivers import RouteFollowingAlpaSimModel

    return RouteFollowingAlpaSimModel(
        camera_ids=[adapter.model_camera_id],
        context_length=1,
        output_frequency_hz=adapter.output_frequency_hz,
        config=_resample_config(adapter),
    )


def _build_token_dagger_bc(adapter: PolicyContext) -> Any:
    from alpabridge.simulator.alpasim_token_bc import TokenBCAlpaSimModel

    return TokenBCAlpaSimModel(
        checkpoint_path=adapter.checkpoint_path,
        device=adapter.device,
        camera_ids=[adapter.model_camera_id],
        context_length=1,
        output_frequency_hz=adapter.output_frequency_hz,
    )


def _build_navsim_ego_status_mlp(adapter: PolicyContext) -> Any:
    from alpabridge.simulator.navsim_ego_status_mlp import NavsimEgoStatusMLPModel

    return NavsimEgoStatusMLPModel(
        checkpoint_path=adapter.checkpoint_path,
        device=adapter.device,
        camera_ids=[adapter.model_camera_id],
    )


def _build_vavam(adapter: PolicyContext) -> Any:
    from alpabridge.simulator.vavam_model import VAVAMAlpaSimModel

    return VAVAMAlpaSimModel(
        checkpoint_path=adapter.checkpoint_path,
        tokenizer_checkpoint_path=adapter.tokenizer_checkpoint_path,
        device=adapter.device,
        camera_ids=[adapter.model_camera_id],
        output_frequency_hz=adapter.output_frequency_hz,
        horizon_seconds=adapter.horizon_seconds,
    )


register_policy(DriverPolicy("constant_velocity", _build_constant_velocity))
register_policy(DriverPolicy("route_following", _build_route_following))
register_policy(
    DriverPolicy("token_dagger_bc", _build_token_dagger_bc, requires_checkpoint=True)
)
register_policy(
    DriverPolicy(
        "navsim_ego_status_mlp", _build_navsim_ego_status_mlp, requires_checkpoint=True
    )
)
register_policy(
    DriverPolicy(
        "vavam",
        _build_vavam,
        requires_checkpoint=True,
        requires_tokenizer_checkpoint=True,
    )
)
