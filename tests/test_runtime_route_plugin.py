"""Exercise AlpaSim PR #179 through the real AlpaBridge gRPC driver.

Requires an installed AlpaSim runtime with route-generator plugin support.
The authored route is a test fixture in a synthetic shared coordinate frame;
this does not validate rendering, physics, or road validity in a dataset scene.
"""

from __future__ import annotations

import asyncio
import io
import math
from concurrent import futures
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

pytest.importorskip("alpasim_runtime")
plugins = pytest.importorskip("alpasim_plugins")
if not hasattr(plugins, "route_generators"):
    pytest.skip("Requires AlpaSim PR #179", allow_module_level=True)

import grpc  # noqa: E402
from alpasim_grpc import API_VERSION_MESSAGE  # noqa: E402
from alpasim_grpc.v0 import common_pb2, egodriver_pb2, egodriver_pb2_grpc  # noqa: E402
from alpasim_grpc.v0.logging_pb2 import RolloutMetadata  # noqa: E402
from alpasim_runtime.broadcaster import MessageBroadcaster  # noqa: E402
from alpasim_runtime.config import (  # noqa: E402
    RouteGeneratorType,
    RuntimeCameraConfig,
    SimulationConfig,
    VehicleConfig,
)
from alpasim_runtime.event_loop import EventBasedRollout  # noqa: E402
from alpasim_runtime.events.base import EventQueue  # noqa: E402
from alpasim_runtime.events.policy import PolicyEvent  # noqa: E402
from alpasim_runtime.events.state import ServiceBundle  # noqa: E402
from alpasim_runtime.route_generator import RouteGenerator, RouteGeneratorRecorded  # noqa: E402
from alpasim_runtime.services.driver_service import DriverService  # noqa: E402
from alpasim_runtime.services.sensorsim_service import SensorsimService  # noqa: E402
from alpasim_runtime.services.session_configs import DriverSessionConfig  # noqa: E402
from alpasim_runtime.unbound_rollout import UnboundRollout  # noqa: E402
from alpasim_utils.geometry import Pose, Trajectory  # noqa: E402
from alpasim_utils.scenario import CameraId, Rig, TrafficObjects  # noqa: E402
from alpasim_utils.types import ImageWithMetadata  # noqa: E402
from omegaconf import OmegaConf  # noqa: E402
from PIL import Image  # noqa: E402

from alpabridge.driver.driver_service import (  # noqa: E402
    AlpaBridgeDriverService,
    _build_service_class,
)
from alpabridge.simulator.environment import Scenario, route_centerline  # noqa: E402


class AuthoredTurnRoute(RouteGeneratorRecorded):
    """A fixed alternate route used only to validate the integration boundary."""

    @classmethod
    def from_context(cls, recorded_waypoints_in_local, vector_map, *, route_start_offset_m=0.0):
        scenario = Scenario(
            width=120.0,
            height=60.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0), (25.0, 15.0), (60.0, 20.0), (110.0, 20.0)],
            lane_half_width=3.5,
            obstacles=[],
            start=(0.0, 0.0),
            goal=(110.0, 20.0),
            seed=0,
        )
        route = np.array([(x, y, 0.0) for x, y in route_centerline(scenario)])
        # Place the synthetic scenario at the recording's initial position/heading.
        direction = recorded_waypoints_in_local[1] - recorded_waypoints_in_local[0]
        yaw = math.atan2(direction[1], direction[0])
        rotation = np.array(
            [
                [math.cos(yaw), -math.sin(yaw), 0.0],
                [math.sin(yaw), math.cos(yaw), 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        route = route @ rotation.T + recorded_waypoints_in_local[0]
        return cls(route, route_start_offset_m=route_start_offset_m)


@pytest.fixture
def route_plugin(tmp_path, monkeypatch):
    metadata = tmp_path / "alpabridge_test_route-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: alpabridge-test-route\nVersion: 1.0\n"
    )
    (metadata / "entry_points.txt").write_text(
        f"[alpasim.route_generators]\nalpabridge-test-turn = {__name__}:AuthoredTurnRoute\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(plugins.route_generators, "_cache", None)
    # Evaluation is unrelated to transport and would require extra artifacts.
    monkeypatch.setattr("alpasim_runtime.event_loop.RuntimeEvaluator", MagicMock())


@pytest.fixture
def route_driver():
    adapter = AlpaBridgeDriverService(model_name="route_following", camera_ids=("front",))
    service_cls = _build_service_class(
        grpc=grpc,
        api_version_message=API_VERSION_MESSAGE,
        common_pb2=common_pb2,
        egodriver_pb2=egodriver_pb2,
        egodriver_pb2_grpc=egodriver_pb2_grpc,
    )
    with futures.ThreadPoolExecutor(max_workers=4) as executor:
        server = grpc.server(executor)
        service = service_cls(adapter)
        egodriver_pb2_grpc.add_EgodriverServiceServicer_to_server(service, server)
        service.attach_server(server)
        port = server.add_insecure_port("127.0.0.1:0")
        assert port
        server.start()
        try:
            yield adapter, f"127.0.0.1:{port}"
        finally:
            server.stop(grace=0).wait()


def _scene(yaw):
    timestamps = np.arange(0, 6_000_001, 100_000, dtype=np.uint64)
    quaternion = np.array([0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2)])
    trajectory = Trajectory.from_poses(
        timestamps=timestamps,
        poses=[
            Pose(
                np.array([100 + 5 * t / 1e6 * math.cos(yaw), 50 + 5 * t / 1e6 * math.sin(yaw), 0]),
                quaternion,
            )
            for t in timestamps
        ],
    )
    rig = Rig(
        sequence_id="synthetic-route-test",
        trajectory=trajectory,
        camera_ids=[CameraId("front", 0, "synthetic-route-test", "front-id")],
        camera_frame_timestamps_us={"front-id": [1_000_000]},
        camera_frame_ranges_us={"front-id": [range(900_000, 1_000_000)]},
        world_to_nre=np.eye(4),
        vehicle_config=VehicleConfig(),
    )
    return SimpleNamespace(
        rig=rig,
        traffic_objects=TrafficObjects(),
        source="synthetic",
        metadata=SimpleNamespace(
            logger=SimpleNamespace(run_id="test"), version_string="test", uuid="test"
        ),
        map=None,
    )


@pytest.mark.parametrize("yaw", [0.0, math.pi / 2])
@pytest.mark.parametrize("offset", [0.0, 8.0])
def test_custom_route_reaches_alpabridge_over_grpc(
    route_plugin, route_driver, tmp_path, yaw, offset
):
    adapter, address = route_driver

    async def run():
        lateral_endpoints = []
        for plugin_name in (None, "alpabridge-test-turn"):
            # Exercise structured config conversion and both rollout construction layers.
            cfg = OmegaConf.structured(
                SimulationConfig(
                    n_sim_steps=3,
                    n_rollouts=1,
                    control_timestep_us=100_000,
                    force_gt_duration_us=0,
                    cameras=[RuntimeCameraConfig(logical_id="front")],
                    route_generator_type=RouteGeneratorType.RECORDED
                    if plugin_name is None
                    else RouteGeneratorType.NONE,
                    route_generator_plugin=plugin_name,
                    route_start_offset_m=offset,
                )
            )
            source = _scene(yaw)
            renderer = SensorsimService(
                address="unused", skip=True, camera_catalog=SimpleNamespace()
            )
            unbound = UnboundRollout.create(
                simulation_config=OmegaConf.to_object(cfg),
                scene_id="synthetic-route-test",
                version_ids=RolloutMetadata.VersionIds(),
                data_source=source,
                rollouts_dir=str(tmp_path),
                renderer_service=renderer,
            )
            np.testing.assert_array_equal(
                unbound.gt_ego_trajectory.positions, source.rig.trajectory.positions
            )
            driver = DriverService(address=address)
            rollout = EventBasedRollout(
                unbound=unbound,
                data_source=source,
                driver=driver,
                renderer_service=renderer,
                physics=MagicMock(),
                trafficsim=MagicMock(),
                controller=MagicMock(),
                camera_catalog=MagicMock(),
                eval_config=MagicMock(),
                eval_executor=MagicMock(),
            )
            if plugin_name:
                assert isinstance(rollout.route_generator, AuthoredTurnRoute)
            state = rollout._create_rollout_state()
            timestamp = unbound.first_policy_timestamp_us
            services = ServiceBundle(
                driver=driver,
                controller=rollout.controller,
                physics=rollout.physics,
                trafficsim=rollout.trafficsim,
                broadcaster=MessageBroadcaster(),
                planner_delay_buffer=rollout.planner_delay_buffer,
            )
            async with driver.rollout_session(
                uuid=unbound.rollout_uuid,
                broadcaster=services.broadcaster,
                session_config=DriverSessionConfig(
                    sensorsim_cameras=[], scene_id=unbound.scene_id, random_seed=7
                ),
            ):
                image = io.BytesIO()
                Image.new("RGB", (8, 8), (150, 150, 150)).save(image, format="PNG")
                await driver.submit_image(
                    ImageWithMetadata(timestamp, timestamp, image.getvalue(), "front")
                )
                event = PolicyEvent(
                    timestamp_us=timestamp,
                    policy_timestep_us=100_000,
                    services=services,
                    camera_ids=["front"],
                    route_generator=rollout.route_generator,
                    send_recording_ground_truth=False,
                )
                await event.run(state, EventQueue())
                expected = RouteGenerator.prepare_for_policy(
                    rollout.route_generator.generate_route(
                        timestamp, state.ego_trajectory.last_pose
                    )
                ).waypoints
                # A short recorded route can end in NaNs; the driver drops those.
                expected = expected[np.all(np.isfinite(expected), axis=1)]
                received = adapter.prediction_input(
                    unbound.rollout_uuid, time_now_us=timestamp
                ).route_waypoints
                np.testing.assert_allclose(
                    [[point["x"], point["y"], point["z"]] for point in received],
                    expected,
                    # Float32 local/rig transforms accumulate sub-millimetre error.
                    atol=1e-4,
                )
                prediction = state.step_context.driver_trajectory.transform(
                    state.ego_trajectory.last_pose.inverse()
                )
                lateral_endpoints.append(prediction.positions[-1, 1])
            assert driver.session_info is None
            assert driver.channel is None
        assert abs(lateral_endpoints[0]) < 1e-4
        assert lateral_endpoints[1] > 5.0

    asyncio.run(asyncio.wait_for(run(), timeout=30))
