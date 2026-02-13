import asyncio
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from tools.network_event_listener import NetworkEventListener, DEBOUNCE_SECONDS


def _make_listener():
    interface_cache = MagicMock()
    netmon_client = MagicMock()
    dhcp_manager = MagicMock()
    dhcp_manager.handle_dhcp_update = AsyncMock()
    dhcp_manager.running = False
    dhcp_manager.pending_dhcp_resyncs = {}
    dhcp_manager.dhcp_retry_task = None
    dhcp_manager.resync_dhcp_for_existing_containers = AsyncMock()
    dhcp_manager.stop = AsyncMock()
    reconnection_manager = MagicMock()
    reconnection_manager.reconnect_containers = AsyncMock()
    serial_device_manager = MagicMock()
    serial_device_manager.handle_device_discovery = AsyncMock()
    serial_device_manager.handle_device_change = AsyncMock()

    listener = NetworkEventListener(
        interface_cache=interface_cache,
        netmon_client=netmon_client,
        dhcp_manager=dhcp_manager,
        reconnection_manager=reconnection_manager,
        serial_device_manager=serial_device_manager,
    )
    return listener


class TestHandleEvent:
    @pytest.mark.asyncio
    async def test_network_discovery(self):
        """network_discovery event populates interface cache."""
        listener = _make_listener()

        await listener._handle_event({
            "type": "network_discovery",
            "data": {
                "interfaces": [
                    {
                        "interface": "eth0",
                        "ipv4_addresses": [{"address": "192.168.1.10", "subnet": "192.168.1.0/24"}],
                        "gateway": "192.168.1.1",
                        "type": "ethernet",
                    }
                ]
            },
        })

        listener.interface_cache.set_interface.assert_called_once_with("eth0", {
            "subnet": "192.168.1.0/24",
            "gateway": "192.168.1.1",
            "type": "ethernet",
            "addresses": [{"address": "192.168.1.10", "subnet": "192.168.1.0/24"}],
        })

    @pytest.mark.asyncio
    async def test_network_discovery_no_addresses(self):
        """Interface with no IPv4 addresses removed from cache."""
        listener = _make_listener()

        await listener._handle_event({
            "type": "network_discovery",
            "data": {
                "interfaces": [
                    {"interface": "eth0", "ipv4_addresses": [], "gateway": None}
                ]
            },
        })

        listener.interface_cache.remove_interface.assert_called_once_with("eth0")

    @pytest.mark.asyncio
    async def test_network_discovery_skips_no_name(self):
        """Interface without name is skipped."""
        listener = _make_listener()

        await listener._handle_event({
            "type": "network_discovery",
            "data": {
                "interfaces": [{"ipv4_addresses": [{"subnet": "10.0.0.0/24"}]}]
            },
        })

        listener.interface_cache.set_interface.assert_not_called()

    @pytest.mark.asyncio
    async def test_dhcp_update(self):
        """dhcp_update event dispatched to dhcp_manager."""
        listener = _make_listener()
        data = {"container_name": "plc1", "vnic_name": "v1", "ip": "10.0.0.5"}

        await listener._handle_event({"type": "dhcp_update", "data": data})

        listener.dhcp_manager.handle_dhcp_update.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_network_change_updates_cache(self):
        """network_change event updates interface cache."""
        listener = _make_listener()
        listener.interface_cache.get_all_interfaces.return_value = {}

        await listener._handle_event({
            "type": "network_change",
            "data": {
                "interface": "eth0",
                "ipv4_addresses": [{"address": "10.0.0.1", "subnet": "10.0.0.0/24"}],
                "gateway": "10.0.0.1",
            },
        })

        listener.interface_cache.set_interface.assert_called_once()
        assert "eth0" in listener.pending_changes

    @pytest.mark.asyncio
    async def test_network_change_no_interface(self):
        """network_change with no interface → early return."""
        listener = _make_listener()

        await listener._handle_event({
            "type": "network_change",
            "data": {"ipv4_addresses": [{"subnet": "10.0.0.0/24"}]},
        })

        listener.interface_cache.set_interface.assert_not_called()

    @pytest.mark.asyncio
    async def test_network_change_no_addresses(self):
        """network_change with empty addresses removes from cache."""
        listener = _make_listener()

        await listener._handle_event({
            "type": "network_change",
            "data": {"interface": "eth0", "ipv4_addresses": []},
        })

        listener.interface_cache.remove_interface.assert_called_once_with("eth0")

    @pytest.mark.asyncio
    async def test_device_discovery(self):
        """device_discovery event dispatched to serial_device_manager."""
        listener = _make_listener()
        data = {"devices": [{"by_id": "usb-FTDI", "path": "/dev/ttyUSB0"}]}

        await listener._handle_event({"type": "device_discovery", "data": data})

        listener.serial_device_manager.handle_device_discovery.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_device_change(self):
        """device_change event dispatched to serial_device_manager."""
        listener = _make_listener()
        data = {"action": "add", "device": {"path": "/dev/ttyUSB0"}}

        await listener._handle_event({"type": "device_change", "data": data})

        listener.serial_device_manager.handle_device_change.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_unknown_event_no_error(self):
        """Unknown event type does not raise."""
        listener = _make_listener()

        # Should not raise
        await listener._handle_event({"type": "unknown_event", "data": {}})


class TestDelegatedApi:
    @pytest.mark.asyncio
    async def test_send_command(self):
        listener = _make_listener()
        listener.netmon_client.send_command = AsyncMock(return_value={"ok": True})

        result = await listener.send_command({"cmd": "test"})

        listener.netmon_client.send_command.assert_called_once_with({"cmd": "test"})
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_start_dhcp(self):
        listener = _make_listener()
        listener.netmon_client.start_dhcp = AsyncMock(return_value={"success": True})

        result = await listener.start_dhcp("plc1", "v1", "02:00:00:00:00:01", 1234)

        listener.netmon_client.start_dhcp.assert_called_once_with("plc1", "v1", "02:00:00:00:00:01", 1234)

    @pytest.mark.asyncio
    async def test_stop_dhcp(self):
        listener = _make_listener()
        listener.netmon_client.stop_dhcp = AsyncMock(return_value={})

        await listener.stop_dhcp("plc1", "v1")

        listener.netmon_client.stop_dhcp.assert_called_once_with("plc1", "v1")

    @pytest.mark.asyncio
    async def test_request_wifi_dhcp(self):
        listener = _make_listener()
        listener.netmon_client.request_wifi_dhcp = AsyncMock(return_value={"success": True})

        await listener.request_wifi_dhcp("plc1", "v1", "wlan0", 5678)

        listener.netmon_client.request_wifi_dhcp.assert_called_once_with("plc1", "v1", "wlan0", 5678)

    @pytest.mark.asyncio
    async def test_setup_proxy_arp_bridge(self):
        listener = _make_listener()
        listener.netmon_client.setup_proxy_arp_bridge = AsyncMock(return_value={})

        await listener.setup_proxy_arp_bridge("plc1", 1234, "wlan0", "10.0.0.5", "10.0.0.1")

        listener.netmon_client.setup_proxy_arp_bridge.assert_called_once_with(
            "plc1", 1234, "wlan0", "10.0.0.5", "10.0.0.1", "255.255.255.0"
        )

    @pytest.mark.asyncio
    async def test_cleanup_proxy_arp_bridge(self):
        listener = _make_listener()
        listener.netmon_client.cleanup_proxy_arp_bridge = AsyncMock(return_value={})

        await listener.cleanup_proxy_arp_bridge("plc1", "10.0.0.5", "wlan0", "veth-plc1")

        listener.netmon_client.cleanup_proxy_arp_bridge.assert_called_once()

    def test_get_dhcp_ip(self):
        listener = _make_listener()
        listener.netmon_client.get_dhcp_ip.return_value = "10.0.0.5"

        assert listener.get_dhcp_ip("plc1", "v1") == "10.0.0.5"

    def test_register_dhcp_callback(self):
        listener = _make_listener()
        cb = MagicMock()

        listener.register_dhcp_callback(cb)

        listener.netmon_client.register_dhcp_callback.assert_called_once_with(cb)

    def test_get_available_devices(self):
        listener = _make_listener()
        listener.serial_device_manager.get_available_devices.return_value = [{"path": "/dev/ttyUSB0"}]

        result = listener.get_available_devices()

        assert result == [{"path": "/dev/ttyUSB0"}]

    def test_get_device_by_id(self):
        listener = _make_listener()
        listener.serial_device_manager.get_device_by_id.return_value = {"path": "/dev/ttyUSB0"}

        result = listener.get_device_by_id("usb-FTDI")

        assert result == {"path": "/dev/ttyUSB0"}

    def test_register_device_callback(self):
        listener = _make_listener()
        cb = MagicMock()

        listener.register_device_callback(cb)

        listener.serial_device_manager.register_device_callback.assert_called_once_with(cb)


class TestProcessPendingChanges:
    @pytest.mark.asyncio
    async def test_debounces_and_dispatches(self):
        """After debounce, dispatches to reconnection_manager."""
        listener = _make_listener()
        iface_data = {
            "interface": "eth0",
            "ipv4_addresses": [{"subnet": "10.0.0.0/24"}],
            "gateway": "10.0.0.1",
        }
        listener.pending_changes["eth0"] = iface_data
        # Set last_event_time far enough in the past
        listener.last_event_time["eth0"] = 0

        with patch("tools.network_event_listener.asyncio") as mock_asyncio:
            mock_asyncio.sleep = AsyncMock()
            mock_asyncio.get_event_loop.return_value.time.return_value = DEBOUNCE_SECONDS + 1

            await listener._process_pending_changes("eth0")

        listener.reconnection_manager.reconnect_containers.assert_called_once_with("eth0", iface_data)

    @pytest.mark.asyncio
    async def test_skips_if_recent_event(self):
        """Skips processing if another event arrived within debounce window."""
        listener = _make_listener()
        listener.pending_changes["eth0"] = {"interface": "eth0"}

        with patch("tools.network_event_listener.asyncio") as mock_asyncio:
            mock_asyncio.sleep = AsyncMock()
            current_time = 100.0
            mock_asyncio.get_event_loop.return_value.time.return_value = current_time
            # Last event is within debounce window
            listener.last_event_time["eth0"] = current_time - (DEBOUNCE_SECONDS / 2)

            await listener._process_pending_changes("eth0")

        listener.reconnection_manager.reconnect_containers.assert_not_called()


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_stop(self):
        """Stop sets running=False and cancels tasks."""
        listener = _make_listener()
        listener.running = True
        listener.listener_task = None

        await listener.stop()

        assert listener.running is False
        listener.dhcp_manager.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_with_active_task(self):
        """Stop cancels active listener task (lines 61-65)."""
        listener = _make_listener()
        listener.running = True

        # Create a real task that won't complete on its own
        async def hang_forever():
            await asyncio.sleep(999)

        listener.listener_task = asyncio.create_task(hang_forever())

        await listener.stop()

        assert listener.running is False
        assert listener.listener_task.cancelled()

    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        """Start sets running=True and creates a task (lines 43-54)."""
        listener = _make_listener()
        assert listener.running is False

        # We need to mock _listen_loop so it doesn't actually do I/O
        async def fake_loop():
            while listener.running:
                await asyncio.sleep(0.01)

        with patch.object(listener, '_listen_loop', side_effect=fake_loop):
            await listener.start()

        assert listener.running is True
        assert listener.listener_task is not None

        # Cleanup
        await listener.stop()

    @pytest.mark.asyncio
    async def test_start_when_already_running_returns_early(self):
        """Start with running=True and active task returns early (line 48-49)."""
        listener = _make_listener()
        listener.running = True

        # Create a non-done task
        async def hang():
            await asyncio.sleep(999)

        listener.listener_task = asyncio.create_task(hang())

        # Should return early without creating a new task
        await listener.start()

        # Cleanup
        listener.listener_task.cancel()
        try:
            await listener.listener_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_start_when_running_but_task_done_restarts(self):
        """Start with running=True but task done restarts (lines 44-46)."""
        listener = _make_listener()
        listener.running = True

        # Create a completed task
        async def done_quickly():
            pass

        listener.listener_task = asyncio.create_task(done_quickly())
        await listener.listener_task  # Let it complete

        async def fake_loop():
            while listener.running:
                await asyncio.sleep(0.01)

        with patch.object(listener, '_listen_loop', side_effect=fake_loop):
            await listener.start()

        assert listener.running is True
        assert listener.listener_task is not None

        # Cleanup
        await listener.stop()


class TestHandleEventException:
    @pytest.mark.asyncio
    async def test_exception_in_handler_no_crash(self):
        """Lines 238-239: exception in _handle_event is caught."""
        listener = _make_listener()
        # Make dhcp_manager raise when handling dhcp_update
        listener.dhcp_manager.handle_dhcp_update = AsyncMock(side_effect=RuntimeError("boom"))

        # Should not raise
        await listener._handle_event({"type": "dhcp_update", "data": {}})


class TestProcessPendingChangesNotInPending:
    @pytest.mark.asyncio
    async def test_interface_not_in_pending_returns(self):
        """Line 253: interface not in pending_changes returns early."""
        listener = _make_listener()
        # pending_changes is empty, so "eth0" is not in it

        with patch("tools.network_event_listener.asyncio") as mock_asyncio:
            mock_asyncio.sleep = AsyncMock()
            current_time = 100.0
            mock_asyncio.get_event_loop.return_value.time.return_value = current_time
            listener.last_event_time["eth0"] = 0  # old event

            await listener._process_pending_changes("eth0")

        listener.reconnection_manager.reconnect_containers.assert_not_called()


class TestDelegatedApiExtra:
    @pytest.mark.asyncio
    async def test_cleanup_all_proxy_arp(self):
        """Line 318: cleanup_all_proxy_arp delegates to netmon_client."""
        listener = _make_listener()
        listener.netmon_client.cleanup_all_proxy_arp = AsyncMock(return_value={"ok": True})

        result = await listener.cleanup_all_proxy_arp()

        listener.netmon_client.cleanup_all_proxy_arp.assert_called_once()
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_resync_serial_devices(self):
        """Line 327: resync_serial_devices delegates to serial_device_manager."""
        listener = _make_listener()
        listener.serial_device_manager.resync_serial_devices = AsyncMock()

        await listener.resync_serial_devices()

        listener.serial_device_manager.resync_serial_devices.assert_called_once()


class TestListenLoop:
    """Tests for the _listen_loop method (lines 71-138)."""

    @pytest.mark.asyncio
    async def test_socket_not_found_waits(self):
        """Lines 74-80: socket not found -> sleep and continue."""
        listener = _make_listener()
        listener.running = True

        call_count = [0]
        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            call_count[0] += 1
            if call_count[0] >= 1:
                listener.running = False

        with patch("os.path.exists", return_value=False), \
             patch("tools.network_event_listener.asyncio.sleep", side_effect=mock_sleep):
            await listener._listen_loop()

        assert listener.running is False
        assert listener.listener_task is None

    @pytest.mark.asyncio
    async def test_connection_reads_event_then_close(self):
        """Lines 82-125: connect, read one event, then connection closes (empty line)."""
        listener = _make_listener()
        listener.running = True

        event = {"type": "network_discovery", "data": {"interfaces": []}}
        event_bytes = json.dumps(event).encode("utf-8") + b"\n"

        readline_results = [event_bytes, b""]
        readline_index = [0]

        async def fake_readline():
            idx = readline_index[0]
            readline_index[0] += 1
            return readline_results[idx]

        mock_reader = MagicMock()
        mock_reader.readline = fake_readline

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        call_count = [0]

        async def fake_connect(path):
            call_count[0] += 1
            if call_count[0] > 1:
                listener.running = False
                raise FileNotFoundError("stop")
            return mock_reader, mock_writer

        with patch("os.path.exists", return_value=True), \
             patch("asyncio.open_unix_connection", side_effect=fake_connect), \
             patch("tools.network_event_listener.asyncio.sleep", new_callable=AsyncMock), \
             patch("asyncio.create_task", return_value=MagicMock()):
            await listener._listen_loop()

        assert listener.running is False
        mock_writer.close.assert_called()

    @pytest.mark.asyncio
    async def test_json_decode_error(self):
        """Lines 117-118: invalid JSON on readline -> log error and continue."""
        listener = _make_listener()
        listener.running = True

        readline_results = [b"not valid json\n", b""]
        readline_index = [0]

        async def fake_readline():
            idx = readline_index[0]
            readline_index[0] += 1
            return readline_results[idx]

        mock_reader = MagicMock()
        mock_reader.readline = fake_readline

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        call_count = [0]

        async def fake_connect(path):
            call_count[0] += 1
            if call_count[0] > 1:
                listener.running = False
                raise FileNotFoundError("stop")
            return mock_reader, mock_writer

        with patch("os.path.exists", return_value=True), \
             patch("asyncio.open_unix_connection", side_effect=fake_connect), \
             patch("tools.network_event_listener.asyncio.sleep", new_callable=AsyncMock), \
             patch("asyncio.create_task", return_value=MagicMock()):
            await listener._listen_loop()

        assert listener.running is False

    @pytest.mark.asyncio
    async def test_timeout_error_continues(self):
        """Lines 115-116: TimeoutError on readline -> continue loop."""
        listener = _make_listener()
        listener.running = True

        wait_for_call = [0]

        async def fake_wait_for(coro, timeout):
            wait_for_call[0] += 1
            # Consume the coroutine to avoid warning
            try:
                if hasattr(coro, 'close'):
                    coro.close()
            except Exception:
                pass
            if wait_for_call[0] == 1:
                raise asyncio.TimeoutError()
            return b""  # close connection

        mock_reader = MagicMock()
        mock_reader.readline = AsyncMock(return_value=b"")

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        connect_count = [0]

        async def fake_connect(path):
            connect_count[0] += 1
            if connect_count[0] > 1:
                listener.running = False
                raise FileNotFoundError("stop")
            return mock_reader, mock_writer

        with patch("os.path.exists", return_value=True), \
             patch("asyncio.open_unix_connection", side_effect=fake_connect), \
             patch("asyncio.wait_for", side_effect=fake_wait_for), \
             patch("tools.network_event_listener.asyncio.sleep", new_callable=AsyncMock), \
             patch("asyncio.create_task", return_value=MagicMock()):
            await listener._listen_loop()

        assert wait_for_call[0] == 2  # one timeout, then one close

    @pytest.mark.asyncio
    async def test_generic_read_exception_breaks_inner_loop(self):
        """Lines 119-121: generic Exception on readline -> break inner loop."""
        listener = _make_listener()
        listener.running = True

        async def fail_wait_for(coro, timeout):
            try:
                if hasattr(coro, 'close'):
                    coro.close()
            except Exception:
                pass
            raise RuntimeError("unexpected error")

        mock_reader = MagicMock()
        mock_reader.readline = AsyncMock(return_value=b"")

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        connect_count = [0]

        async def fake_connect(path):
            connect_count[0] += 1
            if connect_count[0] > 1:
                listener.running = False
                raise FileNotFoundError("stop")
            return mock_reader, mock_writer

        with patch("os.path.exists", return_value=True), \
             patch("asyncio.open_unix_connection", side_effect=fake_connect), \
             patch("asyncio.wait_for", side_effect=fail_wait_for), \
             patch("tools.network_event_listener.asyncio.sleep", new_callable=AsyncMock), \
             patch("asyncio.create_task", return_value=MagicMock()):
            await listener._listen_loop()

        assert listener.running is False

    @pytest.mark.asyncio
    async def test_file_not_found_on_connect(self):
        """Lines 127-131: FileNotFoundError when connecting -> sleep and retry."""
        listener = _make_listener()
        listener.running = True

        call_count = [0]

        async def fake_connect(path):
            nonlocal call_count
            call_count[0] += 1
            raise FileNotFoundError("not found")

        async def mock_sleep(duration):
            if call_count[0] >= 1:
                listener.running = False

        with patch("os.path.exists", return_value=True), \
             patch("asyncio.open_unix_connection", side_effect=fake_connect), \
             patch("tools.network_event_listener.asyncio.sleep", side_effect=mock_sleep):
            await listener._listen_loop()

        assert listener.running is False

    @pytest.mark.asyncio
    async def test_generic_exception_on_connect(self):
        """Lines 132-134: generic Exception when connecting -> sleep and retry."""
        listener = _make_listener()
        listener.running = True

        call_count = [0]

        async def fake_connect(path):
            nonlocal call_count
            call_count[0] += 1
            raise ConnectionRefusedError("refused")

        async def mock_sleep(duration):
            if call_count[0] >= 1:
                listener.running = False

        with patch("os.path.exists", return_value=True), \
             patch("asyncio.open_unix_connection", side_effect=fake_connect), \
             patch("tools.network_event_listener.asyncio.sleep", side_effect=mock_sleep):
            await listener._listen_loop()

        assert listener.running is False

    @pytest.mark.asyncio
    async def test_dhcp_retry_task_started(self):
        """Lines 94-101: DHCP retry task is started when there are pending resyncs."""
        listener = _make_listener()
        listener.running = True
        listener.dhcp_manager.pending_dhcp_resyncs = {"plc1": {}}
        listener.dhcp_manager.dhcp_retry_task = None
        listener.dhcp_manager.dhcp_retry_loop = AsyncMock()

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(return_value=b"")

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        connect_count = [0]

        async def fake_connect(path):
            connect_count[0] += 1
            if connect_count[0] > 1:
                listener.running = False
                raise FileNotFoundError("stop")
            return mock_reader, mock_writer

        created_tasks = []

        def track_create_task(coro):
            task = MagicMock()
            created_tasks.append(coro)
            return task

        with patch("os.path.exists", return_value=True), \
             patch("asyncio.open_unix_connection", side_effect=fake_connect), \
             patch("asyncio.wait_for", side_effect=lambda coro, timeout: coro), \
             patch("tools.network_event_listener.asyncio.sleep", new_callable=AsyncMock), \
             patch("asyncio.create_task", side_effect=track_create_task):
            await listener._listen_loop()

        # Verify dhcp_retry_loop was passed to create_task
        assert len(created_tasks) > 0
