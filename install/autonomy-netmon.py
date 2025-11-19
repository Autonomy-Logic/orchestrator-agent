#!/usr/bin/env python3
"""
Autonomy Network Monitor Daemon

Monitors host network interfaces for changes and reports them to the orchestrator-agent
via Unix domain socket. Provides network discovery and real-time change notifications.
"""

import json
import socket
import time
import sys
import os
import signal
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import ipaddress

try:
    from pyroute2 import IPRoute, NetlinkError
    from pyroute2.netlink import NLMSG_ERROR
except ImportError:
    print("ERROR: pyroute2 is not installed. Install it with: pip3 install pyroute2")
    sys.exit(1)

SOCKET_PATH = "/var/orchestrator/netmon.sock"
LOG_FILE = "/var/log/autonomy-netmon.log"
DEBOUNCE_SECONDS = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


class NetworkMonitor:
    def __init__(self):
        self.ipr = IPRoute()
        self.socket_path = SOCKET_PATH
        self.server_socket = None
        self.clients = []
        self.running = True
        self.last_event_time = 0
        self.pending_changes = set()

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
            except:
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

    def accept_clients(self):
        """Accept new client connections"""
        try:
            client, addr = self.server_socket.accept()
            self.clients.append(client)
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
                    f"Sent discovery data with {len(interfaces)} interfaces to new client"
                )
            except Exception as e:
                logger.error(f"Failed to send discovery data: {e}")

        except socket.timeout:
            pass
        except Exception as e:
            logger.error(f"Error accepting client: {e}")

    def run(self):
        """Main event loop"""
        logger.info("Starting Autonomy Network Monitor")

        self.setup_socket()

        self.ipr.bind()

        logger.info("Monitoring network changes...")

        while self.running:
            try:
                self.accept_clients()

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

        for client in self.clients:
            try:
                client.close()
            except:
                pass

        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except:
                pass

        try:
            self.ipr.close()
        except:
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
