# Networking Model

## MACVLAN Networks

MACVLAN networks allow runtime containers to appear as physical devices on the LAN with their own MAC and IP addresses.

**Key Features:**
- One MACVLAN network per physical interface and subnet combination
- Network name pattern: `macvlan_<interface>_<subnet>` (e.g., `macvlan_eth0_192.168.1.0_24`)
- Automatic subnet and gateway detection via network monitor cache
- Reuses existing MACVLAN networks to avoid Docker pool overlap errors
- Supports both DHCP and static IP configuration

**Network Creation Logic:**
1. Check if MACVLAN network already exists for the interface/subnet
2. If not, query network monitor cache for subnet and gateway
3. Create MACVLAN network with detected or provided configuration
4. If pool overlap error occurs, search for and reuse existing matching network

**Implementation:** `src/use_cases/docker_manager/create_runtime_container.py` - `get_or_create_macvlan_network()`

## Internal Bridge Networks

Each runtime container gets a dedicated internal bridge network for agent-to-runtime communication.

**Key Features:**
- Network name pattern: `<container_name>_internal`
- Internal-only (no external routing)
- Used for runtime control plane communication (port 8443)
- Independent of MACVLAN configuration changes
- Orchestrator agent connects to all runtime internal networks

**Implementation:** `src/use_cases/docker_manager/create_runtime_container.py` - `create_internal_network()`

## Dynamic Network Adaptation

When the host moves between networks (e.g., DHCP renewal to different subnet), the agent automatically reconnects runtime containers.

**Process:**
1. Network monitor detects interface address/route change via netlink
2. Debounces changes for 3 seconds to avoid rapid reconnections
3. Publishes `network_change` event to agent via Unix socket
4. Agent loads persisted vNIC configurations from `/var/orchestrator/runtime_vnics.json`
5. For each affected runtime container:
   - Disconnects from old MACVLAN network
   - Creates/retrieves new MACVLAN network for new subnet
   - Reconnects container with preserved IP/MAC settings (if static mode)
6. Container maintains connectivity with brief interruption

**Implementation:**
- `src/use_cases/network_monitor/network_event_listener.py` - Event handling and reconnection
- `src/use_cases/docker_manager/vnic_persistence.py` - vNIC configuration persistence

## vNIC Configuration

Runtime containers support multiple virtual network interfaces (vNICs), each with configurable properties:

**Configuration Options:**
- `name` - Virtual NIC identifier
- `parent_interface` - Physical host interface (e.g., "eth0")
- `parent_subnet` - Parent network subnet (optional, auto-detected if omitted)
- `parent_gateway` - Parent network gateway (optional, auto-detected if omitted)
- `network_mode` - "dhcp" or "static"
- `ip` - Static IP address (static mode only)
- `subnet` - Subnet mask (static mode only)
- `gateway` - Gateway address (static mode only)
- `dns` - List of DNS servers (optional)
- `mac_address` - Custom MAC address (optional, auto-generated if omitted)

**Persistence:**
- vNIC configurations are saved to `/var/orchestrator/runtime_vnics.json`
- Used for automatic reconnection after network changes
- Preserved across container restarts

## Network Overlap Handling

When creating MACVLAN networks, Docker may report "pool overlaps with other one on this address space" errors. The agent handles this automatically by:

1. Catching the overlap exception
2. Searching for existing MACVLAN networks with matching subnet and parent interface
3. Reusing the existing network if found
4. Failing with clear error message if no matching network exists

This prevents duplicate MACVLAN networks and ensures consistent network configuration.

## Troubleshooting

For network-related issues, see:
- [Troubleshooting - Docker Network Overlap Errors](troubleshooting.md#docker-network-overlap-errors)
- [Troubleshooting - Agent Not Reconnecting After Network Change](troubleshooting.md#agent-not-reconnecting-after-network-change)
