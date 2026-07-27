"""Proves a generic gRPC client - not AlpaSim's own wizard - can drive a
session against the standalone driver, using nothing but the public
egodriver.EgodriverService interface.

Requires the AlpaSim gRPC package (``alpasim_grpc`` + ``grpc``), which isn't
vendored into AlpaBridge - skipped when it isn't installed, the same way
other AlpaSim-checkout-dependent tests in this repo are.
"""

from __future__ import annotations

from concurrent import futures

import pytest

grpc = pytest.importorskip("grpc")
alpasim_grpc = pytest.importorskip("alpasim_grpc")
from alpasim_grpc.v0 import common_pb2, egodriver_pb2, egodriver_pb2_grpc  # noqa: E402

from alpabridge.driver.driver_service import (  # noqa: E402
    AlpaBridgeDriverService,
    _build_service_class,
)


@pytest.fixture
def driver_port():
    adapter = AlpaBridgeDriverService(model_name="constant_velocity")
    service_cls = _build_service_class(
        grpc=grpc,
        api_version_message=alpasim_grpc.API_VERSION_MESSAGE,
        common_pb2=common_pb2,
        egodriver_pb2=egodriver_pb2,
        egodriver_pb2_grpc=egodriver_pb2_grpc,
    )
    service = service_cls(adapter)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    egodriver_pb2_grpc.add_EgodriverServiceServicer_to_server(service, server)
    service.attach_server(server)
    port = server.add_insecure_port("127.0.0.1:0")
    assert port != 0
    server.start()
    try:
        yield port
    finally:
        server.stop(grace=0.0)


def test_generic_grpc_client_drives_one_full_session(driver_port: int) -> None:
    """A plain grpc client (not alpasim_wizard) exercises the real interface."""
    channel = grpc.insecure_channel(f"127.0.0.1:{driver_port}")
    stub = egodriver_pb2_grpc.EgodriverServiceStub(channel)
    session_uuid = "generic-client-test"

    version = stub.get_version(common_pb2.Empty())
    assert version.version_id.startswith("alpabridge-driver-")

    stub.start_session(egodriver_pb2.DriveSessionRequest(session_uuid=session_uuid))

    stub.submit_image_observation(
        egodriver_pb2.RolloutCameraImage(
            session_uuid=session_uuid,
            camera_image=egodriver_pb2.RolloutCameraImage.CameraImage(
                frame_end_us=1_000_000, image_bytes=b""
            ),
        )
    )
    stub.submit_egomotion_observation(
        egodriver_pb2.RolloutEgoTrajectory(
            session_uuid=session_uuid,
            trajectory=common_pb2.Trajectory(
                poses=[
                    common_pb2.PoseAtTime(
                        timestamp_us=1_000_000,
                        pose=common_pb2.Pose(
                            vec=common_pb2.Vec3(x=0.0, y=0.0, z=0.0),
                            quat=common_pb2.Quat(w=1.0, x=0.0, y=0.0, z=0.0),
                        ),
                    )
                ]
            ),
        )
    )
    stub.submit_route(
        egodriver_pb2.RouteRequest(
            session_uuid=session_uuid,
            route=egodriver_pb2.Route(timestamp_us=1_000_000),
        )
    )

    response = stub.drive(
        egodriver_pb2.DriveRequest(session_uuid=session_uuid, time_now_us=1_100_000)
    )
    assert len(response.trajectory.poses) > 0

    stub.close_session(egodriver_pb2.DriveSessionCloseRequest(session_uuid=session_uuid))
