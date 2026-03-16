import asyncio
from entities import DedicatedNicConfig
from tools.logger import log_info, log_debug, log_warning, log_error


class DedicatedNICManager:
    """
    Manages dedicated physical NICs that are moved into container network namespaces.

    Handles:
    - Resync on orchestrator startup (re-move NICs for running containers)
    - Docker event monitoring for container restarts (re-move NIC when container restarts)
    - Orphan config cleanup (remove configs for containers that no longer exist)
    """

    def __init__(self, netmon_client, container_runtime, dedicated_nic_repo):
        self.netmon_client = netmon_client
        self.container_runtime = container_runtime
        self.dedicated_nic_repo = dedicated_nic_repo
        self._event_listener_task = None
        self._running = False
        self._events_generator = None

    async def _move_nic_to_running_container(self, container_name, host_interface, *, check_present=False):
        """
        Get a running container's PID and move the NIC into its namespace.

        Args:
            check_present: If True, skip move if NIC is already in the container.

        Returns True if NIC was moved (or already present), False on failure.
        """
        container = self.container_runtime.get_container(container_name)
        container.reload()
        pid = container.attrs.get("State", {}).get("Pid", 0)

        if pid <= 0 or container.status != "running":
            log_debug(f"Container {container_name} not running, skipping NIC move for {host_interface}")
            return False

        if check_present:
            check_result = await self.netmon_client.check_nic_in_container(host_interface, pid)
            if check_result.get("present"):
                log_debug(f"NIC {host_interface} already present in {container_name}")
                return True

        log_info(f"Moving NIC {host_interface} to container {container_name} (PID {pid})")
        result = await self.netmon_client.move_nic_to_container(host_interface, pid)
        if result.get("success"):
            log_info(f"NIC {host_interface} moved to {container_name}")
            return True

        log_warning(f"Failed to move NIC {host_interface} to {container_name}: {result.get('error')}")
        return False

    async def resync_nics_for_existing_containers(self):
        """
        Called on orchestrator startup. Re-moves NICs for all running containers
        that have dedicated NIC configurations.

        Also cleans up orphaned configs for containers that no longer exist.
        """
        all_configs = self.dedicated_nic_repo.load_all_configs()
        if not all_configs:
            log_debug("No dedicated NIC configs to resync")
            return

        log_info(f"Resyncing dedicated NICs for {len(all_configs)} container(s)")

        orphaned = []
        for container_name, raw_config in all_configs.items():
            nic_config = DedicatedNicConfig.from_dict(raw_config)

            try:
                await self._move_nic_to_running_container(
                    container_name, nic_config.host_interface, check_present=True,
                )
            except self.container_runtime.NotFoundError:
                log_warning(
                    f"Container {container_name} no longer exists, "
                    f"cleaning up orphaned NIC config for {nic_config.host_interface}"
                )
                orphaned.append(container_name)
            except Exception as e:
                log_error(f"Error resyncing NIC for {container_name}: {e}")

        for container_name in orphaned:
            self.dedicated_nic_repo.delete_config(container_name)

    async def start_docker_event_listener(self):
        """
        Subscribe to Docker 'container start' events for real-time NIC re-assignment.

        When a container with a dedicated NIC config restarts, the NIC needs to be
        re-moved into the new namespace (container restart creates a new PID/namespace).

        The Docker SDK events iterator is synchronous and blocking, so we run it in
        a thread via run_in_executor and use an asyncio.Queue to forward events
        back to the async event loop without blocking it.
        """
        self._running = True
        self._event_queue = asyncio.Queue()
        log_info("Dedicated NIC Docker event listener started")

        def _poll_docker_events():
            """Run in a thread — blocks on Docker event stream, pushes to queue."""
            try:
                self._events_generator = self.container_runtime.client.events(
                    filters={"event": ["start"]},
                    decode=True,
                    timeout=30,
                )
                for event in self._events_generator:
                    if not self._running:
                        break
                    self._event_queue.put_nowait(event)
            except Exception as e:
                if self._running:
                    self._event_queue.put_nowait(e)
            finally:
                self._events_generator = None

        loop = asyncio.get_event_loop()
        poll_future = loop.run_in_executor(None, _poll_docker_events)

        try:
            while self._running:
                try:
                    event = await asyncio.wait_for(self._event_queue.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue

                if isinstance(event, Exception):
                    log_error(f"Dedicated NIC Docker event listener error: {event}")
                    break

                container_name = event.get("Actor", {}).get("Attributes", {}).get("name")
                if not container_name:
                    continue

                raw_config = self.dedicated_nic_repo.load_config(container_name)
                if not raw_config:
                    continue

                nic_config = DedicatedNicConfig.from_dict(raw_config)
                log_info(f"Container {container_name} started, re-assigning dedicated NIC {nic_config.host_interface}")

                # Brief delay for container PID to be fully assigned
                await asyncio.sleep(1)

                try:
                    await self._move_nic_to_running_container(
                        container_name, nic_config.host_interface,
                    )
                except Exception as e:
                    log_error(f"Error re-assigning NIC to {container_name}: {e}")
        finally:
            self._running = False
            poll_future.cancel()

        log_info("Dedicated NIC Docker event listener stopped")

    async def stop(self):
        """Cancel the event listener task."""
        self._running = False
        if self._events_generator is not None:
            try:
                self._events_generator.close()
            except Exception:
                pass
        if self._event_listener_task and not self._event_listener_task.done():
            self._event_listener_task.cancel()
            try:
                await self._event_listener_task
            except asyncio.CancelledError:
                pass
