"""Extension point for policies servable behind AlpaBridge's AlpaSim driver service.

Every registered policy is served behind the same gRPC service, session
tracking, telemetry, and replica handling in ``driver_service.py`` - none of
that machinery is specific to any one policy. Register a new one with
``register_policy`` instead of editing ``AlpaBridgeDriverService`` directly,
and it becomes selectable the same way as any built-in model. Any
``BaseTrajectoryModel``-compatible policy can be evaluated through the same
interface this way, for research and benchmarking as much as for competition
(the AlpaSim E2E challenge is one deployment target among others).

Why this registry exists separately from the in-process ``alpasim.models``
entry points (see ``pyproject.toml``), instead of one shared registration
point: the two paths configure a policy from genuinely different sources.
In-process, AlpaSim calls ``SomeModel.from_config(model_cfg, ...)`` with a
Hydra config object loaded from a YAML file - and real models read many
config-specific fields there (``TokenBCAlpaSimModel.from_config`` alone
reads six, several with their own env-var overrides). The standalone
driver has no Hydra runtime at all - its configuration is plain CLI flags
(``PolicyContext`` below). A generic bridge from one to the other would
mean faking an entire Hydra config per model, which is more fragile than
just writing the two factories directly - so this registry constructs
each policy's plain constructor itself rather than routing through
``from_config``. Where policies genuinely share a construction shape (the
two dependency-light baselines below), one factory is parameterized by
class instead of copied - that duplication was accidental, this one isn't.
"""

from __future__ import annotations

import importlib
import logging
import math
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Protocol

LOGGER = logging.getLogger("alpabridge_policy_registry")


def _env_float(name: str, default: float) -> float:
    """Read a float tuning override from the environment.

    The standalone driver has no Hydra config, so values that `from_config`
    exposes to in-process users are otherwise unreachable behind the gRPC
    boundary — reachable only by editing this file and rebuilding the image.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        LOGGER.warning("%s=%r is not a number; using %s", name, raw, default)
        return default
    # NaN fails every comparison, so `value <= 0` does not reject it and it would
    # reach the planner and poison candidate rollouts silently. inf passes the
    # positivity check for the same reason it is useless as a speed.
    if not math.isfinite(value) or value <= 0:
        LOGGER.warning(
            "%s=%s must be a positive finite number; using %s", name, value, default
        )
        return default
    return value


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


def load_external_policy_modules(spec: str | None = None) -> tuple[str, ...]:
    """Import modules named in ``ALPABRIDGE_EXTRA_POLICY_MODULES`` so their
    ``register_policy`` calls run before the CLI enumerates the choices.

    The registry is populated by import side effect, which works fine for the
    policies that ship here but leaves out-of-tree ones unreachable: the
    standalone driver's ``--model`` choices are built from
    ``available_policy_names()`` inside ``main()``, so a policy defined in
    another distribution is never offered unless something imported it first.
    Callers could wrap ``main()`` in their own entry point to do that, but then
    every deployment reimplements the same shim. A comma-separated module list
    is the smaller contract, and it keeps policies that are not ours out of
    this file.

    Import failures are fatal rather than warned past: a driver that silently
    starts on a different policy than the operator asked for is worse than one
    that refuses to start.
    """
    raw = os.environ.get("ALPABRIDGE_EXTRA_POLICY_MODULES") if spec is None else spec
    if not raw or not raw.strip():
        return ()
    loaded: list[str] = []
    for name in (part.strip() for part in raw.split(",")):
        if not name:
            continue
        importlib.import_module(name)
        LOGGER.info("imported external policy module %s", name)
        loaded.append(name)
    return tuple(loaded)


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


def _baseline_factory(model_cls: type) -> PolicyFactory:
    """Both dependency-light baselines share this exact construction shape -
    one real factory, parameterized by class, instead of two copies."""

    def factory(adapter: PolicyContext) -> Any:
        return model_cls(
            camera_ids=[adapter.model_camera_id],
            context_length=1,
            output_frequency_hz=adapter.output_frequency_hz,
            config=_resample_config(adapter),
        )

    return factory


def _build_constant_velocity(adapter: PolicyContext) -> Any:
    from alpabridge.simulator.baseline_drivers import ConstantVelocityAlpaSimModel

    return _baseline_factory(ConstantVelocityAlpaSimModel)(adapter)


def _build_route_following(adapter: PolicyContext) -> Any:
    from alpabridge.simulator.baseline_drivers import RouteFollowingAlpaSimModel

    return _baseline_factory(RouteFollowingAlpaSimModel)(adapter)


def _env_float_tuple(name: str, default: tuple[float, ...]) -> tuple[float, ...]:
    """Read a comma-separated float tuple override from the environment.

    Candidate sets, unlike scalars, cannot be usefully clamped: an empty or
    unparseable set would leave the planner with nothing to choose from, and
    MPCPlannerConfig rejects that outright. So anything malformed warns and
    falls back to the default rather than raising mid-rollout.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        values = tuple(float(part) for part in raw.split(",") if part.strip())
    except ValueError:
        LOGGER.warning("%s=%r is not a comma-separated float list; using %s", name, raw, default)
        return default
    if not values:
        LOGGER.warning("%s=%r parsed to an empty set; using %s", name, raw, default)
        return default
    # Candidate sets are allowed to contain zero and negatives — decelerations and
    # left yaw rates are meaningful — so only finiteness is checked here.
    if not all(math.isfinite(value) for value in values):
        LOGGER.warning(
            "%s=%r contains a non-finite value; using %s", name, raw, default
        )
        return default
    return values


def _build_mpc_planner(adapter: PolicyContext) -> Any:
    from alpabridge.simulator.mpc_planner import MPCPlannerAlpaSimModel, MPCPlannerConfig

    resample = _resample_config(adapter)
    defaults = MPCPlannerConfig()
    accels_mps2 = _env_float_tuple(
        "ALPABRIDGE_MPC_ACCELS_MPS2", defaults.accels_mps2
    )
    yaw_rates_rps = _env_float_tuple(
        "ALPABRIDGE_MPC_YAW_RATES_RPS", defaults.yaw_rates_rps
    )
    max_speed_mps = _env_float(
        "ALPABRIDGE_MPC_MAX_SPEED_MPS", defaults.max_speed_mps
    )
    cruise_speed_mps = _env_float(
        "ALPABRIDGE_MPC_CRUISE_SPEED_MPS", defaults.target_cruise_speed_mps
    )
    if cruise_speed_mps > max_speed_mps:
        LOGGER.warning(
            "cruise speed %s exceeds max speed %s; clamping",
            cruise_speed_mps,
            max_speed_mps,
        )
        cruise_speed_mps = max_speed_mps

    return MPCPlannerAlpaSimModel(
        camera_ids=[adapter.model_camera_id],
        context_length=1,
        output_frequency_hz=adapter.output_frequency_hz,
        config=MPCPlannerConfig(
            horizon_seconds=resample.horizon_seconds,
            point_count=resample.point_count,
            max_speed_mps=max_speed_mps,
            target_cruise_speed_mps=cruise_speed_mps,
            accels_mps2=accels_mps2,
            yaw_rates_rps=yaw_rates_rps,
        ),
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


def _build_direct_actor_planner(adapter: PolicyContext) -> Any:
    from alpabridge.simulator.alpasim_direct_actor_planner import (
        DirectActorPlannerAlpaSimModel,
        DirectPlannerConfig,
    )

    resample = _resample_config(adapter)
    defaults = DirectPlannerConfig()
    # speed_scales are multipliers on the *current* speed, so the stock ceiling
    # of 1.2 caps this planner at 1.2x whatever speed the session began with -
    # the same longitudinal ceiling the route follower's ramp exists to lift.
    # Exposing both candidate sets is what makes that testable from a container.
    speed_scales = _env_float_tuple(
        "ALPABRIDGE_DAP_SPEED_SCALES", defaults.speed_scales
    )
    lateral_offsets_m = _env_float_tuple(
        "ALPABRIDGE_DAP_LATERAL_OFFSETS_M", defaults.lateral_offsets_m
    )

    return DirectActorPlannerAlpaSimModel(
        camera_ids=[adapter.model_camera_id],
        context_length=1,
        output_frequency_hz=adapter.output_frequency_hz,
        planner_config=DirectPlannerConfig(
            horizon_seconds=resample.horizon_seconds,
            point_count=resample.point_count,
            speed_scales=speed_scales,
            lateral_offsets_m=lateral_offsets_m,
        ),
    )


register_policy(DriverPolicy("constant_velocity", _build_constant_velocity))
register_policy(DriverPolicy("direct_actor_planner", _build_direct_actor_planner))
register_policy(DriverPolicy("route_following", _build_route_following))
register_policy(DriverPolicy("mpc_planner", _build_mpc_planner))
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
