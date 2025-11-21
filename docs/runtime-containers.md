# Runtime Containers

## Overview

Runtime containers are OpenPLC v4 instances managed by the orchestrator agent. Each container runs independently with its own network configuration and can be controlled via the cloud.

**Image:** `ghcr.io/autonomy-logic/openplc-runtime:latest`

## Creating Runtime Containers

### Topic: `create_new_runtime`

Creates a new OpenPLC v4 runtime container with MACVLAN networking and internal communication network.

### Message Format

```json
{
  "correlation_id": 12345,
  "container_name": "plc-001",
  "vnic_configs": [
    {
      "name": "eth0",
      "parent_interface": "ens37",
      "network_mode": "dhcp"
    }
  ]
}
```

### vNIC Configuration Schema

**Required Fields:**
- `name` (string) - Virtual NIC identifier
- `parent_interface` (string) - Physical host interface
- `network_mode` (string) - "dhcp" or "manual"

**Optional Fields:**
- `parent_subnet` (string) - Parent network subnet (auto-detected if omitted)
- `parent_gateway` (string) - Parent network gateway (auto-detected if omitted)
- `ip_address` (string) - Static IP address (manual mode only)
- `subnet` (string) - Subnet mask (manual mode only)
- `gateway` (string) - Gateway address (manual mode only)
- `dns` (array of strings) - DNS servers
- `mac_address` (string) - Custom MAC address

### Example: DHCP Configuration

```json
{
  "correlation_id": 12345,
  "container_name": "plc-dhcp",
  "vnic_configs": [
    {
      "name": "eth0",
      "parent_interface": "ens37",
      "network_mode": "dhcp",
      "dns": ["8.8.8.8", "8.8.4.4"]
    }
  ]
}
```

### Example: Manual IP Configuration

```json
{
  "correlation_id": 12346,
  "container_name": "plc-static",
  "vnic_configs": [
    {
      "name": "eth0",
      "parent_interface": "ens37",
      "parent_subnet": "192.168.1.0/24",
      "parent_gateway": "192.168.1.1",
      "network_mode": "manual",
      "ip_address": "192.168.1.100",
      "subnet": "192.168.1.0/24",
      "gateway": "192.168.1.1",
      "dns": ["192.168.1.1"],
      "mac_address": "02:42:ac:11:00:02"
    }
  ]
}
```

### Example: Multiple vNICs

```json
{
  "correlation_id": 12347,
  "container_name": "plc-multi",
  "vnic_configs": [
    {
      "name": "eth0",
      "parent_interface": "ens37",
      "network_mode": "dhcp"
    },
    {
      "name": "eth1",
      "parent_interface": "ens38",
      "network_mode": "manual",
      "ip_address": "10.0.0.100",
      "subnet": "10.0.0.0/24",
      "gateway": "10.0.0.1"
    }
  ]
}
```

## Container Creation Process

1. **Validation**: Validates message against contract schema
2. **Image Pull**: Pulls `ghcr.io/autonomy-logic/openplc-runtime:latest` (uses local if pull fails)
3. **Internal Network**: Creates internal bridge network `<container_name>_internal`
4. **MACVLAN Networks**: Creates or retrieves MACVLAN network for each vNIC
5. **Container Creation**: Creates container with restart policy "always"
6. **Network Attachment**: Connects container to internal network first, then MACVLAN networks
7. **Agent Connection**: Connects orchestrator agent to internal network
8. **IP Registration**: Registers container's internal IP in client registry
9. **vNIC Persistence**: Saves vNIC configurations to `/var/orchestrator/runtime_vnics.json`

## Response

The agent returns an immediate response before starting the container creation:

```json
{
  "action": "create_new_runtime",
  "correlation_id": 12345,
  "status": "creating",
  "container_id": "plc-001",
  "message": "Container creation started for plc-001"
}
```

Container creation happens asynchronously in the background to avoid blocking the WebSocket connection.

**Implementation:** `src/controllers/websocket_controller/topics/receivers/create_new_runtime.py`

## Container Lifecycle

### Starting Containers

Runtime containers are created with restart policy "always", so they automatically start on boot and restart if they crash.

**Note:** The `start_device` topic is currently a placeholder and returns a dummy response.

### Stopping Containers

**Note:** The `stop_device` topic is currently a placeholder and returns a dummy response.

### Restarting Containers

**Note:** The `restart_device` topic is currently a placeholder and returns a dummy response.

### Deleting Containers

Use the `delete_device` topic to remove a runtime container and its associated networks.

**Message Format:**
```json
{
  "correlation_id": 12348,
  "device_id": "plc-001"
}
```

## Runtime Control

Runtime containers expose port 8443 for the OpenPLC web interface and API. The agent communicates with runtimes via the internal bridge network.

### Executing Commands

Use the `run_command` topic to execute commands on a runtime container.

**Message Format:**
```json
{
  "correlation_id": 12349,
  "device_id": "plc-001",
  "command": "start",
  "parameters": {}
}
```

The agent proxies the command to the runtime container's HTTP API.

## Troubleshooting

For runtime container issues, see [Troubleshooting - Container Creation Failures](troubleshooting.md#container-creation-failures).
