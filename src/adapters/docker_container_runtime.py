import docker
from typing import Any, List


class DockerContainerRuntime:
    """Concrete adapter wrapping the docker-py SDK."""

    # Expose Docker exception types so callers don't need to import docker directly
    NotFoundError = docker.errors.NotFound
    APIError = docker.errors.APIError
    ImageNotFound = docker.errors.ImageNotFound

    def __init__(self, client=None):
        self._client = client or docker.from_env()

    def get_container(self, name: str) -> Any:
        return self._client.containers.get(name)

    def list_containers(self, **kwargs) -> List[Any]:
        return self._client.containers.list(**kwargs)

    def create_container(self, **kwargs) -> Any:
        return self._client.containers.create(**kwargs)

    def pull_image(self, image_name: str) -> None:
        self._client.images.pull(image_name)

    def get_image(self, image_name: str) -> Any:
        return self._client.images.get(image_name)

    def get_network(self, name: str) -> Any:
        return self._client.networks.get(name)

    def list_networks(self) -> List[Any]:
        return self._client.networks.list()

    def create_network(self, **kwargs) -> Any:
        return self._client.networks.create(**kwargs)

    def get_volume(self, name: str) -> Any:
        return self._client.volumes.get(name)

    def get_api_version(self) -> str:
        return self._client.api.api_version

    def create_endpoint_config(self, version: str, **kwargs) -> Any:
        return docker.types.EndpointConfig(version, **kwargs)

    def create_ipam_pool(self, **kwargs) -> Any:
        return docker.types.IPAMPool(**kwargs)

    def create_ipam_config(self, pool_configs: list) -> Any:
        return docker.types.IPAMConfig(pool_configs=pool_configs)

    def create_ulimit(self, name: str, soft: int, hard: int) -> Any:
        return docker.types.Ulimit(name=name, soft=soft, hard=hard)
