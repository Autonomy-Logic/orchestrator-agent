# WiFi Support via Proxy ARP Bridge - Implementation Plan

This document describes the implementation strategy for enabling vPLC container networking on WiFi interfaces using a Proxy ARP Bridge approach.

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Technical Background](#technical-background)
3. [Solution Architecture](#solution-architecture)
4. [Implementation Tasks](#implementation-tasks)
5. [Cleanup and Deletion](#cleanup-and-deletion)
6. [Testing Strategy](#testing-strategy)
7. [Rollback Plan](#rollback-plan)

---

## Problem Statement

### Current Situation

The orchestrator-agent uses MACVLAN Docker networks to give each vPLC container its own MAC address and IP address, making them appear as separate physical devices on the network. This works well on **Ethernet** interfaces but **fails on WiFi** interfaces.

### Why MACVLAN Fails on WiFi

```
┌─────────────────────────────────────────────────────────────────┐
│                    MACVLAN on WiFi - The Problem                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Host                         WiFi Access Point               │
│   ┌──────────────┐             ┌──────────────┐                │
│   │   wlan0      │             │              │                │
│   │   MAC: AA:BB │◄───────────►│  Authenticated│               │
│   │   (auth'd)   │   802.11    │  MAC: AA:BB  │                │
│   └──────┬───────┘             └──────────────┘                │
│          │                                                      │
│   ┌──────┴───────┐                                             │
│   │   MACVLAN    │                                             │
│   │   Network    │                                             │
│   └──────┬───────┘                                             │
│          │                                                      │
│   ┌──────┴───────┐             ┌──────────────┐                │
│   │  Container   │             │              │                │
│   │  MAC: 02:XX  │─────────X───│  NOT auth'd! │                │
│   │  (different) │   BLOCKED   │  MAC: 02:XX  │                │
│   └──────────────┘             └──────────────┘                │
│                                                                 │
│   Result: Container traffic is dropped by the access point     │
│   because its MAC address never completed 802.11 auth/assoc    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Root Cause:** WiFi access points perform MAC-based authentication. Only devices that have completed the 802.11 authentication and association handshake can send/receive traffic. MACVLAN creates containers with **new MAC addresses** that the AP has never seen, so their traffic is dropped.

**Why Ethernet Works:** Ethernet switches are promiscuous by design - they forward frames based on MAC learning without authenticating devices. Any MAC address on a port is accepted.

### Why IPvlan Doesn't Work Universally

IPvlan would be an ideal solution as it shares the parent's MAC address, but:

1. **Kernel support required:** IPvlan requires `CONFIG_IPVLAN=y` in the kernel
2. **Not available on embedded devices:** Many ARM devices (Arduino Portenta X8, Raspberry Pi with custom kernels) don't have IPvlan compiled in
3. **Cannot be added as a module:** IPvlan must be compiled into the kernel, not loaded as a module

### Requirements

1. vPLCs must be reachable by other devices on the network (Modbus, OPC-UA, SCADA protocols)
2. vPLCs must be able to communicate with other devices on the network
3. Each vPLC should have its own IP address on the WiFi subnet
4. DHCP should work for automatic IP assignment
5. Solution must work without special kernel modules (universal compatibility)
6. Existing Ethernet functionality must not be affected

---

## Technical Background

### How VirtualBox Solves This Problem

VirtualBox successfully bridges VMs to WiFi networks using a technique called **Proxy ARP**. According to VirtualBox documentation and source code analysis:

1. **MAC Address Rewriting:** All outgoing frames use the host's WiFi MAC address
2. **Proxy ARP:** The host responds to ARP requests for VM IPs, making VMs appear to have the host's MAC
3. **IP-based Routing:** Incoming packets are routed to the correct VM based on destination IP, not MAC

This approach works without special kernel modules because it uses standard Linux networking features:
- Proxy ARP (`/proc/sys/net/ipv4/conf/*/proxy_arp`)
- IP forwarding (`/proc/sys/net/ipv4/ip_forward`)
- Standard routing tables

### Proxy ARP Bridge Concept

```
┌─────────────────────────────────────────────────────────────────┐
│                  Proxy ARP Bridge - Solution                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   External Device (192.168.1.100)                               │
│   ┌──────────────┐                                             │
│   │ "Who has     │                                             │
│   │ 192.168.1.50?"                                             │
│   └──────┬───────┘                                             │
│          │ ARP Request                                         │
│          ▼                                                      │
│   WiFi Access Point                                            │
│          │                                                      │
│          ▼                                                      │
│   Host (192.168.1.10)                                          │
│   ┌──────────────────────────────────────────┐                 │
│   │   wlan0 (MAC: AA:BB:CC:DD:EE:FF)         │                 │
│   │   proxy_arp = 1                           │                 │
│   │                                           │                 │
│   │   Responds: "192.168.1.50 is at AA:BB..."│                 │
│   │   (Host's own MAC!)                       │                 │
│   └──────────────────┬───────────────────────┘                 │
│                      │                                          │
│                      │ Route: 192.168.1.50 → veth-container    │
│                      ▼                                          │
│   ┌──────────────────────────────────────────┐                 │
│   │   Container vPLC                          │                 │
│   │   IP: 192.168.1.50                        │                 │
│   │   (Real IP on WiFi subnet!)               │                 │
│   └──────────────────────────────────────────┘                 │
│                                                                 │
│   Result: External devices can reach container at 192.168.1.50 │
│   Traffic flows through host's authenticated WiFi connection   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### DHCP with Proxy ARP

Since the container's traffic uses the host's MAC address, we need DHCP client-id (Option 61) to get unique IPs:

```
┌─────────────────────────────────────────────────────────────────┐
│                    DHCP with Client-ID                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Container A                    Container B                    │
│   ┌──────────────┐              ┌──────────────┐               │
│   │ Uses host's  │              │ Uses host's  │               │
│   │ MAC via proxy│              │ MAC via proxy│               │
│   └──────┬───────┘              └──────┬───────┘               │
│          │                             │                        │
│          │ DHCP DISCOVER               │ DHCP DISCOVER          │
│          │ Client-ID: "vplc-a:veth0"   │ Client-ID: "vplc-b:veth0"
│          │ (via host's wlan0)          │ (via host's wlan0)     │
│          └─────────────┬───────────────┘                       │
│                        │                                        │
│                        ▼                                        │
│              ┌─────────────────┐                               │
│              │   DHCP Server   │                               │
│              │                 │                               │
│              │ Identifies by   │                               │
│              │ Client-ID, not  │                               │
│              │ MAC address     │                               │
│              └────────┬────────┘                               │
│                       │                                         │
│         ┌─────────────┴─────────────┐                          │
│         │                           │                           │
│         ▼                           ▼                           │
│   Container A: 192.168.1.50   Container B: 192.168.1.51        │
│                                                                 │
│   Both containers get unique IPs on the WiFi subnet!           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Solution Architecture

### Hybrid Approach

We implement a **hybrid strategy** that automatically selects the appropriate network method based on interface type:

- **Ethernet interfaces** → MACVLAN (existing behavior, unchanged)
- **WiFi interfaces** → Proxy ARP Bridge with client-id DHCP

### Network Architecture for WiFi

```
┌─────────────────────────────────────────────────────────────────┐
│                    WiFi Container Network Setup                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │                         HOST                             │  │
│   │                                                          │  │
│   │   wlan0 ─────────────────────────────────────────────┐  │  │
│   │   192.168.1.10                                       │  │  │
│   │   proxy_arp=1                                        │  │  │
│   │   ip_forward=1                                       │  │  │
│   │                                                      │  │  │
│   │   Routing Table:                                     │  │  │
│   │   192.168.1.50/32 via veth-host-A                   │  │  │
│   │   192.168.1.51/32 via veth-host-B                   │  │  │
│   │                                                      │  │  │
│   │   ┌─────────────┐        ┌─────────────┐            │  │  │
│   │   │ veth-host-A │        │ veth-host-B │            │  │  │
│   │   └──────┬──────┘        └──────┬──────┘            │  │  │
│   └──────────┼──────────────────────┼───────────────────┘  │  │
│              │                      │                       │  │
│   ┌──────────┼──────────────────────┼───────────────────┐  │  │
│   │          │   Container netns    │                    │  │  │
│   │   ┌──────┴──────┐        ┌──────┴──────┐            │  │  │
│   │   │  veth-ct-A  │        │  veth-ct-B  │            │  │  │
│   │   │192.168.1.50 │        │192.168.1.51 │            │  │  │
│   │   └─────────────┘        └─────────────┘            │  │  │
│   │                                                      │  │  │
│   │   Container A               Container B              │  │  │
│   │   (vPLC 1)                  (vPLC 2)                 │  │  │
│   └──────────────────────────────────────────────────────┘  │  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                       Container Creation Flow                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Cloud Command: create_new_runtime                              │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────┐                   │
│  │ 1. Load vNIC config                     │                   │
│  │    - parent_interface: "wlan0"          │                   │
│  └─────────────────┬───────────────────────┘                   │
│                    │                                            │
│                    ▼                                            │
│  ┌─────────────────────────────────────────┐                   │
│  │ 2. Get interface type from cache        │                   │
│  │    - Check INTERFACE_CACHE["wlan0"]     │                   │
│  │    - type: "wifi"                       │                   │
│  └─────────────────┬───────────────────────┘                   │
│                    │                                            │
│                    ▼                                            │
│  ┌─────────────────────────────────────────┐                   │
│  │ 3. Select network method                │                   │
│  │    - WiFi? → Proxy ARP Bridge           │                   │
│  │    - Ethernet? → MACVLAN (unchanged)    │                   │
│  └─────────────────┬───────────────────────┘                   │
│                    │                                            │
│                    ▼                                            │
│  ┌─────────────────────────────────────────┐                   │
│  │ 4. Create container with internal net   │                   │
│  │    - Container on internal bridge only  │                   │
│  │    - No external network yet            │                   │
│  └─────────────────┬───────────────────────┘                   │
│                    │                                            │
│                    ▼                                            │
│  ┌─────────────────────────────────────────┐                   │
│  │ 5. Create veth pair for WiFi            │                   │
│  │    - veth-host end on host              │                   │
│  │    - veth-ct end in container netns     │                   │
│  └─────────────────┬───────────────────────┘                   │
│                    │                                            │
│                    ▼                                            │
│  ┌─────────────────────────────────────────┐                   │
│  │ 6. Request DHCP via netmon              │                   │
│  │    - netmon runs udhcpc in container ns │                   │
│  │    - Uses client-id for identification  │                   │
│  │    - Packets go via host's wlan0        │                   │
│  └─────────────────┬───────────────────────┘                   │
│                    │                                            │
│                    ▼                                            │
│  ┌─────────────────────────────────────────┐                   │
│  │ 7. Configure Proxy ARP on host          │                   │
│  │    - Enable proxy_arp on wlan0          │                   │
│  │    - Add route to container IP          │                   │
│  │    - Add proxy ARP neighbor entry       │                   │
│  └─────────────────────────────────────────┘                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Tasks

### Task 1: Add WiFi Interface Type Detection to netmon

**File:** `install/autonomy-netmon.py`

**Changes:**

1. Add `get_interface_type()` function (already implemented):

```python
def get_interface_type(ifname: str) -> str:
    """
    Detect if a network interface is WiFi or Ethernet.

    Detection methods (in order):
    1. Check /sys/class/net/{ifname}/wireless directory
    2. Check /sys/class/net/{ifname}/phy80211 symlink
    3. Check interface name patterns (wlan*, wlp*, wlx*)

    Returns:
        "wifi" or "ethernet"
    """
    wireless_path = f"/sys/class/net/{ifname}/wireless"
    if os.path.exists(wireless_path):
        return "wifi"

    phy_path = f"/sys/class/net/{ifname}/phy80211"
    if os.path.exists(phy_path):
        return "wifi"

    if ifname.startswith(("wlan", "wlp", "wlx")):
        return "wifi"

    return "ethernet"
```

2. Include type in `get_interface_info()` response (already implemented).

---

### Task 2: Update Interface Cache

**File:** `src/tools/interface_cache.py`

**Changes:** Add `get_interface_type()` accessor (already implemented).

---

### Task 3: Create Proxy ARP Bridge Network Support

**File:** `src/tools/docker_tools.py`

**Changes:**

1. Remove IPvlan functions (`get_or_create_ipvlan_network`, `get_ipvlan_network_key`)

2. Add Proxy ARP Bridge setup functions:

```python
def setup_proxy_arp_bridge(
    container_name: str,
    container_pid: int,
    parent_interface: str,
    ip_address: str,
    gateway: str,
) -> dict:
    """
    Set up Proxy ARP bridge for a container on a WiFi interface.

    This creates a veth pair, configures routing, and enables proxy ARP
    so the container can be reached on the WiFi network.

    Args:
        container_name: Name of the container
        container_pid: PID of container's init process
        parent_interface: WiFi interface (e.g., "wlan0")
        ip_address: IP address for container (from DHCP or static)
        gateway: Gateway address

    Returns:
        dict with veth names and configuration details
    """
    import subprocess

    # Generate veth names
    # Use short hash of container name to keep under 15 char limit
    short_id = container_name[:8]
    veth_host = f"veth-{short_id}"
    veth_container = "eth1"  # Name inside container

    # 1. Create veth pair
    subprocess.run([
        "ip", "link", "add", veth_host, "type", "veth",
        "peer", "name", veth_container
    ], check=True)

    # 2. Move one end to container's network namespace
    subprocess.run([
        "ip", "link", "set", veth_container,
        "netns", str(container_pid)
    ], check=True)

    # 3. Configure container's interface
    subprocess.run([
        "nsenter", "-t", str(container_pid), "-n",
        "ip", "addr", "add", f"{ip_address}/32", "dev", veth_container
    ], check=True)

    subprocess.run([
        "nsenter", "-t", str(container_pid), "-n",
        "ip", "link", "set", veth_container, "up"
    ], check=True)

    # Add default route via the veth (peer address doesn't matter for /32)
    subprocess.run([
        "nsenter", "-t", str(container_pid), "-n",
        "ip", "route", "add", "default", "dev", veth_container
    ], check=True)

    # 4. Configure host's end
    subprocess.run(["ip", "link", "set", veth_host, "up"], check=True)

    # 5. Enable proxy ARP on WiFi interface
    with open(f"/proc/sys/net/ipv4/conf/{parent_interface}/proxy_arp", "w") as f:
        f.write("1")

    # 6. Enable IP forwarding
    with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
        f.write("1")

    # 7. Add route to container
    subprocess.run([
        "ip", "route", "add", f"{ip_address}/32", "dev", veth_host
    ], check=True)

    # 8. Add proxy ARP entry (host will respond to ARP for container's IP)
    subprocess.run([
        "ip", "neighbor", "add", "proxy", ip_address, "dev", parent_interface
    ], check=True)

    return {
        "veth_host": veth_host,
        "veth_container": veth_container,
        "ip_address": ip_address,
        "parent_interface": parent_interface,
    }


def cleanup_proxy_arp_bridge(
    container_name: str,
    ip_address: str,
    parent_interface: str,
    veth_host: str,
) -> None:
    """
    Clean up Proxy ARP bridge configuration for a container.

    Args:
        container_name: Name of the container
        ip_address: Container's IP address
        parent_interface: WiFi interface
        veth_host: Host-side veth interface name
    """
    import subprocess

    # Remove proxy ARP entry
    try:
        subprocess.run([
            "ip", "neighbor", "del", "proxy", ip_address, "dev", parent_interface
        ], check=False)
    except Exception:
        pass

    # Remove route
    try:
        subprocess.run([
            "ip", "route", "del", f"{ip_address}/32", "dev", veth_host
        ], check=False)
    except Exception:
        pass

    # Remove veth pair (removes both ends)
    try:
        subprocess.run(["ip", "link", "del", veth_host], check=False)
    except Exception:
        pass
```

---

### Task 4: Update Container Creation for WiFi

**File:** `src/use_cases/docker_manager/create_runtime_container.py`

**Changes:**

1. For WiFi interfaces, don't create MACVLAN/IPvlan network
2. Create container with only internal network
3. After container starts, set up Proxy ARP bridge
4. Request DHCP with client-id

```python
# In the vNIC processing loop:
for vnic_config in vnic_configs:
    parent_interface = vnic_config.get("parent_interface")
    interface_type = get_interface_type(parent_interface)

    if interface_type == "wifi":
        # WiFi: Use Proxy ARP Bridge (no Docker network needed)
        log_info(f"Using Proxy ARP Bridge for WiFi interface {parent_interface}")
        vnic_config["_network_method"] = "proxy_arp"
        # Container will only be on internal network initially
        # Proxy ARP setup happens after container starts
    else:
        # Ethernet: Use MACVLAN (existing behavior)
        network = get_or_create_macvlan_network(
            parent_interface, parent_subnet, parent_gateway
        )
        networks.append((network, vnic_config))
        vnic_config["_network_method"] = "macvlan"

# After container starts, for WiFi vNICs:
for vnic_config in vnic_configs:
    if vnic_config.get("_network_method") == "proxy_arp":
        network_mode = vnic_config.get("network_mode", "dhcp")

        if network_mode == "dhcp":
            # Request DHCP first to get IP
            result = await network_event_listener.start_dhcp_proxy_arp(
                container_name,
                vnic_config["name"],
                container_pid,
                vnic_config["parent_interface"],
            )
            if result.get("success"):
                ip_address = result.get("ip_address")
                gateway = result.get("gateway")
        else:
            # Static IP
            ip_address = vnic_config.get("ip")
            gateway = vnic_config.get("gateway")

        # Set up Proxy ARP bridge with the IP
        bridge_config = setup_proxy_arp_bridge(
            container_name,
            container_pid,
            vnic_config["parent_interface"],
            ip_address,
            gateway,
        )

        # Store config for cleanup
        vnic_config["_proxy_arp_config"] = bridge_config
```

---

### Task 5: Update netmon DHCP for Proxy ARP

**File:** `install/autonomy-netmon.py`

**Changes:**

1. Add function to run DHCP and capture IP for Proxy ARP setup:

```python
def start_dhcp_proxy_arp(
    self,
    container_name: str,
    vnic_name: str,
    container_pid: int,
    parent_interface: str,
) -> Dict[str, Any]:
    """
    Start DHCP for Proxy ARP bridge setup.

    This runs udhcpc to get an IP, then returns the IP for Proxy ARP setup.
    The DHCP packets go out via the host's WiFi interface.

    Args:
        container_name: Container name
        vnic_name: vNIC name
        container_pid: Container PID
        parent_interface: WiFi interface to use

    Returns:
        Dict with ip_address, gateway, etc.
    """
    key = f"{container_name}:{vnic_name}"

    # Generate unique client-id
    client_id_str = f"{container_name}:{vnic_name}"
    client_id_hex = client_id_str.encode('utf-8').hex()

    # Create a temporary veth for DHCP
    # This will be replaced by the actual Proxy ARP veth after we get the IP
    temp_veth = f"dhcp-{container_name[:6]}"

    # Run udhcpc on the parent interface with client-id
    # The -O option requests specific options
    cmd = [
        "udhcpc", "-f", "-i", parent_interface,
        "-s", "/usr/share/udhcpc/default.script",
        "-t", "5", "-T", "3", "-n",  # -n = exit if no lease
        "-x", f"0x3d:{client_id_hex}",  # Client-ID
        "-O", "router",  # Request gateway
    ]

    # Run and capture lease info
    # ... implementation details ...

    return {
        "success": True,
        "ip_address": assigned_ip,
        "gateway": gateway,
        "subnet_mask": mask,
    }
```

---

### Task 6: Update network_event_listener

**File:** `src/tools/network_event_listener.py`

**Changes:**

1. Add `start_dhcp_proxy_arp()` method to communicate with netmon
2. Update reconnection logic to handle Proxy ARP bridges
3. Remove IPvlan-specific code

---

### Task 7: Update selfdestruct.py

**File:** `src/use_cases/docker_manager/selfdestruct.py`

**Changes:**

1. Remove IPvlan network pattern
2. Add cleanup for Proxy ARP configurations:

```python
def _cleanup_proxy_arp_configs():
    """
    Clean up Proxy ARP configurations during self-destruct.

    This removes:
    - Proxy ARP neighbor entries
    - Routes to container IPs
    - Veth interfaces
    """
    # Load vNIC configs to find Proxy ARP setups
    all_vnic_configs = load_vnic_configs()

    for container_name, vnic_configs in all_vnic_configs.items():
        for vnic_config in vnic_configs:
            proxy_arp_config = vnic_config.get("_proxy_arp_config")
            if proxy_arp_config:
                cleanup_proxy_arp_bridge(
                    container_name,
                    proxy_arp_config.get("ip_address"),
                    proxy_arp_config.get("parent_interface"),
                    proxy_arp_config.get("veth_host"),
                )
```

---

### Task 8: Update install.sh

**File:** `install/install.sh`

**Changes:**

Add system configuration for Proxy ARP support:

```bash
# Enable IP forwarding (persistent)
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p

# Note: proxy_arp is enabled per-interface at runtime
```

---

## Cleanup and Deletion

### Runtime Container Deletion

When a container with Proxy ARP bridge is deleted:

1. **Stop DHCP client** - netmon handles this
2. **Remove proxy ARP neighbor entry** - `ip neighbor del proxy {ip} dev {wlan0}`
3. **Remove route** - `ip route del {ip}/32 dev {veth}`
4. **Remove veth pair** - `ip link del {veth}` (removes both ends)
5. **Container removal** - Standard Docker removal

### Orchestrator Self-Destruct

The `_cleanup_proxy_arp_configs()` function handles:
1. Iterating through all vNIC configs
2. Finding Proxy ARP configurations
3. Cleaning up routes, neighbors, and veth interfaces

### DHCP Cleanup

DHCP cleanup is automatic - when the DHCP client is stopped, the lease expires naturally.

---

## Testing Strategy

### Unit Testing

1. **Interface type detection:**
   - Test with various interface names (eth0, wlan0, enp0s3, wlp2s0)

2. **Proxy ARP setup:**
   - Test veth creation
   - Test routing configuration
   - Test proxy ARP neighbor entries

### Integration Testing

1. **Ethernet path (regression):**
   - Create vPLC on Ethernet interface
   - Verify MACVLAN network created
   - Verify DHCP works with MAC-based identification

2. **WiFi path (new):**
   - Create vPLC on WiFi interface
   - Verify Proxy ARP bridge created
   - Verify DHCP works with client-id
   - Verify container reachable from other devices

3. **Mixed scenario:**
   - Create vPLCs on both Ethernet and WiFi
   - Verify correct network method selection

4. **Deletion:**
   - Delete vPLC
   - Verify Proxy ARP cleanup (routes, neighbors, veth)

### Manual Testing Checklist

- [ ] Create vPLC on Ethernet - verify MACVLAN used
- [ ] Create vPLC on WiFi - verify Proxy ARP Bridge used
- [ ] Ping container from another device on WiFi network
- [ ] Container can ping other devices on WiFi network
- [ ] Test Modbus TCP connection to WiFi vPLC
- [ ] Delete vPLC - verify cleanup (no orphan routes/veths)
- [ ] Self-destruct - verify all Proxy ARP configs removed

---

## Rollback Plan

If issues are discovered after deployment:

1. **Revert to Ethernet-only:**
   - Setting `get_interface_type()` to always return "ethernet" disables WiFi support
   - Users would need Ethernet connection

2. **Cleanup:**
   - Proxy ARP configs are cleaned up on container deletion
   - Self-destruct handles full cleanup

3. **No data migration needed:**
   - vNIC configs are backward compatible
   - Missing `_network_method` field defaults to "macvlan"

---

## File Summary

| File | Changes |
|------|---------|
| `install/autonomy-netmon.py` | Add `get_interface_type()` (done), add `start_dhcp_proxy_arp()` |
| `src/tools/interface_cache.py` | Add `get_interface_type()` accessor (done) |
| `src/tools/docker_tools.py` | Remove IPvlan functions, add `setup_proxy_arp_bridge()`, `cleanup_proxy_arp_bridge()` |
| `src/tools/network_event_listener.py` | Add Proxy ARP DHCP support, remove IPvlan code |
| `src/use_cases/docker_manager/create_runtime_container.py` | Use Proxy ARP for WiFi, remove IPvlan code |
| `src/use_cases/docker_manager/selfdestruct.py` | Remove IPvlan pattern, add `_cleanup_proxy_arp_configs()` |
| `install/install.sh` | Enable IP forwarding |

---

## References

- [VirtualBox Bridged Networking Documentation](https://docs.oracle.com/en/virtualization/virtualbox/6.0/user/network_bridged.html)
- [VirtualBox Source Code - VBoxNetFlt](https://github.com/VirtualBox/virtualbox)
- [Linux Proxy ARP](https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt)
- [RFC 2132 - DHCP Options](https://www.rfc-editor.org/rfc/rfc2132) (Option 61: Client Identifier)
- [BusyBox udhcpc](https://udhcp.busybox.net/README.udhcpc)
