from __future__ import annotations

import pytest

from alpabridge.driver.policy_registry import (
    DriverPolicy,
    available_policy_names,
    build_policy,
    register_policy,
)


def test_available_policy_names_includes_all_built_in_policies() -> None:
    names = available_policy_names()

    assert set(names) == {
        "constant_velocity",
        "route_following",
        "token_dagger_bc",
        "navsim_ego_status_mlp",
        "vavam",
    }


def test_build_policy_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="Unsupported policy"):
        build_policy("not-a-real-policy", adapter=object())


def test_register_policy_rejects_duplicate_name() -> None:
    with pytest.raises(ValueError, match="already registered"):
        register_policy(DriverPolicy("route_following", factory=lambda adapter: None))


def test_build_policy_constructs_a_real_correctly_configured_baseline() -> None:
    from types import SimpleNamespace

    from alpabridge.simulator.baseline_drivers import (
        ConstantVelocityAlpaSimModel,
        RouteFollowingAlpaSimModel,
    )

    adapter = SimpleNamespace(
        model_camera_id="front",
        checkpoint_path=None,
        tokenizer_checkpoint_path=None,
        device="cpu",
        output_frequency_hz=10,
        horizon_seconds=5.0,
    )

    constant_velocity = build_policy("constant_velocity", adapter)
    route_following = build_policy("route_following", adapter)

    assert isinstance(constant_velocity, ConstantVelocityAlpaSimModel)
    assert isinstance(route_following, RouteFollowingAlpaSimModel)
    for policy in (constant_velocity, route_following):
        assert policy.camera_ids == ["front"]
        assert policy.output_frequency_hz == 10


def test_build_policy_enforces_checkpoint_requirements_before_constructing() -> None:
    from types import SimpleNamespace

    called = []
    register_policy(
        DriverPolicy(
            "test_only_requires_both",
            factory=lambda adapter: called.append(adapter),
            requires_checkpoint=True,
            requires_tokenizer_checkpoint=True,
        )
    )
    try:
        adapter = SimpleNamespace(checkpoint_path=None, tokenizer_checkpoint_path=None)
        with pytest.raises(ValueError, match="requires a checkpoint path"):
            build_policy("test_only_requires_both", adapter)

        adapter = SimpleNamespace(checkpoint_path="present.pt", tokenizer_checkpoint_path=None)
        with pytest.raises(ValueError, match="requires a tokenizer checkpoint path"):
            build_policy("test_only_requires_both", adapter)

        adapter = SimpleNamespace(checkpoint_path="present.pt", tokenizer_checkpoint_path="present.jit")
        build_policy("test_only_requires_both", adapter)
        assert called == [adapter]
    finally:
        from alpabridge.driver import policy_registry

        del policy_registry._REGISTRY["test_only_requires_both"]
