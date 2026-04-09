"""
Container lifecycle manager for vPLC (openplc-runtime) containers.

Manages container startup sequencing after boot, health monitoring via Docker
event streaming, and automatic restart of crashed containers. This replaces
Docker's restart:always policy to eliminate the boot race condition where
containers start before host networking is ready.

IMPORTANT: vPLC containers run factory automation PLC logic. They must NEVER be
restarted if already running -- only started if stopped/exited. Restarting a
running PLC container disrupts industrial processes.
"""

import asyncio
import time

from tools.logger import log_debug, log_error, log_info, log_warning
from use_cases.docker_manager import get_self_container


class ContainerLifecycleManager:
    """
    Manages vPLC container lifecycle: startup sequencing after boot,
    health monitoring, and automatic restart of crashed containers.
    """

    # How often the fallback health poll checks container status (seconds)
    HEALTH_POLL_INTERVAL = 60

    # Delay before restarting a crashed container (seconds).
    # Avoids restart storms if a container is crash-looping.
    RESTART_DELAY = 3

    # Crash-loop protection: after MAX_RAPID_RESTARTS restarts within
    # RAPID_RESTART_WINDOW seconds, stop retrying and log an error.
    MAX_RAPID_RESTARTS = 5
    RAPID_RESTART_WINDOW = 600  # 10 minutes

    def __init__(
        self,
        container_runtime,
        client_registry,
        socket_repo,
        operations_state,
    ):
        self.container_runtime = container_runtime
        self.client_registry = client_registry
        self.socket_repo = socket_repo
        self.operations_state = operations_state
        self.running = False
        self._event_task = None
        self._poll_task = None
        self._startup_done = asyncio.Event()
        self._loop = None
        # Per-container restart timestamps for crash-loop detection
        self._restart_history = {}

    async def start(self):
        """Start lifecycle management: Docker event watchdog + health poll."""
        self.running = True
        self._event_task = asyncio.create_task(self._docker_event_loop())
        self._poll_task = asyncio.create_task(self._health_poll_loop())
        log_info("Container lifecycle manager started")

    async def stop(self):
        """Stop all lifecycle management tasks."""
        self.running = False
        for task in (self._event_task, self._poll_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._event_task = None
        self._poll_task = None
        log_info("Container lifecycle manager stopped")

    async def on_network_ready(self):
        """Called when netmon connects and network is confirmed ready.

        Triggers the boot startup sequence: starts stopped containers,
        reconnects orchestrator to internal bridges, refreshes IPs.
        Running containers are left alone (never restart a running PLC).
        """
        await self._start_existing_containers()
        self._startup_done.set()

    # ── Boot Startup ─────────────────────────────────────────────────────

    async def _start_existing_containers(self):
        """Start all known vPLC containers that are not already running.

        For each container in the client registry:
        - Running: leave it alone. Migrate restart policy if needed.
        - Stopped/exited: start it.
        - Missing: log warning, skip.
        Always reconnect orchestrator to the internal bridge network.
        """
        clients = self.client_registry.list_clients()
        if not clients:
            log_info("No existing containers to manage at boot")
            return

        log_info(f"Managing {len(clients)} existing container(s) after network ready...")

        for container_name in clients:
            try:
                await self._ensure_container_running(container_name)
            except Exception as e:
                log_error(f"Failed to manage container {container_name} at boot: {e}")

    async def _ensure_container_running(self, container_name):
        """Ensure a single container is running and orchestrator is connected.

        Never restarts a running container -- PLC processes must not be disrupted.
        """
        try:
            container = await asyncio.to_thread(
                self.container_runtime.get_container, container_name
            )
        except self.container_runtime.NotFoundError:
            log_warning(
                f"Container {container_name} in registry but not in Docker "
                f"(may have been deleted externally)"
            )
            return

        await asyncio.to_thread(container.reload)

        # Migrate old restart:always containers to restart:no
        await self._migrate_restart_policy(container, container_name)

        status = container.status

        if status == "running":
            log_info(f"Container {container_name} already running, leaving it alone")
        elif status in ("exited", "created"):
            log_info(f"Starting stopped container {container_name}")
            await asyncio.to_thread(container.start)
            await asyncio.sleep(2)
        else:
            log_warning(f"Container {container_name} in unexpected state: {status}")
            return

        await self._reconnect_orchestrator_to_bridge(container_name)
        await self._refresh_client_ip(container_name)

    async def _migrate_restart_policy(self, container, container_name):
        """Migrate container from restart:always to restart:no if needed."""
        try:
            host_config = container.attrs.get("HostConfig", {})
            current_policy = host_config.get("RestartPolicy", {}).get("Name", "")
            if current_policy not in ("no", ""):
                log_info(
                    f"Migrating {container_name} restart policy "
                    f"from '{current_policy}' to 'no'"
                )
                await asyncio.to_thread(
                    container.update, restart_policy={"Name": "no"}
                )
        except Exception as e:
            log_warning(f"Failed to migrate restart policy for {container_name}: {e}")

    # ── Bridge Reconnection ──────────────────────────────────────────────

    async def _reconnect_orchestrator_to_bridge(self, container_name):
        """Connect orchestrator-agent to a container's internal bridge network."""
        internal_network_name = f"{container_name}_internal"
        try:
            def _connect():
                network = self.container_runtime.get_network(internal_network_name)
                main_container = get_self_container(
                    container_runtime=self.container_runtime,
                    socket_repo=self.socket_repo,
                )
                if main_container:
                    try:
                        network.connect(main_container)
                        log_debug(
                            f"Connected orchestrator to {internal_network_name}"
                        )
                    except self.container_runtime.APIError as e:
                        if (
                            "already exists" in str(e).lower()
                            or "already attached" in str(e).lower()
                        ):
                            log_debug(
                                f"Orchestrator already connected to "
                                f"{internal_network_name}"
                            )
                        else:
                            log_warning(
                                f"Could not connect orchestrator to "
                                f"{internal_network_name}: {e}"
                            )

            await asyncio.to_thread(_connect)
        except self.container_runtime.NotFoundError:
            log_warning(f"Internal network {internal_network_name} not found")
        except Exception as e:
            log_warning(
                f"Error reconnecting orchestrator to {internal_network_name}: {e}"
            )

    async def _refresh_client_ip(self, container_name):
        """Reload container, extract internal IP, update client registry."""
        try:
            def _refresh():
                container = self.container_runtime.get_container(container_name)
                container.reload()
                internal_network_name = f"{container_name}_internal"
                networks = container.attrs.get(
                    "NetworkSettings", {}
                ).get("Networks", {})
                if internal_network_name in networks:
                    ip = networks[internal_network_name].get("IPAddress")
                    if ip:
                        self.client_registry.add_client(container_name, ip)
                        log_debug(
                            f"Updated internal IP for {container_name}: {ip}"
                        )

            await asyncio.to_thread(_refresh)
        except Exception as e:
            log_warning(f"Failed to refresh IP for {container_name}: {e}")

    # ── Docker Event Watchdog ────────────────────────────────────────────

    async def _docker_event_loop(self):
        """Stream Docker container events and restart crashed vPLC containers.

        Uses a dedicated event stream (separate Docker client) since events()
        blocks the HTTP connection. Only monitors containers in the client
        registry (managed vPLCs).
        """
        # Capture the running loop before entering the blocking thread
        # (asyncio.get_event_loop() is deprecated in threads on Python 3.10+)
        self._loop = asyncio.get_running_loop()
        log_info("Docker event watchdog started")
        try:
            while self.running:
                try:
                    await asyncio.to_thread(self._consume_docker_events)
                except Exception as e:
                    if not self.running:
                        break
                    log_error(f"Docker event stream error: {e}")
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            log_info("Docker event watchdog cancelled")
            raise

    def _consume_docker_events(self):
        """Blocking: consume Docker events in a thread."""
        event_stream, close_fn = self.container_runtime.create_event_stream(
            decode=True,
            filters={"type": "container", "event": ["die"]},
        )
        try:
            for event in event_stream:
                if not self.running:
                    break

                attrs = event.get("Actor", {}).get("Attributes", {})
                container_name = attrs.get("name", "")

                if not self.client_registry.contains(container_name):
                    continue

                exit_code = attrs.get("exitCode", "unknown")
                log_warning(
                    f"Container {container_name} died "
                    f"(exit code: {exit_code}), scheduling restart"
                )

                self._loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    self._handle_container_exit(container_name),
                )
        finally:
            close_fn()

    # ── Health Poll Fallback ─────────────────────────────────────────────

    async def _health_poll_loop(self):
        """Periodic fallback: check all containers and restart any that stopped.

        Catches cases the event stream might miss (e.g., reconnection gaps).
        Waits for initial boot startup to complete before polling.
        """
        log_info("Health poll watchdog started")
        try:
            await self._startup_done.wait()

            while self.running:
                await asyncio.sleep(self.HEALTH_POLL_INTERVAL)
                if not self.running:
                    break

                clients = self.client_registry.list_clients()
                for container_name in clients:
                    try:
                        container = await asyncio.to_thread(
                            self.container_runtime.get_container, container_name
                        )
                        await asyncio.to_thread(container.reload)

                        if container.status != "running":
                            in_progress, _ = (
                                self.operations_state.is_operation_in_progress(
                                    container_name
                                )
                            )
                            if not in_progress:
                                log_warning(
                                    f"Container {container_name} not running "
                                    f"(status: {container.status}), restarting"
                                )
                                await self._handle_container_exit(container_name)
                    except self.container_runtime.NotFoundError:
                        log_debug(
                            f"Container {container_name} not found during "
                            f"health poll"
                        )
                    except Exception as e:
                        log_error(
                            f"Error checking health of {container_name}: {e}"
                        )
        except asyncio.CancelledError:
            log_info("Health poll watchdog cancelled")
            raise

    # ── Container Restart ────────────────────────────────────────────────

    def _is_crash_looping(self, container_name):
        """Check if a container is crash-looping (too many restarts recently).

        Returns True if the container has exceeded MAX_RAPID_RESTARTS within
        RAPID_RESTART_WINDOW seconds and should not be restarted.
        """
        now = time.time()
        history = self._restart_history.get(container_name, [])
        # Keep only recent timestamps
        history = [t for t in history if now - t < self.RAPID_RESTART_WINDOW]
        self._restart_history[container_name] = history

        if len(history) >= self.MAX_RAPID_RESTARTS:
            return True
        return False

    def _record_restart(self, container_name):
        """Record a restart timestamp for crash-loop detection."""
        history = self._restart_history.setdefault(container_name, [])
        history.append(time.time())

    async def _handle_container_exit(self, container_name):
        """Restart a container that has exited/died unexpectedly.

        Skips restart if a create/delete operation is in progress or if the
        container is crash-looping (exceeded MAX_RAPID_RESTARTS within
        RAPID_RESTART_WINDOW).
        """
        in_progress, op_type = self.operations_state.is_operation_in_progress(
            container_name
        )
        if in_progress:
            log_debug(
                f"Container {container_name} has {op_type} in progress, "
                f"skipping automatic restart"
            )
            return

        if self._is_crash_looping(container_name):
            log_error(
                f"Container {container_name} has crashed "
                f"{self.MAX_RAPID_RESTARTS} times within "
                f"{self.RAPID_RESTART_WINDOW}s, giving up automatic restarts. "
                f"Check container logs for the root cause."
            )
            return

        await asyncio.sleep(self.RESTART_DELAY)

        try:
            container = await asyncio.to_thread(
                self.container_runtime.get_container, container_name
            )
            await asyncio.to_thread(container.reload)

            if container.status == "running":
                log_debug(
                    f"Container {container_name} already running, "
                    f"no restart needed"
                )
                return

            log_info(f"Starting crashed container {container_name}")
            await asyncio.to_thread(container.start)
            self._record_restart(container_name)

            await asyncio.sleep(2)
            await self._reconnect_orchestrator_to_bridge(container_name)
            await self._refresh_client_ip(container_name)

            log_info(f"Container {container_name} restarted successfully")
        except self.container_runtime.NotFoundError:
            log_warning(
                f"Container {container_name} no longer exists, cannot restart"
            )
        except Exception as e:
            log_error(f"Failed to restart container {container_name}: {e}")
