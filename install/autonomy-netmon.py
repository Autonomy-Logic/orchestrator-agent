#!/usr/bin/env python3
"""
Autonomy Network Monitor Daemon

Monitors host network interfaces for changes and reports them to the orchestrator-agent
via Unix domain socket. Provides network discovery, real-time change notifications,
and DHCP client management for runtime containers.
"""

import json
import socket
import time
import sys
import os
import signal
import logging
import subprocess
import threading
import select
from datetime import datetime
from typing import Any, Dict, List, Optional
import ipaddress

try:
    from pyroute2 import IPRoute, NetlinkError
except ImportError:
    print("ERROR: pyroute2 is not installed. Install it with: pip3 install pyroute2")
    sys.exit(1)

try:
    import pyudev
    PYUDEV_AVAILABLE = True
except ImportError:
    print("WARNING: pyudev is not installed. Serial device monitoring will be disabled.")
    print("Install it with: pip3 install pyudev")
    PYUDEV_AVAILABLE = False

SOCKET_PATH = "/var/orchestrator/netmon.sock"
LOG_FILE = "/var/log/autonomy-netmon.log"
DHCP_LEASE_DIR = "/var/orchestrator/dhcp"
DEBOUNCE_SECONDS = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


class DHCPManager:
    """Manages DHCP clients for runtime containers."""

    def __init__(self, send_event_callback):
        self.dhcp_processes: Dict[str, subprocess.Popen] = {}
        self.send_event = send_event_callback
        self.lease_monitor_thread = None
        self.running = False
        self.last_lease_state: Dict[str, dict] = {}
        os.makedirs(DHCP_LEASE_DIR, exist_ok=True)

    def start(self):
        """Start the lease monitor thread."""
        self.running = True
        self.lease_monitor_thread = threading.Thread(
            target=self._monitor_leases, daemon=True
        )
        self.lease_monitor_thread.start()
        logger.info("DHCP lease monitor started")

    def stop(self):
        """Stop all DHCP clients and the monitor thread."""
        self.running = False
        for key in list(self.dhcp_processes.keys()):
            self.stop_dhcp(key)
        if self.lease_monitor_thread:
            self.lease_monitor_thread.join(timeout=2)
        logger.info("DHCP manager stopped")

    def _find_interface_by_mac(self, container_pid: int, mac_address: str) -> Optional[str]:
        """Find the interface name inside a container's netns by MAC address."""
        try:
            result = subprocess.run(
                ["nsenter", "-t", str(container_pid), "-n", "ip", "-j", "link", "show"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                interfaces = json.loads(result.stdout)
                mac_lower = mac_address.lower()
                for iface in interfaces:
                    iface_mac = iface.get("address", "").lower()
                    if iface_mac == mac_lower:
                        return iface.get("ifname")
            logger.warning(f"Could not find interface with MAC {mac_address}")
        except Exception as e:
            logger.error(f"Error finding interface by MAC: {e}")
        return None

    def start_dhcp(
        self, container_name: str, vnic_name: str, mac_address: str, container_pid: int
    ) -> Dict[str, Any]:
        """Start a DHCP client for a container's vNIC.
        
        Args:
            container_name: Name of the container
            vnic_name: Name of the virtual NIC
            mac_address: MAC address of the interface to find
            container_pid: PID of the container's init process (provided by orchestrator-agent)
        """
        key = f"{container_name}:{vnic_name}"

        if key in self.dhcp_processes:
            proc = self.dhcp_processes[key]
            if proc.poll() is None:
                logger.info(f"DHCP client already running for {key}")
                return {"success": True, "message": "DHCP client already running"}

        if not container_pid or container_pid <= 0:
            logger.error(f"Invalid container PID: {container_pid}")
            return {"success": False, "error": f"Invalid container PID: {container_pid}"}
        
        netns_path = f"/proc/{container_pid}/ns/net"
        try:
            os.stat(netns_path)
        except FileNotFoundError:
            logger.error(f"Network namespace not found: {netns_path} - PID may be invalid or container not running")
            return {"success": False, "error": f"Container PID {container_pid} network namespace not found"}
        except PermissionError:
            logger.error(f"Permission denied accessing {netns_path} - netmon may need CAP_SYS_ADMIN or CAP_SYS_PTRACE")
            return {"success": False, "error": f"Permission denied accessing container PID {container_pid} network namespace"}
        except OSError as e:
            logger.error(f"OS error accessing {netns_path}: {e}")
            return {"success": False, "error": f"Cannot access container PID {container_pid} network namespace: {e}"}

        logger.info(f"Looking for interface with MAC {mac_address} in container PID {container_pid}")
        
        # Retry interface discovery with backoff - interface may not be immediately
        # visible after network.connect() due to kernel/Docker timing
        max_retries = 10
        retry_delay = 0.3  # seconds
        interface = None
        
        for attempt in range(max_retries):
            interface = self._find_interface_by_mac(container_pid, mac_address)
            if interface:
                if attempt > 0:
                    logger.info(f"Found interface {interface} after {attempt + 1} attempts")
                break
            if attempt < max_retries - 1:
                logger.debug(f"Interface with MAC {mac_address} not found, retrying ({attempt + 1}/{max_retries})...")
                time.sleep(retry_delay)
        
        if not interface:
            logger.error(f"Interface with MAC {mac_address} not found in container PID {container_pid} after {max_retries} attempts")
            return {"success": False, "error": f"Interface with MAC {mac_address} not found in container after {max_retries} retries"}

        logger.info(f"Starting DHCP client for {key} on interface {interface} (MAC: {mac_address})")

        try:
            # Create unique lease file key by replacing : with _ (filesystem-safe)
            lease_key = key.replace(":", "_")
            
            # Set up environment with ORCH_DHCP_KEY for the udhcpc script
            # This ensures each container:vnic gets its own lease file
            env = os.environ.copy()
            env["ORCH_DHCP_KEY"] = lease_key
            
            # Run udhcpc inside the container's network namespace
            # -f: foreground, -i: interface, -s: script, -t: retries, -T: timeout
            proc = subprocess.Popen(
                [
                    "nsenter", "-t", str(container_pid), "-n",
                    "udhcpc", "-f", "-i", interface,
                    "-s", "/usr/share/udhcpc/default.script",
                    "-t", "5", "-T", "3",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            self.dhcp_processes[key] = proc

            # Store metadata for lease monitoring - use unique lease file per container:vnic
            lease_file = os.path.join(DHCP_LEASE_DIR, f"{lease_key}.lease")
            self.last_lease_state[key] = {
                "container_name": container_name,
                "vnic_name": vnic_name,
                "mac_address": mac_address,
                "interface": interface,
                "lease_file": lease_file,
                "lease_key": lease_key,
                "pid": container_pid,
            }

            logger.info(f"DHCP client started for {key} (PID: {proc.pid})")
            return {"success": True, "message": f"DHCP client started for {interface}"}

        except Exception as e:
            logger.error(f"Failed to start DHCP client for {key}: {e}")
            return {"success": False, "error": str(e)}

    def stop_dhcp(self, key: str) -> Dict[str, Any]:
        """Stop a DHCP client by key (container_name:vnic_name)."""
        if key not in self.dhcp_processes:
            return {"success": False, "error": f"No DHCP client found for {key}"}

        proc = self.dhcp_processes[key]
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            del self.dhcp_processes[key]
            if key in self.last_lease_state:
                del self.last_lease_state[key]
            logger.info(f"DHCP client stopped for {key}")
            return {"success": True, "message": f"DHCP client stopped for {key}"}
        except Exception as e:
            logger.error(f"Error stopping DHCP client for {key}: {e}")
            return {"success": False, "error": str(e)}

    def _monitor_leases(self):
        """Monitor lease files for changes and send updates."""
        while self.running:
            try:
                for key, state in list(self.last_lease_state.items()):
                    lease_file = state.get("lease_file")
                    if not lease_file or not os.path.exists(lease_file):
                        continue

                    try:
                        with open(lease_file, "r") as f:
                            lease_data = json.load(f)

                        # Check if lease has changed
                        current_ip = lease_data.get("ip")
                        last_ip = state.get("last_ip")

                        if current_ip and current_ip != last_ip:
                            state["last_ip"] = current_ip
                            logger.info(
                                f"DHCP lease update for {key}: IP={current_ip}"
                            )

                            # Send dhcp_update event to orchestrator
                            event = {
                                "type": "dhcp_update",
                                "data": {
                                    "container_name": state["container_name"],
                                    "vnic_name": state["vnic_name"],
                                    "mac_address": state["mac_address"],
                                    "ip": current_ip,
                                    "mask": lease_data.get("mask"),
                                    "prefix": lease_data.get("prefix"),
                                    "gateway": lease_data.get("router"),
                                    "dns": lease_data.get("dns"),
                                    "lease_time": lease_data.get("lease"),
                                    "timestamp": lease_data.get("timestamp"),
                                },
                            }
                            self.send_event(event)

                    except json.JSONDecodeError:
                        pass  # Lease file being written
                    except Exception as e:
                        logger.debug(f"Error reading lease file {lease_file}: {e}")

                # Check for dead DHCP processes and restart them
                for key, proc in list(self.dhcp_processes.items()):
                    if proc.poll() is not None:
                        logger.warning(f"DHCP client for {key} died, restarting...")
                        state = self.last_lease_state.get(key)
                        if state and state.get("pid"):
                            self.start_dhcp(
                                state["container_name"],
                                state["vnic_name"],
                                state["mac_address"],
                                state["pid"],
                            )
                        else:
                            logger.error(f"Cannot restart DHCP for {key}: missing PID in state")

            except Exception as e:
                logger.error(f"Error in lease monitor: {e}")

            time.sleep(2)

    def get_status(self) -> Dict[str, Any]:
        """Get status of all DHCP clients."""
        status = {}
        for key, proc in self.dhcp_processes.items():
            state = self.last_lease_state.get(key, {})
            status[key] = {
                "running": proc.poll() is None,
                "pid": proc.pid,
                "last_ip": state.get("last_ip"),
                "interface": state.get("interface"),
            }
        return status


class DeviceMonitor:
    """
    Monitor USB serial devices using pyudev for hot-plug detection.

    This class detects USB-to-serial adapters and native serial ports,
    providing device discovery on startup and real-time hotplug notifications.
    Events are sent to the orchestrator-agent which creates/removes device
    nodes inside vPLC containers dynamically (without container restart).

    Supported device types:
    - USB-to-serial adapters (ttyUSB*): FTDI, CH340, PL2303, CP210x, etc.
    - ACM modems (ttyACM*): Arduino, USB CDC devices
    - Native serial ports (ttyS*): Onboard UART ports
    """

    # Device major numbers for serial port types
    SERIAL_MAJORS = {
        188: "ttyUSB",  # USB-to-serial adapters
        166: "ttyACM",  # ACM modems (Arduino, etc.)
        4: "ttyS",      # Native serial ports (minor 64-255)
    }

    def __init__(self, send_event_callback):
        """
        Initialize the device monitor.

        Args:
            send_event_callback: Function to call with device events.
                                 Events are dicts with 'type' and 'data' keys.
        """
        self.send_event = send_event_callback
        self.context = None
        self.monitor = None
        self.monitor_thread = None
        self.running = False
        self.device_cache: Dict[str, Dict] = {}  # by_id -> device_info

    def start(self):
        """Start monitoring for device events."""
        if not PYUDEV_AVAILABLE:
            logger.warning("pyudev not available, serial device monitoring disabled")
            return

        try:
            self.context = pyudev.Context()
            self.monitor = pyudev.Monitor.from_netlink(self.context)
            # Monitor tty subsystem for serial devices
            self.monitor.filter_by(subsystem='tty')

            self.running = True
            self.monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True
            )
            self.monitor_thread.start()

            logger.info("Serial device monitor started")

        except Exception as e:
            logger.error(f"Failed to start device monitor: {e}")
            self.running = False

    def stop(self):
        """Stop the device monitor."""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
        logger.info("Serial device monitor stopped")

    def get_current_devices(self) -> List[Dict]:
        """
        Enumerate all currently connected serial devices.

        Returns:
            List of device info dicts, each containing:
            - path: Device node path (e.g., /dev/ttyUSB0)
            - by_id: Stable identifier path (e.g., /dev/serial/by-id/usb-FTDI_...)
            - major: Device major number
            - minor: Device minor number
            - vendor_id: USB vendor ID (if available)
            - product_id: USB product ID (if available)
            - serial: USB serial number (if available)
            - subsystem: Always 'tty'
            - manufacturer: Device manufacturer (if available)
            - product: Product name (if available)
        """
        if not PYUDEV_AVAILABLE:
            return []

        devices = []
        try:
            context = self.context or pyudev.Context()

            for device in context.list_devices(subsystem='tty'):
                device_info = self._build_device_info(device)
                if device_info:
                    devices.append(device_info)
                    # Update cache
                    by_id = device_info.get("by_id")
                    if by_id:
                        self.device_cache[by_id] = device_info

        except Exception as e:
            logger.error(f"Failed to enumerate serial devices: {e}")

        return devices

    def _build_device_info(self, device) -> Optional[Dict]:
        """
        Extract device information from a pyudev device object.

        Filters to only include actual serial port devices (ttyUSB*, ttyACM*, ttyS*),
        excluding pseudo-terminals and other non-serial tty devices.

        Args:
            device: pyudev Device object

        Returns:
            Device info dict or None if device should be filtered out.
        """
        try:
            device_node = device.device_node
            if not device_node:
                return None

            # Filter to only serial port devices
            basename = os.path.basename(device_node)
            if not (basename.startswith('ttyUSB') or
                    basename.startswith('ttyACM') or
                    basename.startswith('ttyS')):
                return None

            # Get device numbers
            try:
                stat_info = os.stat(device_node)
                major = os.major(stat_info.st_rdev)
                minor = os.minor(stat_info.st_rdev)
            except (OSError, FileNotFoundError):
                # Device may have been removed
                return None

            # For ttyS devices, only include minor >= 64 (real serial ports)
            # Minor 0-63 are typically virtual console devices
            if basename.startswith('ttyS') and minor < 64:
                return None

            # Get stable by-id path
            by_id_path = self._get_by_id_path(device)

            # Get USB device properties (may not be available for native serial ports)
            vendor_id = device.get('ID_VENDOR_ID')
            product_id = device.get('ID_MODEL_ID')
            serial = device.get('ID_SERIAL_SHORT')
            manufacturer = device.get('ID_VENDOR') or device.get('ID_VENDOR_FROM_DATABASE')
            product = device.get('ID_MODEL') or device.get('ID_MODEL_FROM_DATABASE')

            device_info = {
                "path": device_node,
                "by_id": by_id_path,
                "major": major,
                "minor": minor,
                "vendor_id": vendor_id,
                "product_id": product_id,
                "serial": serial,
                "subsystem": "tty",
                "manufacturer": manufacturer,
                "product": product,
            }

            return device_info

        except Exception as e:
            logger.debug(f"Error building device info: {e}")
            return None

    def _get_by_id_path(self, device) -> Optional[str]:
        """
        Get the stable /dev/serial/by-id/ path for a device.

        This path contains the USB serial number and remains constant
        regardless of which USB port the device is plugged into.

        Args:
            device: pyudev Device object

        Returns:
            The by-id symlink path, or None if not available.
        """
        try:
            device_node = device.device_node
            if not device_node:
                return None

            # Check /dev/serial/by-id/ for symlinks pointing to this device
            by_id_dir = "/dev/serial/by-id"
            if os.path.isdir(by_id_dir):
                for entry in os.listdir(by_id_dir):
                    entry_path = os.path.join(by_id_dir, entry)
                    if os.path.islink(entry_path):
                        target = os.path.realpath(entry_path)
                        if target == os.path.realpath(device_node):
                            return entry_path

            # Fallback: use ID_SERIAL property to construct expected path
            id_serial = device.get('ID_SERIAL')
            if id_serial:
                # Construct expected by-id path format
                expected_path = f"/dev/serial/by-id/{id_serial}"
                if os.path.exists(expected_path):
                    return expected_path

            return None

        except Exception as e:
            logger.debug(f"Error getting by-id path: {e}")
            return None

    def _monitor_loop(self):
        """Background thread loop for monitoring device events."""
        logger.info("Device monitor thread started")

        try:
            # Use poll() for non-blocking monitoring
            self.monitor.start()

            while self.running:
                try:
                    # Poll with timeout to allow checking self.running
                    device = self.monitor.poll(timeout=1.0)
                    if device:
                        self._handle_device_event(device)
                except Exception as e:
                    if self.running:
                        logger.error(f"Error polling device events: {e}")

        except Exception as e:
            logger.error(f"Device monitor loop error: {e}")

        logger.info("Device monitor thread stopped")

    def _handle_device_event(self, device):
        """
        Handle a device add/remove event from udev.

        Args:
            device: pyudev Device object with action attribute
        """
        try:
            action = device.action

            if action not in ('add', 'remove'):
                return

            device_info = self._build_device_info(device)

            if action == 'add':
                if not device_info:
                    return

                by_id = device_info.get("by_id")
                logger.info(f"Serial device added: {device_info.get('path')} (by_id: {by_id})")

                # Update cache
                if by_id:
                    self.device_cache[by_id] = device_info

                # Send event
                event = {
                    "type": "device_change",
                    "data": {
                        "action": "add",
                        "device": device_info,
                    }
                }
                self.send_event(event)

            elif action == 'remove':
                device_node = device.device_node
                if not device_node:
                    return

                # For remove events, device_info may be incomplete
                # Try to find cached info by path
                removed_info = None
                removed_by_id = None

                for by_id, cached_info in list(self.device_cache.items()):
                    if cached_info.get("path") == device_node:
                        removed_info = cached_info
                        removed_by_id = by_id
                        break

                if removed_info:
                    logger.info(f"Serial device removed: {device_node} (by_id: {removed_by_id})")
                    del self.device_cache[removed_by_id]
                else:
                    # Build minimal info for devices not in cache
                    basename = os.path.basename(device_node)
                    if not (basename.startswith('ttyUSB') or
                            basename.startswith('ttyACM') or
                            basename.startswith('ttyS')):
                        return

                    logger.info(f"Serial device removed: {device_node}")
                    removed_info = {
                        "path": device_node,
                        "by_id": None,
                        "major": None,
                        "minor": None,
                        "subsystem": "tty",
                    }

                # Send event
                event = {
                    "type": "device_change",
                    "data": {
                        "action": "remove",
                        "device": removed_info,
                    }
                }
                self.send_event(event)

        except Exception as e:
            logger.error(f"Error handling device event: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get status of the device monitor."""
        return {
            "running": self.running,
            "pyudev_available": PYUDEV_AVAILABLE,
            "cached_devices": len(self.device_cache),
            "devices": list(self.device_cache.values()),
        }


class NetworkMonitor:
    def __init__(self):
        self.ipr = IPRoute()
        self.socket_path = SOCKET_PATH
        self.server_socket = None
        self.clients = []
        self.client_buffers: Dict[socket.socket, str] = {}
        self.running = True
        self.last_event_time = 0
        self.pending_changes = set()
        self.dhcp_manager = DHCPManager(self.send_event)
        self.device_monitor = DeviceMonitor(self.send_event)

    def setup_socket(self):
        """Create Unix domain socket for communication with orchestrator-agent"""
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.bind(self.socket_path)
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)

        os.chmod(self.socket_path, 0o666)
        logger.info(f"Unix socket created at {self.socket_path}")

    def get_interface_info(self, ifname: str) -> Optional[Dict]:
        """Get detailed information about a network interface"""
        try:
            links = self.ipr.link_lookup(ifname=ifname)
            if not links:
                return None

            idx = links[0]
            link_info = self.ipr.get_links(idx)[0]

            ifname = link_info.get_attr("IFLA_IFNAME")
            operstate = link_info.get_attr("IFLA_OPERSTATE")

            if operstate != "UP":
                return None

            addrs = self.ipr.get_addr(index=idx, family=socket.AF_INET)
            if not addrs:
                return None

            ipv4_addresses = []
            for addr in addrs:
                ip = addr.get_attr("IFA_ADDRESS")
                prefixlen = addr["prefixlen"]
                if ip:
                    try:
                        network = ipaddress.ip_network(
                            f"{ip}/{prefixlen}", strict=False
                        )
                        ipv4_addresses.append(
                            {
                                "address": ip,
                                "prefixlen": prefixlen,
                                "subnet": str(network.with_prefixlen),
                                "network_address": str(network.network_address),
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to parse IP {ip}/{prefixlen}: {e}")

            if not ipv4_addresses:
                return None

            gateway = self.get_default_gateway(ifname)

            return {
                "interface": ifname,
                "index": idx,
                "operstate": operstate,
                "ipv4_addresses": ipv4_addresses,
                "gateway": gateway,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to get info for interface {ifname}: {e}")
            return None

    def get_default_gateway(self, ifname: str) -> Optional[str]:
        """Get the default gateway for an interface"""
        try:
            routes = self.ipr.get_default_routes(family=socket.AF_INET)
            for route in routes:
                oif = route.get_attr("RTA_OIF")
                if oif:
                    links = self.ipr.get_links(oif)
                    if links:
                        route_ifname = links[0].get_attr("IFLA_IFNAME")
                        if route_ifname == ifname:
                            gateway = route.get_attr("RTA_GATEWAY")
                            if gateway:
                                return gateway
            return None
        except Exception as e:
            logger.error(f"Failed to get gateway for {ifname}: {e}")
            return None

    def discover_all_interfaces(self) -> List[Dict]:
        """Discover all active network interfaces with IPv4 addresses"""
        interfaces = []
        try:
            links = self.ipr.get_links()
            for link in links:
                ifname = link.get_attr("IFLA_IFNAME")

                if ifname in ["lo", "docker0"] or ifname.startswith("veth"):
                    continue

                info = self.get_interface_info(ifname)
                if info:
                    interfaces.append(info)
                    logger.info(
                        f"Discovered interface: {ifname} with {len(info['ipv4_addresses'])} IPv4 address(es)"
                    )

        except Exception as e:
            logger.error(f"Failed to discover interfaces: {e}")

        return interfaces

    def send_event(self, event: Dict):
        """Send event to all connected clients"""
        event_json = json.dumps(event) + "\n"
        event_bytes = event_json.encode("utf-8")

        disconnected = []
        for client in self.clients:
            try:
                client.sendall(event_bytes)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                disconnected.append(client)

        for client in disconnected:
            try:
                client.close()
            except Exception:
                pass
            self.clients.remove(client)

    def handle_netlink_event(self, msg):
        """Handle netlink events for address and route changes"""
        try:
            event_type = msg["event"]

            if event_type in [
                "RTM_NEWADDR",
                "RTM_DELADDR",
                "RTM_NEWROUTE",
                "RTM_DELROUTE",
            ]:
                idx = msg.get("index")
                if idx:
                    try:
                        links = self.ipr.get_links(idx)
                        if links:
                            ifname = links[0].get_attr("IFLA_IFNAME")
                            if (
                                ifname
                                and not ifname.startswith("veth")
                                and ifname not in ["lo", "docker0"]
                            ):
                                self.pending_changes.add(ifname)
                                self.last_event_time = time.time()
                                logger.debug(f"Network event on {ifname}: {event_type}")
                    except NetlinkError as e:
                        if e.code == 19:
                            logger.debug(f"Interface no longer exists (ENODEV): {e}")
                        else:
                            logger.error(f"Netlink error handling event: {e}")

        except Exception as e:
            logger.error(f"Error handling netlink event: {e}")

    def process_pending_changes(self):
        """Process pending network changes after debounce period"""
        if not self.pending_changes:
            return

        if time.time() - self.last_event_time < DEBOUNCE_SECONDS:
            return

        logger.info(f"Processing changes for interfaces: {self.pending_changes}")

        for ifname in self.pending_changes:
            info = self.get_interface_info(ifname)
            if info:
                event = {"type": "network_change", "data": info}
                self.send_event(event)
                logger.info(f"Sent network change event for {ifname}")

        self.pending_changes.clear()

    def handle_command(self, client: socket.socket, command: Dict) -> Dict:
        """Handle a command from a client."""
        cmd_type = command.get("command")
        logger.info(f"Received command: {cmd_type}")

        if cmd_type == "start_dhcp":
            container_name = command.get("container_name")
            vnic_name = command.get("vnic_name")
            mac_address = command.get("mac_address")
            container_pid = command.get("container_pid")
            
            # Validate each parameter explicitly for better error messages
            if not container_name:
                logger.error("start_dhcp: missing container_name")
                return {"success": False, "error": "Missing container_name"}
            if not vnic_name:
                logger.error("start_dhcp: missing vnic_name")
                return {"success": False, "error": "Missing vnic_name"}
            if not mac_address:
                logger.error("start_dhcp: missing mac_address")
                return {"success": False, "error": "Missing mac_address"}
            if container_pid is None:
                logger.error("start_dhcp: missing container_pid")
                return {"success": False, "error": "Missing container_pid"}
            
            # Ensure container_pid is an integer (JSON may send it as string)
            try:
                container_pid = int(container_pid)
            except (ValueError, TypeError) as e:
                logger.error(f"start_dhcp: invalid container_pid type: {type(container_pid)}, value: {container_pid}")
                return {"success": False, "error": f"Invalid container_pid: {container_pid}"}
            
            logger.info(f"start_dhcp: container={container_name}, vnic={vnic_name}, mac={mac_address}, pid={container_pid}")
            result = self.dhcp_manager.start_dhcp(container_name, vnic_name, mac_address, container_pid)
            logger.info(f"start_dhcp result: {result}")
            return result

        elif cmd_type == "stop_dhcp":
            container_name = command.get("container_name")
            vnic_name = command.get("vnic_name")
            if not all([container_name, vnic_name]):
                return {"success": False, "error": "Missing required parameters"}
            key = f"{container_name}:{vnic_name}"
            return self.dhcp_manager.stop_dhcp(key)

        elif cmd_type == "get_dhcp_status":
            return {"success": True, "status": self.dhcp_manager.get_status()}

        elif cmd_type == "get_device_status":
            return {"success": True, "status": self.device_monitor.get_status()}

        elif cmd_type == "discover_devices":
            # Force re-enumeration of serial devices
            devices = self.device_monitor.get_current_devices()
            return {"success": True, "devices": devices}

        else:
            return {"success": False, "error": f"Unknown command: {cmd_type}"}

    def process_client_data(self, client: socket.socket):
        """Process incoming data from a client."""
        try:
            data = client.recv(4096)
            if not data:
                return False

            if client not in self.client_buffers:
                self.client_buffers[client] = ""

            self.client_buffers[client] += data.decode("utf-8")

            while "\n" in self.client_buffers[client]:
                line, self.client_buffers[client] = self.client_buffers[client].split(
                    "\n", 1
                )
                if line.strip():
                    try:
                        command = json.loads(line)
                        response = self.handle_command(client, command)
                        response_json = json.dumps(response) + "\n"
                        client.sendall(response_json.encode("utf-8"))
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON from client: {e}")
                        error_response = json.dumps(
                            {"success": False, "error": "Invalid JSON"}
                        ) + "\n"
                        client.sendall(error_response.encode("utf-8"))

            return True
        except Exception as e:
            logger.warning(f"Error processing client data: {e}")
            return False

    def accept_clients(self):
        """Accept new client connections"""
        try:
            client, addr = self.server_socket.accept()
            client.setblocking(False)
            self.clients.append(client)
            self.client_buffers[client] = ""
            logger.info("New client connected")

            interfaces = self.discover_all_interfaces()
            discovery_event = {
                "type": "network_discovery",
                "data": {
                    "interfaces": interfaces,
                    "timestamp": datetime.now().isoformat(),
                },
            }

            try:
                event_json = json.dumps(discovery_event) + "\n"
                client.sendall(event_json.encode("utf-8"))
                logger.info(
                    f"Sent network discovery with {len(interfaces)} interfaces to new client"
                )
            except Exception as e:
                logger.error(f"Failed to send network discovery data: {e}")

            # Send device discovery (serial devices)
            devices = self.device_monitor.get_current_devices()
            device_discovery_event = {
                "type": "device_discovery",
                "data": {
                    "devices": devices,
                    "timestamp": datetime.now().isoformat(),
                },
            }

            try:
                event_json = json.dumps(device_discovery_event) + "\n"
                client.sendall(event_json.encode("utf-8"))
                logger.info(
                    f"Sent device discovery with {len(devices)} serial devices to new client"
                )
            except Exception as e:
                logger.error(f"Failed to send device discovery data: {e}")

        except socket.timeout:
            pass
        except Exception as e:
            logger.error(f"Error accepting client: {e}")

    def run(self):
        """Main event loop"""
        logger.info("Starting Autonomy Network Monitor")

        self.setup_socket()

        self.ipr.bind()

        self.dhcp_manager.start()
        self.device_monitor.start()

        logger.info("Monitoring network and device changes...")

        while self.running:
            try:
                self.accept_clients()

                # Process incoming commands from clients
                disconnected = []
                for client in self.clients:
                    try:
                        readable, _, _ = select.select([client], [], [], 0)
                        if readable:
                            if not self.process_client_data(client):
                                disconnected.append(client)
                    except Exception as e:
                        logger.warning(f"Error checking client: {e}")
                        disconnected.append(client)

                for client in disconnected:
                    try:
                        client.close()
                    except Exception:
                        pass
                    if client in self.clients:
                        self.clients.remove(client)
                    if client in self.client_buffers:
                        del self.client_buffers[client]

                msgs = self.ipr.get()
                for msg in msgs:
                    self.handle_netlink_event(msg)

                self.process_pending_changes()

                time.sleep(0.1)

            except KeyboardInterrupt:
                logger.info("Received interrupt signal")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(1)

        self.cleanup()

    def cleanup(self):
        """Cleanup resources"""
        logger.info("Shutting down...")

        self.dhcp_manager.stop()
        self.device_monitor.stop()

        for client in self.clients:
            try:
                client.close()
            except Exception:
                pass

        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass

        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except Exception:
                pass

        try:
            self.ipr.close()
        except Exception:
            pass

        logger.info("Shutdown complete")


def signal_handler(signum, frame):
    """Handle termination signals"""
    logger.info(f"Received signal {signum}")
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    monitor = NetworkMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
