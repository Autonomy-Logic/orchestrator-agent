#!/usr/bin/env python3
"""
Autonomy Network Monitor Daemon

Monitors host network interfaces for changes and reports them to the orchestrator-agent
via Unix domain socket. Provides network discovery, real-time change notifications,
and DHCP client management for runtime containers.
"""

import errno
import json
import logging
import os
import queue
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
import ipaddress

try:
    from pyroute2 import IPRoute, NetlinkError
except ImportError:
    print("ERROR: pyroute2 is not installed. Install it with: pip3 install pyroute2")
    sys.exit(1)

# Netlink socket buffer size (2MB) - larger buffer helps during event bursts
NETLINK_RCVBUF_SIZE = 2 * 1024 * 1024

# Events we care about for network monitoring
RELEVANT_NETLINK_EVENTS = frozenset([
    "RTM_NEWADDR",
    "RTM_DELADDR",
    "RTM_NEWROUTE",
    "RTM_DELROUTE",
    "RTM_NEWLINK",
    "RTM_DELLINK",
])

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


def get_interface_type(ifname: str) -> str:
    """
    Detect if a network interface is WiFi or Ethernet.

    This information is used by the orchestrator-agent to select the appropriate
    networking method:
    - WiFi interfaces use Proxy ARP Bridge (traffic routes through host's WiFi MAC)
    - Ethernet interfaces use MACVLAN (unique MAC per container)

    Detection methods (in order of priority):
    1. Check /sys/class/net/{ifname}/wireless directory (most reliable)
    2. Check /sys/class/net/{ifname}/phy80211 symlink (alternative indicator)
    3. Check interface name patterns (wlan*, wlp*, wlx*) as fallback

    Args:
        ifname: Network interface name (e.g., "eth0", "wlan0", "enp0s3", "wlp2s0")

    Returns:
        "wifi" for wireless interfaces, "ethernet" for wired interfaces
    """
    # Method 1: Check for wireless sysfs directory
    # This directory exists for all wireless interfaces managed by cfg80211
    wireless_path = f"/sys/class/net/{ifname}/wireless"
    if os.path.exists(wireless_path):
        logger.debug(f"Interface {ifname} detected as WiFi (wireless sysfs exists)")
        return "wifi"

    # Method 2: Check for phy80211 symlink
    # This symlink points to the wireless PHY device
    phy_path = f"/sys/class/net/{ifname}/phy80211"
    if os.path.exists(phy_path):
        logger.debug(f"Interface {ifname} detected as WiFi (phy80211 exists)")
        return "wifi"

    # Method 3: Check interface name patterns (fallback)
    # Common WiFi interface naming conventions:
    # - wlan*: Traditional naming (wlan0, wlan1)
    # - wlp*: Predictable naming by PCI path (wlp2s0, wlp3s0)
    # - wlx*: Predictable naming by MAC address (wlx001122334455)
    if ifname.startswith(("wlan", "wlp", "wlx")):
        logger.debug(f"Interface {ifname} detected as WiFi (name pattern)")
        return "wifi"

    logger.debug(f"Interface {ifname} detected as Ethernet (default)")
    return "ethernet"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


# ========== Proxy ARP Bridge Functions ==========


def _write_sysctl(key: str, value: str):
    """Write a sysctl value, trying /proc/sys first then sysctl command."""
    proc_path = "/proc/sys/" + key.replace(".", "/")
    try:
        with open(proc_path, "w") as f:
            f.write(value)
        return
    except (OSError, IOError):
        pass
    # Fallback to sysctl command
    try:
        subprocess.run(
            ["sysctl", "-w", f"{key}={value}"],
            check=True, capture_output=True,
        )
    except Exception as e:
        logger.warning(f"Could not set sysctl {key}={value}: {e}")


def subnet_to_prefix_len(subnet: str) -> int:
    """
    Convert a subnet specification to CIDR prefix length.

    Accepts multiple formats:
    - Dotted netmask: "255.255.255.0" -> 24
    - CIDR network: "192.168.1.0/24" -> 24
    - Bare prefix: "24" -> 24

    Args:
        subnet: Subnet in any of the formats above

    Returns:
        Integer prefix length (e.g., 24)
    """
    if "/" in subnet:
        # CIDR format: "192.168.1.0/24" -> 24
        return int(subnet.split("/")[1])
    if "." in subnet:
        # Dotted netmask: "255.255.255.0" -> 24
        return sum(bin(int(octet)).count("1") for octet in subnet.split("."))
    # Bare prefix: "24" -> 24
    return int(subnet)


def setup_proxy_arp_bridge(
    container_name: str,
    container_pid: int,
    parent_interface: str,
    ip_address: str,
    gateway: str,
    subnet_mask: str = "255.255.255.0",
) -> dict:
    """
    Set up Proxy ARP bridge for a container on a WiFi interface.

    Creates a veth pair, configures routing, and enables proxy ARP
    so the container can be reached on the WiFi network.

    Args:
        container_name: Name of the container
        container_pid: PID of container's init process
        parent_interface: WiFi interface (e.g., "wlan0")
        ip_address: IP address for container (from DHCP or static)
        gateway: Gateway address
        subnet_mask: Subnet mask (default 255.255.255.0)

    Returns:
        dict with veth names and configuration details
    """
    short_id = container_name[:8]
    veth_host = f"veth-{short_id}"
    veth_container = "eth1"

    logger.info(
        f"Setting up Proxy ARP bridge for {container_name}: "
        f"IP={ip_address}, interface={parent_interface}"
    )

    try:
        # 1. Create veth pair
        logger.debug(f"Creating veth pair: {veth_host} <-> {veth_container}")
        subprocess.run(
            ["ip", "link", "add", veth_host, "type", "veth", "peer", "name", veth_container],
            check=True, capture_output=True,
        )

        # 2. Move one end to container's network namespace
        logger.debug(f"Moving {veth_container} to container netns (PID {container_pid})")
        subprocess.run(
            ["ip", "link", "set", veth_container, "netns", str(container_pid)],
            check=True, capture_output=True,
        )

        # 3. Configure container's interface with IP
        prefix_len = subnet_to_prefix_len(subnet_mask)

        subprocess.run(
            ["nsenter", "-t", str(container_pid), "-n",
             "ip", "addr", "add", f"{ip_address}/{prefix_len}", "dev", veth_container],
            check=True, capture_output=True,
        )

        subprocess.run(
            ["nsenter", "-t", str(container_pid), "-n",
             "ip", "link", "set", veth_container, "up"],
            check=True, capture_output=True,
        )

        # Add (or replace) default route in container pointing to gateway
        # Using "replace" instead of "add" because Docker may have already installed
        # a default route via the internal bridge network
        logger.debug(f"Adding default route via {gateway} in container")
        subprocess.run(
            ["nsenter", "-t", str(container_pid), "-n",
             "ip", "route", "replace", "default", "via", gateway, "dev", veth_container],
            check=True, capture_output=True,
        )

        # 4. Configure host's end of veth
        logger.debug(f"Bringing up {veth_host} on host")
        subprocess.run(["ip", "link", "set", veth_host, "up"], check=True, capture_output=True)

        # Enable proxy_arp on the veth interface
        _write_sysctl(f"net.ipv4.conf.{veth_host}.proxy_arp", "1")

        # 5. Enable proxy ARP on WiFi interface
        logger.debug(f"Enabling proxy_arp on {parent_interface}")
        _write_sysctl(f"net.ipv4.conf.{parent_interface}.proxy_arp", "1")

        # 6. Enable IP forwarding
        _write_sysctl("net.ipv4.ip_forward", "1")

        # 7. Add route to container IP via veth
        logger.debug(f"Adding route: {ip_address}/32 dev {veth_host}")
        subprocess.run(
            ["ip", "route", "add", f"{ip_address}/32", "dev", veth_host],
            check=True, capture_output=True,
        )

        # 8. Add proxy ARP entry
        logger.debug(f"Adding proxy ARP entry for {ip_address} on {parent_interface}")
        subprocess.run(
            ["ip", "neighbor", "add", "proxy", ip_address, "dev", parent_interface],
            check=True, capture_output=True,
        )

        # 9. Add iptables FORWARD rules
        # Docker sets FORWARD policy to DROP and only allows its own bridge traffic.
        # We need explicit rules to allow forwarding between the veth and WiFi interface.
        # Non-fatal: bridge still functions if iptables fails (e.g., no iptables backend).
        logger.debug(f"Adding iptables FORWARD rules for {veth_host} <-> {parent_interface}")
        try:
            subprocess.run(
                ["iptables", "-I", "FORWARD", "-i", veth_host, "-o", parent_interface, "-j", "ACCEPT"],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["iptables", "-I", "FORWARD", "-i", parent_interface, "-o", veth_host, "-j", "ACCEPT"],
                check=True, capture_output=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning(f"Could not add iptables FORWARD rules: {e}. "
                           "Forwarding may be blocked by Docker's default FORWARD DROP policy.")

        logger.info(f"Proxy ARP bridge setup complete for {container_name}")

        return {
            "veth_host": veth_host,
            "veth_container": veth_container,
            "ip_address": ip_address,
            "gateway": gateway,
            "parent_interface": parent_interface,
        }

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to set up Proxy ARP bridge for {container_name}: {e}")
        logger.error(f"Command output: {e.stderr.decode() if e.stderr else 'N/A'}")
        cleanup_proxy_arp_bridge(container_name, ip_address, parent_interface, veth_host)
        raise RuntimeError(f"Proxy ARP bridge setup failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error setting up Proxy ARP bridge: {e}")
        cleanup_proxy_arp_bridge(container_name, ip_address, parent_interface, veth_host)
        raise


def cleanup_proxy_arp_bridge(
    container_name: str,
    ip_address: str,
    parent_interface: str,
    veth_host: str,
) -> None:
    """
    Clean up Proxy ARP bridge configuration for a container.

    Removes proxy ARP neighbor entry, route, and veth pair.
    """
    logger.info(f"Cleaning up Proxy ARP bridge for {container_name}")

    if ip_address and parent_interface:
        try:
            subprocess.run(
                ["ip", "neighbor", "del", "proxy", ip_address, "dev", parent_interface],
                check=False, capture_output=True,
            )
            logger.debug(f"Removed proxy ARP entry for {ip_address}")
        except Exception as e:
            logger.debug(f"Could not remove proxy ARP entry: {e}")

    # Remove iptables FORWARD rules (best-effort, may already be gone)
    if veth_host and parent_interface:
        try:
            subprocess.run(
                ["iptables", "-D", "FORWARD", "-i", veth_host, "-o", parent_interface, "-j", "ACCEPT"],
                check=False, capture_output=True,
            )
            subprocess.run(
                ["iptables", "-D", "FORWARD", "-i", parent_interface, "-o", veth_host, "-j", "ACCEPT"],
                check=False, capture_output=True,
            )
            logger.debug(f"Removed iptables FORWARD rules for {veth_host}")
        except Exception as e:
            logger.debug(f"Could not remove iptables rules: {e}")

    if ip_address and veth_host:
        try:
            subprocess.run(
                ["ip", "route", "del", f"{ip_address}/32", "dev", veth_host],
                check=False, capture_output=True,
            )
            logger.debug(f"Removed route for {ip_address}")
        except Exception as e:
            logger.debug(f"Could not remove route: {e}")

    if veth_host:
        try:
            subprocess.run(
                ["ip", "link", "del", veth_host],
                check=False, capture_output=True,
            )
            logger.debug(f"Removed veth pair {veth_host}")
        except Exception as e:
            logger.debug(f"Could not remove veth pair: {e}")

    logger.info(f"Proxy ARP bridge cleanup complete for {container_name}")


def cleanup_all_proxy_arp() -> dict:
    """
    Clean up all Proxy ARP veth interfaces and their associated proxy ARP entries.

    Finds all veth-* interfaces on the host and removes them along with
    any proxy neighbor entries. Used during selfdestruct for bulk cleanup.

    Returns:
        dict with success status and count of removed interfaces
    """
    logger.info("Cleaning up all Proxy ARP veth interfaces...")

    try:
        result = subprocess.run(
            ["ip", "-o", "link", "show"],
            capture_output=True, text=True, timeout=10,
        )

        veths_removed = 0
        for line in result.stdout.split("\n"):
            parts = line.split(":")
            if len(parts) >= 2:
                iface_name = parts[1].strip().split("@")[0]
                if iface_name.startswith("veth-"):
                    logger.info(f"Removing Proxy ARP veth: {iface_name}")
                    try:
                        subprocess.run(
                            ["ip", "link", "del", iface_name],
                            check=False, capture_output=True, timeout=5,
                        )
                        veths_removed += 1
                    except Exception as e:
                        logger.warning(f"Could not remove veth {iface_name}: {e}")

        # Also clean up any proxy ARP neighbor entries
        try:
            neigh_result = subprocess.run(
                ["ip", "neighbor", "show", "proxy"],
                capture_output=True, text=True, timeout=10,
            )
            for line in neigh_result.stdout.strip().split("\n"):
                if line.strip():
                    # Format: "IP dev INTERFACE"
                    parts = line.split()
                    if len(parts) >= 3:
                        ip_addr = parts[0]
                        dev_iface = parts[2]
                        try:
                            subprocess.run(
                                ["ip", "neighbor", "del", "proxy", ip_addr, "dev", dev_iface],
                                check=False, capture_output=True, timeout=5,
                            )
                            logger.debug(f"Removed proxy ARP entry: {ip_addr} dev {dev_iface}")
                        except Exception as e:
                            logger.debug(f"Could not remove proxy entry: {e}")
        except Exception as e:
            logger.warning(f"Error cleaning proxy ARP entries: {e}")

        logger.info(f"Proxy ARP cleanup complete: {veths_removed} veths removed")
        return {"success": True, "veths_removed": veths_removed}

    except Exception as e:
        logger.warning(f"Error during Proxy ARP cleanup: {e}")
        return {"success": False, "error": str(e)}


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
        self,
        container_name: str,
        vnic_name: str,
        mac_address: str,
        container_pid: int,
    ) -> Dict[str, Any]:
        """Start a DHCP client for a container's MACVLAN vNIC.

        For MACVLAN networks (Ethernet), the DHCP server identifies clients by MAC address.
        WiFi interfaces use a separate Proxy ARP mechanism with request_wifi_dhcp().

        Args:
            container_name: Name of the container
            vnic_name: Name of the virtual NIC
            mac_address: MAC address of the interface (used for MACVLAN lookup)
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

        # Find the MACVLAN interface by MAC address
        max_retries = 10
        retry_delay = 0.3  # seconds
        interface = None

        logger.info(f"Looking for interface with MAC {mac_address} in container PID {container_pid}")
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

        logger.info(f"Starting DHCP client for {key} on interface {interface} [MACVLAN (MAC: {mac_address})]")

        try:
            # Create unique lease file key by replacing : with _ (filesystem-safe)
            lease_key = key.replace(":", "_")

            # Set up environment with ORCH_DHCP_KEY for the udhcpc script
            # This ensures each container:vnic gets its own lease file
            env = os.environ.copy()
            env["ORCH_DHCP_KEY"] = lease_key

            # Build udhcpc command
            # -f: foreground, -i: interface, -s: script, -t: retries, -T: timeout
            cmd = [
                "nsenter", "-t", str(container_pid), "-n",
                "udhcpc", "-f", "-i", interface,
                "-s", "/usr/share/udhcpc/default.script",
                "-t", "5", "-T", "3",
            ]

            proc = subprocess.Popen(
                cmd,
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

    def request_wifi_dhcp(
        self,
        container_name: str,
        vnic_name: str,
        parent_interface: str,
        container_pid: int,
        client_id: str,
    ) -> Dict[str, Any]:
        """
        Request DHCP for a WiFi vNIC using Proxy ARP method.

        Unlike standard DHCP which runs inside the container, Proxy ARP DHCP
        runs on the host's WiFi interface with a unique client-id (DHCP option 61).
        This allows multiple containers to obtain different IPs on the same WiFi network.

        The DHCP response is monitored via lease files and sent as a dhcp_update event.

        Args:
            container_name: Name of the container
            vnic_name: Name of the virtual NIC
            parent_interface: WiFi interface on host (e.g., "wlan0")
            container_pid: PID of the container (for proxy ARP setup later)
            client_id: Unique identifier for DHCP option 61

        Returns:
            Dict with success status. Actual IP comes via dhcp_update event.
        """
        key = f"{container_name}:{vnic_name}"

        if key in self.dhcp_processes:
            proc = self.dhcp_processes[key]
            if proc.poll() is None:
                logger.info(f"WiFi DHCP client already running for {key}")
                return {"success": True, "message": "WiFi DHCP client already running"}

        logger.info(
            f"Starting WiFi DHCP for {key} on {parent_interface} with client-id: {client_id}"
        )

        try:
            # Create unique lease file key
            lease_key = key.replace(":", "_")

            # Set up environment for the udhcpc script
            env = os.environ.copy()
            env["ORCH_DHCP_KEY"] = lease_key

            # Encode client-id as hex for DHCP option 61
            client_id_hex = client_id.encode("utf-8").hex()

            # Run udhcpc on the host's WiFi interface (NOT inside container netns)
            # Uses wifi.script which only writes lease files (never touches the interface)
            # The -x option sets DHCP option 61 (Client Identifier)
            cmd = [
                "udhcpc",
                "-f",  # foreground
                "-i", parent_interface,  # WiFi interface on host
                "-s", "/usr/share/udhcpc/wifi.script",
                "-t", "5",  # retries
                "-T", "3",  # timeout
                "-x", f"0x3d:{client_id_hex}",  # Client Identifier (option 61)
            ]

            logger.info(f"Running WiFi DHCP: {' '.join(cmd)}")

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            self.dhcp_processes[key] = proc

            # Store metadata for lease monitoring
            lease_file = os.path.join(DHCP_LEASE_DIR, f"{lease_key}.lease")
            self.last_lease_state[key] = {
                "container_name": container_name,
                "vnic_name": vnic_name,
                "mac_address": None,  # WiFi shares parent MAC
                "interface": parent_interface,
                "lease_file": lease_file,
                "lease_key": lease_key,
                "pid": container_pid,
                "use_client_id": True,
                "is_wifi_proxy_arp": True,
                "client_id": client_id,
            }

            logger.info(f"WiFi DHCP client started for {key} (PID: {proc.pid})")
            return {"success": True, "message": f"WiFi DHCP client started on {parent_interface}"}

        except Exception as e:
            logger.error(f"Failed to start WiFi DHCP client for {key}: {e}")
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

                            # For WiFi Proxy ARP leases, set up the bridge automatically
                            proxy_arp_config = None
                            if state.get("is_wifi_proxy_arp"):
                                container_pid = state.get("pid")
                                parent_iface = state.get("interface")
                                gateway = lease_data.get("router")
                                mask = lease_data.get("mask", "255.255.255.0")

                                if container_pid and parent_iface and gateway:
                                    # Clean up old bridge if IP changed
                                    old_config = state.get("_proxy_arp_config")
                                    if old_config:
                                        try:
                                            cleanup_proxy_arp_bridge(
                                                state["container_name"],
                                                old_config.get("ip_address"),
                                                old_config.get("parent_interface"),
                                                old_config.get("veth_host"),
                                            )
                                        except Exception as e:
                                            logger.warning(f"Error cleaning old proxy ARP: {e}")

                                    try:
                                        proxy_arp_config = setup_proxy_arp_bridge(
                                            state["container_name"],
                                            container_pid,
                                            parent_iface,
                                            current_ip,
                                            gateway,
                                            mask,
                                        )
                                        state["_proxy_arp_config"] = proxy_arp_config
                                        logger.info(f"Proxy ARP bridge set up for {key} with IP {current_ip}")
                                    except Exception as e:
                                        logger.error(f"Failed to set up Proxy ARP bridge for {key}: {e}")
                                else:
                                    logger.warning(
                                        f"Cannot set up Proxy ARP for {key}: "
                                        f"pid={container_pid}, iface={parent_iface}, gw={gateway}"
                                    )

                            # Send dhcp_update event to orchestrator
                            event_data = {
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
                            }
                            if proxy_arp_config:
                                event_data["proxy_arp_config"] = proxy_arp_config

                            event = {
                                "type": "dhcp_update",
                                "data": event_data,
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
                            if state.get("is_wifi_proxy_arp"):
                                # WiFi Proxy ARP DHCP - restart with client_id
                                self.request_wifi_dhcp(
                                    state["container_name"],
                                    state["vnic_name"],
                                    state["interface"],
                                    state["pid"],
                                    state.get("client_id", f"{state['container_name']}:{state['vnic_name']}"),
                                )
                            else:
                                # MACVLAN DHCP - restart with MAC address
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

            # For ttyS devices, only include minor >= 64.
            # On most Linux systems, ttyS devices with minor numbers 0–63 are
            # reserved for legacy or virtual console/serial devices, while
            # minors >= 64 correspond to real hardware serial ports. We exclude
            # minors < 64 here to ignore virtual console devices and only track
            # actual serial ports.
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


class NetlinkReader:
    """
    Dedicated thread for reading netlink events from the kernel.

    This class solves the buffer overflow (ENOBUFS) problem by:
    1. Running in a dedicated thread that only reads netlink events
    2. Increasing the kernel socket receive buffer size
    3. Filtering events early to only queue relevant ones
    4. Implementing recovery strategies for errors

    The main loop can then consume events from the queue without
    blocking netlink reads.
    """

    # Recovery configuration
    MAX_CONSECUTIVE_ERRORS = 10
    ERROR_RESET_INTERVAL = 60  # Reset error count after 60s of no errors
    MAX_DRAIN_ITERATIONS = 1000  # Limit buffer drain iterations to prevent infinite loop
    BACKOFF_BASE = 0.1  # Base delay for exponential backoff (seconds)
    BACKOFF_MAX = 5.0  # Maximum backoff delay (seconds)

    def __init__(self, event_queue: queue.Queue):
        """
        Initialize the netlink reader.

        Args:
            event_queue: Thread-safe queue to put filtered events into
        """
        self.event_queue = event_queue
        self.ipr: Optional[IPRoute] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Recovery state
        self._consecutive_errors = 0
        self._last_error_time = 0
        self._degraded = False

    def _create_iproute(self) -> IPRoute:
        """Create and configure an IPRoute instance with larger buffer."""
        ipr = IPRoute()

        # Increase the netlink socket receive buffer
        # This gives more headroom during event bursts
        # Try multiple approaches for different pyroute2 versions
        buffer_set = False
        try:
            # Try to get the underlying socket file descriptor
            # pyroute2 stores the socket in different attributes depending on version
            sock_fd = None

            # Method 1: Direct fileno access (pyroute2 >= 0.5)
            if hasattr(ipr, 'fileno'):
                sock_fd = ipr.fileno()
            # Method 2: Through nlm_request (older versions)
            elif hasattr(ipr, 'nlm_request') and hasattr(ipr.nlm_request, 'fileno'):
                sock_fd = ipr.nlm_request.fileno()

            if sock_fd is not None:
                # Create a socket object from the file descriptor to set options
                # Use SOCK_DGRAM as netlink sockets behave like datagrams
                # Note: fromfd() duplicates the fd, so we must detach() to avoid closing it
                temp_sock = socket.fromfd(sock_fd, socket.AF_NETLINK, socket.SOCK_DGRAM)
                try:
                    old_size = temp_sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
                    temp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, NETLINK_RCVBUF_SIZE)
                    new_size = temp_sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
                    logger.info(f"Netlink socket receive buffer: {old_size} -> {new_size} bytes")
                    # Kernel typically doubles SO_RCVBUF to account for sk_buff overhead.
                    # If actual size differs from requested or 2x requested, it may be
                    # limited by net.core.rmem_max sysctl.
                    if new_size != NETLINK_RCVBUF_SIZE and new_size != NETLINK_RCVBUF_SIZE * 2:
                        logger.info(
                            f"Buffer size {new_size} differs from requested {NETLINK_RCVBUF_SIZE} "
                            f"(may be limited by net.core.rmem_max)"
                        )
                    buffer_set = True
                finally:
                    # Don't close temp_sock as it shares the fd with ipr
                    temp_sock.detach()

        except Exception as e:
            # If we can't set buffer size, log but continue
            # The kernel may limit it based on rmem_max
            logger.warning(f"Could not set netlink buffer size: {e}")

        if not buffer_set:
            logger.info("Using default netlink socket buffer size")

        return ipr

    def start(self):
        """Start the netlink reader thread."""
        if self.running:
            return

        self.running = True
        self._degraded = False
        self._consecutive_errors = 0

        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()
        logger.info("Netlink reader thread started")

    def stop(self):
        """Stop the netlink reader thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)

        with self._lock:
            if self.ipr:
                try:
                    self.ipr.close()
                except Exception:
                    pass
                self.ipr = None

        logger.info("Netlink reader thread stopped")

    def _reader_loop(self):
        """Main loop for reading netlink events."""
        logger.info("Netlink reader loop starting")

        # Create initial IPRoute instance
        with self._lock:
            self.ipr = self._create_iproute()
            self.ipr.bind()

        while self.running:
            try:
                # Check if we should reset error count
                if self._consecutive_errors > 0:
                    if time.time() - self._last_error_time > self.ERROR_RESET_INTERVAL:
                        self._consecutive_errors = 0
                        if self._degraded:
                            self._degraded = False
                            logger.info("Netlink reader recovered from degraded state")

                # Use select() to wait for data with timeout
                # This is efficient (blocks when no events) and allows graceful shutdown
                with self._lock:
                    if not self.ipr:
                        break
                    ipr = self.ipr

                # Get the file descriptor for select()
                try:
                    if hasattr(ipr, 'fileno'):
                        fd = ipr.fileno()
                    else:
                        # Fallback: try to read with a short timeout approach
                        fd = None
                except Exception:
                    fd = None

                if fd is not None:
                    # Wait for data with 1 second timeout
                    # This allows checking self.running periodically for graceful shutdown
                    readable, _, _ = select.select([fd], [], [], 1.0)
                    if not readable:
                        # Timeout - no data, loop back to check self.running
                        continue

                # Read messages from netlink (non-blocking now since select said data is ready)
                with self._lock:
                    if not self.ipr:
                        break
                    msgs = self.ipr.get()

                # Filter and queue relevant events
                for msg in msgs:
                    event_type = msg.get("event")
                    if event_type in RELEVANT_NETLINK_EVENTS:
                        # Don't block if queue is full - drop oldest events
                        try:
                            self.event_queue.put_nowait(msg)
                        except queue.Full:
                            # Queue is full, drop this event
                            # This shouldn't happen with a reasonably sized queue
                            logger.warning("Event queue full, dropping netlink event")

            except OSError as e:
                if e.errno == errno.ENOBUFS:
                    self._handle_enobufs()
                else:
                    self._handle_error(e)
            except Exception as e:
                self._handle_error(e)

        logger.info("Netlink reader loop stopped")

    def _handle_enobufs(self):
        """Handle ENOBUFS (buffer overflow) error with recovery strategy."""
        self._consecutive_errors += 1
        self._last_error_time = time.time()

        if not self._degraded:
            self._degraded = True
            logger.warning("Netlink buffer overflow detected, entering recovery mode")

        if self._consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
            # Too many consecutive errors - recreate the socket
            logger.warning(
                f"Persistent ENOBUFS after {self._consecutive_errors} attempts, "
                "recreating netlink socket"
            )
            self._recreate_socket()
            self._consecutive_errors = 0
        else:
            # Try to drain the buffer by reading rapidly
            self._drain_buffer()

    def _drain_buffer(self):
        """Attempt to drain the netlink buffer with rapid non-blocking reads."""
        drained = 0

        with self._lock:
            if not self.ipr:
                return

            for _ in range(self.MAX_DRAIN_ITERATIONS):
                try:
                    # Non-blocking read attempt
                    msgs = self.ipr.get()
                    if not msgs:
                        break
                    drained += len(msgs)

                    # Still filter and queue relevant events during drain
                    for msg in msgs:
                        event_type = msg.get("event")
                        if event_type in RELEVANT_NETLINK_EVENTS:
                            try:
                                self.event_queue.put_nowait(msg)
                            except queue.Full:
                                pass  # Drop during drain

                except OSError as e:
                    if e.errno == errno.ENOBUFS:
                        # Still overflowing, continue draining
                        continue
                    break
                except Exception:
                    break

        if drained > 0:
            logger.info(f"Drained {drained} messages from netlink buffer")

    def _recreate_socket(self):
        """Recreate the IPRoute socket as a last resort recovery."""
        with self._lock:
            # Close old socket
            if self.ipr:
                try:
                    self.ipr.close()
                except Exception:
                    pass

            # Create new socket
            try:
                self.ipr = self._create_iproute()
                self.ipr.bind()
                logger.info("Netlink socket recreated successfully")
            except Exception as e:
                logger.error(f"Failed to recreate netlink socket: {e}")
                # Will retry on next loop iteration
                self.ipr = None
                time.sleep(1)

    def _handle_error(self, error: Exception):
        """Handle generic errors in the reader loop."""
        self._consecutive_errors += 1
        self._last_error_time = time.time()

        if self._consecutive_errors <= 3:
            logger.error(f"Error reading netlink events: {error}")
        elif self._consecutive_errors == 4:
            logger.error(f"Suppressing repeated netlink errors (count: {self._consecutive_errors})")

        # Exponential backoff with cap
        backoff = min(2 ** self._consecutive_errors * self.BACKOFF_BASE, self.BACKOFF_MAX)
        time.sleep(backoff)

        # If too many errors, try recreating socket
        if self._consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
            logger.warning("Too many netlink errors, attempting socket recreation")
            self._recreate_socket()
            self._consecutive_errors = 0

    def is_degraded(self) -> bool:
        """Check if the reader is in degraded state."""
        return self._degraded

    def get_status(self) -> Dict[str, Any]:
        """Get status of the netlink reader."""
        return {
            "running": self.running,
            "degraded": self._degraded,
            "consecutive_errors": self._consecutive_errors,
            "socket_active": self.ipr is not None,
        }


class NetworkMonitor:
    # Maximum events to process per main loop iteration
    MAX_EVENTS_PER_ITERATION = 100
    # Size of the netlink event queue (from reader thread to main loop)
    NETLINK_QUEUE_SIZE = 1000

    def __init__(self):
        # IPRoute instance for queries (interface info, discovery, etc.)
        # This is separate from the netlink reader's socket
        self.ipr = IPRoute()

        # Event queue for netlink events (from dedicated reader thread)
        self.netlink_queue: queue.Queue = queue.Queue(maxsize=self.NETLINK_QUEUE_SIZE)
        self.netlink_reader = NetlinkReader(self.netlink_queue)

        self.socket_path = SOCKET_PATH
        self.server_socket = None
        self.clients = []
        self.client_buffers: Dict[socket.socket, str] = {}
        self.running = True
        self.last_event_time = 0
        self.pending_changes = set()
        self._last_degraded_log_time = 0
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
            iface_type = get_interface_type(ifname)

            return {
                "interface": ifname,
                "index": idx,
                "operstate": operstate,
                "type": iface_type,
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
        """Handle netlink events for address, route, and link changes"""
        try:
            event_type = msg["event"]

            # Handle interface deletion - extract name from message since interface is gone
            if event_type == "RTM_DELLINK":
                ifname = msg.get_attr("IFLA_IFNAME")
                if ifname and not ifname.startswith("veth") and ifname not in ["lo", "docker0"]:
                    logger.info(f"Interface deleted: {ifname}")
                    # Send immediate removal event (empty ipv4_addresses triggers cache removal)
                    event = {
                        "type": "network_change",
                        "data": {
                            "interface": ifname,
                            "ipv4_addresses": [],
                            "status": "removed",
                        }
                    }
                    self.send_event(event)
                return

            # Handle link state changes
            if event_type == "RTM_NEWLINK":
                idx = msg.get("index")
                if idx:
                    try:
                        links = self.ipr.get_links(idx)
                        if links:
                            link = links[0]
                            ifname = link.get_attr("IFLA_IFNAME")
                            operstate = link.get_attr("IFLA_OPERSTATE")

                            if ifname and not ifname.startswith("veth") and ifname not in ["lo", "docker0"]:
                                if operstate != "UP":
                                    # Interface is down - send immediate removal event
                                    logger.info(f"Interface down: {ifname} (state: {operstate})")
                                    event = {
                                        "type": "network_change",
                                        "data": {
                                            "interface": ifname,
                                            "ipv4_addresses": [],
                                            "status": "down",
                                        }
                                    }
                                    self.send_event(event)
                                else:
                                    # Interface is up - use debounced processing
                                    self.pending_changes.add(ifname)
                                    self.last_event_time = time.time()
                                    logger.debug(f"Interface up: {ifname}")
                    except NetlinkError as e:
                        if e.code == errno.ENODEV:
                            logger.debug(f"Interface no longer exists (ENODEV): {e}")
                        else:
                            logger.error(f"Netlink error handling RTM_NEWLINK: {e}")
                return

            # Handle address and route changes (existing logic)
            if event_type in ["RTM_NEWADDR", "RTM_DELADDR", "RTM_NEWROUTE", "RTM_DELROUTE"]:
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
                        if e.code == errno.ENODEV:
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

        elif cmd_type == "request_wifi_dhcp":
            # Proxy ARP WiFi DHCP: Request DHCP on host's WiFi interface
            # with unique client-id to get IP for container
            container_name = command.get("container_name")
            vnic_name = command.get("vnic_name")
            parent_interface = command.get("parent_interface")
            container_pid = command.get("container_pid")
            client_id = command.get("client_id")

            if not all([container_name, vnic_name, parent_interface, container_pid, client_id]):
                return {"success": False, "error": "Missing required parameters for WiFi DHCP"}

            return self.dhcp_manager.request_wifi_dhcp(
                container_name, vnic_name, parent_interface, container_pid, client_id
            )

        elif cmd_type == "get_dhcp_status":
            return {"success": True, "status": self.dhcp_manager.get_status()}

        elif cmd_type == "get_device_status":
            return {"success": True, "status": self.device_monitor.get_status()}

        elif cmd_type == "discover_devices":
            # Force re-enumeration of serial devices
            devices = self.device_monitor.get_current_devices()
            return {"success": True, "devices": devices}

        elif cmd_type == "get_netlink_status":
            return {"success": True, "status": self.netlink_reader.get_status()}

        elif cmd_type == "get_status":
            # Combined status of all components
            return {
                "success": True,
                "status": {
                    "netlink": self.netlink_reader.get_status(),
                    "dhcp": self.dhcp_manager.get_status(),
                    "devices": self.device_monitor.get_status(),
                    "clients_connected": len(self.clients),
                    "pending_changes": list(self.pending_changes),
                }
            }

        elif cmd_type == "setup_proxy_arp_bridge":
            container_name = command.get("container_name")
            container_pid = command.get("container_pid")
            parent_interface = command.get("parent_interface")
            ip_address = command.get("ip_address")
            gateway = command.get("gateway")
            subnet_mask = command.get("subnet_mask", "255.255.255.0")

            if not all([container_name, container_pid, parent_interface, ip_address, gateway]):
                return {"success": False, "error": "Missing required parameters for Proxy ARP setup"}

            try:
                container_pid = int(container_pid)
                config = setup_proxy_arp_bridge(
                    container_name, container_pid, parent_interface,
                    ip_address, gateway, subnet_mask,
                )
                return {"success": True, "proxy_arp_config": config}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif cmd_type == "cleanup_proxy_arp_bridge":
            container_name = command.get("container_name")
            ip_address = command.get("ip_address")
            parent_interface = command.get("parent_interface")
            veth_host = command.get("veth_host")

            if not container_name:
                return {"success": False, "error": "Missing container_name"}

            try:
                cleanup_proxy_arp_bridge(
                    container_name, ip_address, parent_interface, veth_host,
                )
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif cmd_type == "cleanup_all_proxy_arp":
            return cleanup_all_proxy_arp()

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

        # Start the dedicated netlink reader thread
        self.netlink_reader.start()

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

                # Process netlink events from the queue (non-blocking)
                # The dedicated reader thread has already filtered relevant events
                events_processed = 0
                while events_processed < self.MAX_EVENTS_PER_ITERATION:
                    try:
                        msg = self.netlink_queue.get_nowait()
                        self.handle_netlink_event(msg)
                        events_processed += 1
                    except queue.Empty:
                        break

                self.process_pending_changes()

                # Log if netlink reader is in degraded state (periodic check)
                if self.netlink_reader.is_degraded():
                    # Only log every 30 seconds to avoid spam
                    now = time.time()
                    if now - self._last_degraded_log_time >= 30:
                        logger.warning("Netlink reader is in degraded state")
                        self._last_degraded_log_time = now

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

        # Stop the netlink reader thread first
        self.netlink_reader.stop()

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

        # Close the query IPRoute instance
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
