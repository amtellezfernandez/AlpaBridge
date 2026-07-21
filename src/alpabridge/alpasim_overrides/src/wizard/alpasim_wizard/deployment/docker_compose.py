# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 NVIDIA Corporation

"""Docker Compose deployment strategy."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from alpasim_utils.paths import find_repo_root

from ..context import WizardContext
from ..services import ContainerDefinition, build_container_set
from ..utils import LiteralStr, write_yaml

logger = logging.getLogger(__name__)


def _host_path_for_mount(volumes: list[str], container_path: str) -> str | None:
    for mount in volumes:
        parts = mount.split(":", 2)
        if len(parts) < 2:
            continue
        host_path, mounted_path = parts[0], parts[1]
        if mounted_path == container_path:
            return host_path
    return None


def _normalize_single_run_runtime_command(command: str, volumes: list[str]) -> str:
    """Keep runtime aggregation in single-job mode when both mounts share one host dir."""

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
        docker compose up
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
        logger.info("Running docker compose: %s", compose_file)

        try:
            subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "up"],
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
        use_host_network = self.context.cfg.wizard.debug_flags.use_localhost
        if use_host_network:
            ret["network_mode"] = "host"
        else:
            ret["networks"] = ["microservices_network"]
        ret["volumes"] = [v.to_str() for v in container.volumes]
        ret["pull_policy"] = "missing"
        ret["image"] = container.service_config.image

        repo_root = str(find_repo_root(__file__))

        if not container.service_config.external_image:
            build_config: dict[str, Any] = {
                "context": repo_root,
                "dockerfile": "Dockerfile",
                "tags": [container.service_config.image],
            }
            if Path.home().joinpath(".netrc").exists():
                build_config["secrets"] = ["netrc"]
            ret["build"] = build_config

        if container.command:
            ret["entrypoint"] = "bash"
            command = container.command
            command = _normalize_single_run_runtime_command(command, ret["volumes"])
            command = command.replace(r"\$", "$$")
            command = "umask 0000\n" + command
            if "\n" in command:
                command = LiteralStr(command)
            ret["command"] = ["-c", command]
        if container.workdir:
            ret["working_dir"] = container.workdir
        if container.environments:
            ret["environment"] = container.environments

        addresses = container.get_all_addresses()
        if addresses and use_host_network:
            ports = [f"{addr.port}:{addr.port}" for addr in addresses]
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
        return ret

    def generate_docker_compose_yaml(self, container_set: Any) -> str:
        """Generate docker-compose.yaml with services sorted by execution order.

        Args:
            container_set: ContainerSet instance with sim and runtime containers

        Returns:
            Filename of the generated docker-compose.yaml
        """
        services = {}

        for c in container_set.sim or []:
            if c.command == "noop":
                continue
            service = self._to_docker_compose_service(c)
            services[c.uuid] = service

        for c in container_set.runtime or []:
            service = self._to_docker_compose_service(c)
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
            services[c.uuid] = service

        compose: dict[str, Any] = {
            "networks": {"microservices_network": {"driver": "bridge"}},
            "services": services,
        }
        if Path.home().joinpath(".netrc").exists():
            compose["secrets"] = {"netrc": {"file": "${HOME}/.netrc"}}

        filename = "docker-compose.yaml"
        log_dir = Path(self.context.cfg.wizard.log_dir)
        logger.info("Writing docker compose YAML to %s/%s", log_dir, filename)
        os.makedirs(log_dir, exist_ok=True)
        write_yaml(compose, str(log_dir / filename))
        return filename
