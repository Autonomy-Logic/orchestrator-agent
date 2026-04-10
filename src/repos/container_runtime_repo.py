import docker
from typing import Any, Dict, List, Optional

from repos.interfaces import ContainerRuntimeRepoInterface
from tools.logger import log_info, log_debug, log_warning, log_error
from tools.network_utils import (
    detect_interface_network,
    resolve_subnet,
)


class ContainerRuntimeRepo(ContainerRuntimeRepoInterface):
    """Concrete repo wrapping the docker-py SDK."""

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

    # ---- Network operations (moved from tools/docker_tools.py) ----

    def _validate_network_exists(self, network) -> bool:
        """
        Validate that a Docker network object refers to an existing network.

        Docker's networks.get() can return stale objects where the name lookup
        succeeds but the underlying network (by ID) no longer exists.
        """
        try:
            network.reload()
            return True
        except docker.errors.NotFound:
            return False
        except Exception as e:
            log_warning(f"Unexpected error validating network {network.name}: {e}")
            return False

    def get_or_create_macvlan_network(
        self,
        parent_interface: str,
        parent_subnet: Optional[str] = None,
        parent_gateway: Optional[str] = None,
        interface_cache: Any = None,
    ) -> Any:
        """
        Get existing MACVLAN network for a parent interface or create a new one.
        If parent_subnet and parent_gateway are not provided, attempts to auto-detect them.
        parent_subnet can be in either:
        - Netmask format (e.g., 255.255.255.0) - will be converted to CIDR using gateway
        - CIDR format (e.g., 192.168.1.0/24) - used directly
        Returns the network object.
        """
        if parent_subnet and parent_gateway:
            parent_subnet = resolve_subnet(parent_subnet, parent_gateway)
            log_debug(f"Resolved subnet to CIDR: {parent_subnet}")
        else:
            if interface_cache is None:
                raise ValueError(
                    "interface_cache is required when parent_subnet/parent_gateway are not provided"
                )
            parent_subnet, parent_gateway = detect_interface_network(
                parent_interface, interface_cache
            )

            if not parent_subnet:
                raise ValueError(
                    f"Could not detect subnet for interface {parent_interface}. "
                    f"The interface may not exist or netmon may not be running."
                )

        network_name = f"macvlan_{parent_interface}_{parent_subnet.replace('/', '_')}"

        try:
            network = self._client.networks.get(network_name)

            if self._validate_network_exists(network):
                log_debug(f"MACVLAN network {network_name} already exists, reusing it")
                return network
            else:
                log_warning(
                    f"MACVLAN network {network_name} exists but is stale (underlying network not found). "
                    f"Removing stale reference and recreating..."
                )
                try:
                    network.remove()
                except Exception as remove_err:
                    log_debug(f"Could not remove stale network {network_name}: {remove_err}")

        except docker.errors.NotFound:
            pass

        log_info(
            f"Creating new MACVLAN network {network_name} for parent interface {parent_interface} "
            f"with subnet {parent_subnet} and gateway {parent_gateway}"
        )
        try:
            ipam_pool_config = {"subnet": parent_subnet}
            if parent_gateway:
                ipam_pool_config["gateway"] = parent_gateway

            ipam_pool = docker.types.IPAMPool(**ipam_pool_config)
            ipam_config = docker.types.IPAMConfig(pool_configs=[ipam_pool])
            network = self._client.networks.create(
                name=network_name,
                driver="macvlan",
                options={"parent": parent_interface},
                ipam=ipam_config,
            )
            log_info(f"MACVLAN network {network_name} created successfully")
            return network
        except docker.errors.APIError as e:
            if "overlaps" in str(e).lower():
                log_warning(
                    f"Network overlap detected for subnet {parent_subnet}. "
                    f"Searching for existing MACVLAN network to reuse..."
                )

                try:
                    all_networks = self._client.networks.list()
                    for net in all_networks:
                        if net.attrs.get("Driver") == "macvlan":
                            net_options = net.attrs.get("Options", {})
                            net_parent = net_options.get("parent")

                            ipam = net.attrs.get("IPAM", {})
                            if ipam and ipam.get("Config"):
                                for config in ipam["Config"]:
                                    net_subnet = config.get("Subnet")
                                    if (
                                        net_subnet == parent_subnet
                                        and net_parent == parent_interface
                                    ):
                                        log_info(
                                            f"Found existing MACVLAN network {net.name} with matching "
                                            f"subnet {parent_subnet} and parent {parent_interface}. Reusing it."
                                        )
                                        return net

                    log_error(
                        f"Network overlap error but could not find existing MACVLAN network "
                        f"for subnet {parent_subnet} and parent {parent_interface}"
                    )
                    raise
                except Exception as search_error:
                    log_error(f"Error searching for existing networks: {search_error}")
                    raise
            else:
                log_error(f"Failed to create MACVLAN network {network_name}: {e}")
                raise

    def create_internal_network(self, container_name: str) -> Any:
        """
        Create an internal bridge network for orchestrator-runtime communication.
        Returns the network object.
        """
        network_name = f"{container_name}_internal"

        try:
            network = self._client.networks.get(network_name)
            log_debug(f"Internal network {network_name} already exists")
            return network
        except docker.errors.NotFound:
            log_info(f"Creating internal network {network_name}")
            try:
                network = self._client.networks.create(
                    name=network_name, driver="bridge", internal=True
                )
                log_info(f"Internal network {network_name} created successfully")
                return network
            except Exception as e:
                log_error(f"Failed to create internal network {network_name}: {e}")
                raise

    def docker_events(self, **kwargs) -> Any:
        return self._client.events(**kwargs)

    def create_event_stream(self, **kwargs):
        """Create a dedicated Docker event stream on a fresh client.

        Docker's events() blocks the HTTP connection, so it must not share the
        client used for other operations. Returns (event_iterator, close_fn).
        """
        client = docker.from_env()
        return client.events(**kwargs), client.close

    def get_running_pid(self, container_name: str) -> Optional[int]:
        """
        Return the PID of a running container, or None if not running.

        Reloads container state from Docker to get the current PID.
        """
        try:
            container = self._client.containers.get(container_name)
            container.reload()
            pid = container.attrs.get("State", {}).get("Pid", 0)
            if pid > 0 and container.status == "running":
                return pid
            return None
        except docker.errors.NotFound:
            return None

    def get_existing_mac_addresses_on_interface(
        self, parent_interface: str
    ) -> Dict[str, str]:
        """
        Get all MAC addresses currently in use by containers on MACVLAN networks
        attached to a specific parent interface.

        Args:
            parent_interface: Physical network interface on host (e.g., "eth0", "ens33")

        Returns:
            Dictionary mapping MAC address (lowercase) to container name
        """
        mac_to_container: Dict[str, str] = {}

        try:
            macvlan_networks = []
            all_networks = self._client.networks.list()
            for net in all_networks:
                if net.attrs.get("Driver") == "macvlan":
                    net_options = net.attrs.get("Options", {})
                    net_parent = net_options.get("parent")
                    if net_parent == parent_interface:
                        macvlan_networks.append(net.name)

            if not macvlan_networks:
                log_debug(
                    f"No MACVLAN networks found for parent interface {parent_interface}"
                )
                return mac_to_container

            all_containers = self._client.containers.list(all=True)
            for container in all_containers:
                network_settings = container.attrs.get("NetworkSettings", {}).get(
                    "Networks", {}
                )
                for net_name, net_info in network_settings.items():
                    if net_name in macvlan_networks:
                        mac_address = net_info.get("MacAddress", "")
                        if mac_address:
                            mac_to_container[mac_address.lower()] = container.name
                            log_debug(
                                f"Found MAC {mac_address} on container {container.name} "
                                f"(network: {net_name})"
                            )

        except Exception as e:
            log_error(
                f"Error getting existing MAC addresses for interface {parent_interface}: {e}"
            )

        return mac_to_container
