# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 NVIDIA Corporation

"""Docker Compose deployment strategy."""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from alpasim_utils.paths import find_repo_root

from ..context import WizardContext
from ..schema import RunMode
from ..services import ContainerDefinition, build_container_set
from ..utils import LiteralStr, write_yaml

logger = logging.getLogger(__name__)


def _netrc_secret_file() -> Path | None:
    netrc_path = Path.home() / ".netrc"
    return netrc_path if netrc_path.is_file() else None


def _host_path_for_mount(volumes: list[str], container_path: str) -> str | None:
    """Host path bound to ``container_path``, or None if it is not mounted."""
    for mount in volumes:
        parts = mount.split(":", 2)
        if len(parts) < 2:
            continue
        host_path, mounted_path = parts[0], parts[1]
        if mounted_path == container_path:
            return host_path
    return None


def _normalize_single_run_runtime_command(command: str, volumes: list[str]) -> str:
    """Keep runtime aggregation in single-job mode when both mounts share one host dir.

    AlpaBridge runs one scene per invocation with --log-dir and --array-job-dir pointing
    at the same host directory. The runtime then writes its aggregate under
    /mnt/array_job_dir while everything else lands under /mnt/log_dir, so the aggregate
    ends up in a sibling path the run directory does not include. Collapsing the two when
    they are the same host directory keeps a single-run rollout's output self-contained.
    """

    log_dir_host = _host_path_for_mount(volumes, "/mnt/log_dir")
    array_job_dir_host = _host_path_for_mount(volumes, "/mnt/array_job_dir")
    if log_dir_host is None or array_job_dir_host is None:
        return command
    if Path(log_dir_host) != Path(array_job_dir_host):
        return command
    return command.replace("--array-job-dir=/mnt/array_job_dir", "--array-job-dir=/mnt/log_dir")


class DockerComposeDeployment:
    """Deployment strategy using Docker Compose."""

    def __init__(self, context: WizardContext):
        """Initialize with context and build container set.

        Args:
            context: The wizard context
        """
        self.context = context
        self.container_set = build_container_set(context, use_address_string="uuid")

    def generate_docker_compose(self) -> None:
        """Generates the docker-compose.yaml file.

        Note: This does not actually start the services. This can be done using
        ```bash
        docker compose up --exit-code-from runtime-0
        ```
        """
        self.docker_compose_filepath = self.generate_docker_compose_yaml(
            self.container_set
        )
        logger.info(
            "Docker Compose configuration generated in %s",
            self.context.cfg.wizard.log_dir,
        )

    def deploy_all_services(self) -> None:
        """Run docker compose up to deploy all services."""
        log_dir = self.context.cfg.wizard.log_dir
        compose_file = Path(log_dir) / self.docker_compose_filepath
        command = [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "up",
        ]
        if self.container_set.runtime:
            command.extend(
                [
                    "--remove-orphans",
                    "--exit-code-from",
                    "runtime-0",
                ]
            )

        if self.context.cfg.wizard.dry_run:
            logger.info("[DRY-RUN] Would execute: %s", shlex.join(command))
            return

        logger.info("Running docker compose: %s", compose_file)
        try:
            subprocess.run(
                command,
                check=True,
                cwd=log_dir,
            )
            logger.info("Docker Compose deployment completed successfully")
        except subprocess.CalledProcessError as e:
            logger.error(
                "Docker Compose deployment failed with return code: %s", e.returncode
            )
            raise

    def _to_docker_compose_service(
        self, container: ContainerDefinition
    ) -> dict[str, Any]:
        """Convert container to Docker Compose service definition.

        Args:
            container: ContainerDefinition instance

        Returns:
            Docker Compose service configuration dict
        """
        ret: dict[str, Any] = {}
        service_config = container.service_config
        use_host_network = self.context.cfg.wizard.debug_flags.use_localhost
        if use_host_network:
            # Tell Docker to use the host network
            ret["network_mode"] = "host"
        else:
            ret["networks"] = ["microservices_network"]
        ret["volumes"] = [v.to_str() for v in container.volumes]
        # AlpaBridge delta: local external-driver runs use images that are built here or
        # loaded from a local tar, never pulled -- an upstream default of "always" turns
        # every rollout into a registry round trip that fails without credentials.
        ret["pull_policy"] = "missing"
        ret["image"] = service_config.image

        repo_root = str(find_repo_root(__file__))

        if not service_config.external_image:
            build_config: dict[str, Any] = {
                "context": repo_root,
                "dockerfile": "Dockerfile",
                "tags": [service_config.image],
            }
            if _netrc_secret_file() is not None:
                build_config["secrets"] = ["netrc"]
            ret["build"] = build_config

        if container.command:
            ret["entrypoint"] = "bash"
            command = container.command
            # AlpaBridge delta, see _normalize_single_run_runtime_command.
            command = _normalize_single_run_runtime_command(command, ret["volumes"])
            # Escaping:
            # We use \$ to declare fields that should not be interpreted by
            # 'our' OmegaConf parser, but by downstream parsers in the service.
            # Furhtermore, for docker-compose, we need to escape $ as $$
            command = command.replace("$", "$$")
            # Set permissive umask so files written to bind-mounted volumes
            # are accessible by the host user (containers run as root).
            command = "umask 0000\n" + command
            # Use literal scalar string for multi-line commands to get | format in YAML
            if "\n" in command:
                command = LiteralStr(command)
            ret["command"] = ["-c", command]
        if container.workdir:
            ret["working_dir"] = container.workdir
        if container.environments:
            ret["environment"] = container.environments

        addresses = container.get_all_addresses()
        publish_runtime_server_port = (
            container.name == "runtime"
            and self.context.cfg.wizard.run_mode == RunMode.SERVER
        )
        ports: list[str] = []
        if not use_host_network and container.published_ports:
            ports.extend(
                f"{port}:{port}" for port in container.published_ports.values()
            )
        if addresses and (use_host_network or publish_runtime_server_port):
            ports.extend(f"{addr.port}:{addr.port}" for addr in addresses)
        if ports:
            ret["ports"] = ports

        if container.gpu is not None:
            ret["deploy"] = {
                "resources": {
                    "reservations": {
                        "devices": [
                            {
                                "driver": "nvidia",
                                "capabilities": ["gpu"],
                                "device_ids": [str(container.gpu)],
                            }
                        ]
                    }
                }
            }
        elif container.name == "prometheus" and self.context.num_gpus > 0:
            ret["deploy"] = {
                "resources": {
                    "reservations": {
                        "devices": [
                            {
                                "driver": "nvidia",
                                "count": "all",
                                "capabilities": ["gpu"],
                            }
                        ]
                    }
                }
            }
        return ret

    def generate_docker_compose_yaml(self, container_set: Any) -> str:
        """Generate docker-compose.yaml with services sorted by execution order.

        Args:
            container_set: ContainerSet instance with sim and runtime containers

        Returns:
            Filename of the generated docker-compose.yaml
        """
        # Build services in execution order
        services = {}

        # Simulation services (runtime should start last)
        for c in container_set.sim or []:
            if c.command == "noop":
                # Special logic to support renderer/physics combined process.
                continue
            service = self._to_docker_compose_service(c)
            services[c.uuid] = service

        service = self._to_docker_compose_service(container_set.prometheus)
        services[container_set.prometheus.uuid] = service

        # Add runtime service last
        if container_set.runtime is not None:
            service = self._to_docker_compose_service(container_set.runtime)
            # AlpaBridge deltas on the runtime service only:
            # - pid=host so the runtime can see and signal the external driver process
            #   running on the host rather than in a container namespace.
            # - all GPUs rather than one device id: with the driver external, the runtime
            #   still drives renderer/physics work that expects the full set.
            service["pid"] = "host"
            if any(container.gpu is not None for container in container_set.sim or []):
                service["deploy"] = {
                    "resources": {
                        "reservations": {
                            "devices": [
                                {
                                    "driver": "nvidia",
                                    "count": "all",
                                    "capabilities": ["gpu"],
                                }
                            ]
                        }
                    }
                }
            services[container_set.runtime.uuid] = service

        # Create compose structure with ordered services
        compose: dict[str, Any] = {
            "networks": {"microservices_network": {"driver": "bridge"}},
            "services": services,  # Services maintain insertion order in Python 3.7+
        }
        if _netrc_secret_file() is not None:
            compose["secrets"] = {"netrc": {"file": "${HOME}/.netrc"}}

        # Write to file
        filename = "docker-compose.yaml"
        log_dir = Path(self.context.cfg.wizard.log_dir)
        logger.info("Writing docker compose YAML to %s/%s", log_dir, filename)
        os.makedirs(log_dir, exist_ok=True)
        write_yaml(compose, str(log_dir / filename))
        return filename
