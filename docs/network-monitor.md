# Network Monitor Sidecar

## Purpose

The network monitor sidecar provides real-time network discovery and change detection for the orchestrator agent.

## Architecture

**Container:** `autonomy_netmon`  
**Image:** `ghcr.io/autonomy-logic/autonomy-netmon:latest`  
**Network Mode:** `--network=host` (required for physical interface access)  
**Restart Policy:** `unless-stopped`

## Communication

**IPC Method:** Unix domain socket  
**Socket Path:** `/var/orchestrator/netmon.sock`  
**Protocol:** JSON lines (one event per line)  
**Permissions:** 0666 (readable/writable by all)

## Event Types

### network_discovery

Sent when a client connects to the socket. Contains current state of all active interfaces.

**Format:**
```json
{
  "type": "network_discovery",
  "data": {
    "interfaces": [
      {
        "interface": "ens37",
        "index": 2,
        "operstate": "UP",
        "ipv4_addresses": [
          {
            "address": "192.168.1.50",
            "prefixlen": 24,
            "subnet": "192.168.1.0/24",
            "network_address": "192.168.1.0"
          }
        ],
        "gateway": "192.168.1.1",
        "timestamp": "2025-11-20T20:30:45.123456"
      }
    ],
    "timestamp": "2025-11-20T20:30:45.123456"
  }
}
```

### network_change

Sent when an interface's IP address or routing configuration changes.

**Format:**
```json
{
  "type": "network_change",
  "data": {
    "interface": "ens37",
    "index": 2,
    "operstate": "UP",
    "ipv4_addresses": [
      {
        "address": "10.0.0.50",
        "prefixlen": 24,
        "subnet": "10.0.0.0/24",
        "network_address": "10.0.0.0"
      }
    ],
    "gateway": "10.0.0.1",
    "timestamp": "2025-11-20T20:35:12.789012"
  }
}
```

## Monitoring Behavior

**Event Source:** Linux netlink (pyroute2)  
**Monitored Events:**
- `RTM_NEWADDR` - New IP address assigned
- `RTM_DELADDR` - IP address removed
- `RTM_NEWROUTE` - New route added
- `RTM_DELROUTE` - Route removed

**Filtering:**
- Ignores loopback interface (`lo`)
- Ignores Docker bridge (`docker0`)
- Ignores virtual Ethernet pairs (`veth*`)
- Only reports interfaces in "UP" operational state
- Only reports interfaces with IPv4 addresses

**Debouncing:**
- Changes are debounced for 3 seconds
- Multiple rapid changes on the same interface are batched
- Prevents excessive reconnection attempts during network instability

## Agent Integration

The orchestrator agent connects to the network monitor socket on startup:

1. **Connection**: Opens Unix socket connection to `/var/orchestrator/netmon.sock`
2. **Discovery**: Receives initial `network_discovery` event with all interfaces
3. **Caching**: Stores interface information in `INTERFACE_CACHE` for subnet detection
4. **Monitoring**: Listens for `network_change` events
5. **Reconnection**: Triggers container reconnection when parent interface changes

**Implementation:**
- `src/use_cases/network_monitor/network_event_listener.py` - Event listener
- `src/use_cases/network_monitor/interface_cache.py` - Interface cache

## Healthcheck

The network monitor includes a Docker healthcheck:

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD test -S /var/orchestrator/netmon.sock || exit 1
```

Verifies that the Unix socket exists and is accessible.

## Implementation Details

**Source Files:**
- `install/autonomy-netmon.py` - Network monitor daemon
- `install/Dockerfile.netmon` - Container image definition

**Key Features:**
- Event-driven monitoring (no polling)
- Automatic interface discovery on startup
- Graceful handling of interface state changes
- Robust error handling and logging

## Troubleshooting

For network monitor issues, see:
- [Troubleshooting - Network Monitor Socket Missing](troubleshooting.md#network-monitor-socket-missing)
- [Troubleshooting - Sidecar Health Issues](troubleshooting.md#sidecar-health-issues)
