from __future__ import annotations

import pytest

from alpabridge.driver.policy_registry import (
    DriverPolicy,
    _env_float,
    _env_float_tuple,
    available_policy_names,
    build_policy,
    register_policy,
)


def test_available_policy_names_includes_all_built_in_policies() -> None:
    names = available_policy_names()

    assert set(names) == {
        "constant_velocity",
        "route_following",
        "mpc_planner",
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
    from alpabridge.simulator.mpc_planner import MPCPlannerAlpaSimModel

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
    mpc_planner = build_policy("mpc_planner", adapter)

    assert isinstance(constant_velocity, ConstantVelocityAlpaSimModel)
    assert isinstance(route_following, RouteFollowingAlpaSimModel)
    assert isinstance(mpc_planner, MPCPlannerAlpaSimModel)
    for policy in (constant_velocity, route_following, mpc_planner):
        assert policy.camera_ids == ["front"]
        assert policy.output_frequency_hz == 10
    assert mpc_planner._config.horizon_seconds == 5.0
    assert mpc_planner._config.point_count == 50


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


class TestEnvOverrides:
    """The MPC tuning knobs are only reachable through the environment when the
    driver runs behind gRPC, so the parsing has to be defensive: a typo in a
    container env var must not take a driver down mid-evaluation, and must not
    quietly reach the planner either."""

    def test_scalar_override_is_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALPABRIDGE_TEST_SCALAR", "11.5")

        assert _env_float("ALPABRIDGE_TEST_SCALAR", 8.0) == 11.5

    def test_scalar_falls_back_when_unset_or_blank(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ALPABRIDGE_TEST_SCALAR", raising=False)
        assert _env_float("ALPABRIDGE_TEST_SCALAR", 8.0) == 8.0

        monkeypatch.setenv("ALPABRIDGE_TEST_SCALAR", "   ")
        assert _env_float("ALPABRIDGE_TEST_SCALAR", 8.0) == 8.0

    @pytest.mark.parametrize("raw", ["junk", "-3", "0", "nan", "inf", "-inf"])
    def test_scalar_rejects_unusable_values(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        """nan is the subtle one: every comparison against it is False, so a
        bare `value <= 0` guard lets it through to the planner."""
        monkeypatch.setenv("ALPABRIDGE_TEST_SCALAR", raw)

        assert _env_float("ALPABRIDGE_TEST_SCALAR", 8.0) == 8.0

    def test_tuple_override_is_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALPABRIDGE_TEST_TUPLE", "-4,-2,0,2,4,6")

        assert _env_float_tuple("ALPABRIDGE_TEST_TUPLE", (1.0,)) == (
            -4.0,
            -2.0,
            0.0,
            2.0,
            4.0,
            6.0,
        )

    def test_tuple_keeps_zero_and_negative_candidates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Decelerations and left yaw rates are meaningful, so unlike the scalar
        knobs a candidate set must not be filtered for positivity."""
        monkeypatch.setenv("ALPABRIDGE_TEST_TUPLE", "-2.5,0,1.5")

        assert _env_float_tuple("ALPABRIDGE_TEST_TUPLE", (1.0,)) == (-2.5, 0.0, 1.5)

    @pytest.mark.parametrize("raw", ["junk,2", " , , ", "", "1.0,nan", "2,inf"])
    def test_tuple_rejects_unusable_sets(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        default = (-2.5, -1.0, 0.0, 1.0, 1.5)
        monkeypatch.setenv("ALPABRIDGE_TEST_TUPLE", raw)

        assert _env_float_tuple("ALPABRIDGE_TEST_TUPLE", default) == default
