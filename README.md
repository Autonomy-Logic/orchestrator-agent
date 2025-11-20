# Orchestrator Agent

The Orchestrator Agent is a Python daemon that runs on edge devices as a Docker container. It maintains a continuous, mutually authenticated WebSocket connection to the Autonomy Edge Cloud and remotely orchestrates OpenPLC v4 runtime containers (vPLCs) on the host machine.

Communication uses mutual TLS (mTLS) authentication where both client and server verify each other's identity, preventing device impersonation and man-in-the-middle attacks. A companion network monitor sidecar container observes host networking events and enables automatic MACVLAN network reconfiguration when the host's physical network changes.

## Quick Start

**Installation:**
```bash
curl https://getedge.me | bash
```

**Images:**
- Agent: `ghcr.io/autonomy-logic/orchestrator-agent:latest`
- Network Monitor: `ghcr.io/autonomy-logic/autonomy-netmon:latest`
- Runtime: `ghcr.io/autonomy-logic/openplc-runtime:latest`

## Table of Contents

- [Key Capabilities](#key-capabilities)
- [Architecture](#architecture)
- [Security and Identity](#security-and-identity)
- [Installation](#installation)
- [Networking Model](#networking-model)
- [Cloud Protocol](#cloud-protocol)
- [Creating Runtime Containers](#creating-runtime-containers)
- [Network Monitor Sidecar](#network-monitor-sidecar)
- [Logging and Metrics](#logging-and-metrics)
- [Directory Structure](#directory-structure)
- [Local Development](#local-development)
- [CI/CD](#cicd)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

## Key Capabilities

- **Secure Cloud Control**: Maintains persistent WebSocket connection to Autonomy Edge Cloud using mTLS and Socket.IO
- **Container Orchestration**: Creates, configures, and manages OpenPLC v4 runtime containers (vPLCs) on the host
- **Automatic Network Discovery**: Detects physical network interfaces and their configurations via sidecar container
- **Dynamic Network Adaptation**: Automatically reconnects runtime containers when the host moves between networks
- **MACVLAN Networking**: Runtime containers appear as native devices on the physical LAN with their own IP/MAC addresses
- **Internal Communication**: Dedicated bridge network for agent-to-runtime communication independent of MACVLAN
- **System Monitoring**: Periodic heartbeats with CPU, memory, disk, and uptime metrics
- **Contract Validation**: Type-safe message validation for all cloud commands

## Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│ Host Machine                                                         │
│                                                                      │
│  ┌──────────────────────┐         ┌──────────────────────────────┐ │
│  │  autonomy-netmon     │         │  orchestrator-agent          │ │
│  │  (--network=host)    │◄────────┤  (normal network)            │ │
│  │                      │  socket │                              │ │
│  │  Monitors physical   │         │  Manages Docker resources    │ │
│  │  network interfaces  │         │  Handles cloud commands      │ │
│  └──────────────────────┘         └──────────────────────────────┘ │
│           │                                     │                   │
│           │ netlink events                      │ Docker API        │
│           ▼                                     ▼                   │
│  ┌──────────────────────┐         ┌──────────────────────────────┐ │
│  │  Physical NICs       │         │  Runtime Containers          │ │
│  │  (eth0, ens37, ...)  │         │  (OpenPLC v4 vPLCs)          │ │
│  │                      │         │  - MACVLAN networks          │ │
│  │                      │         │  - Internal bridge networks  │ │
│  └──────────────────────┘         └──────────────────────────────┘ │
│                                                                      │
│  Shared Volume: /var/orchestrator (orchestrator-shared)             │
│  - netmon.sock (Unix domain socket for IPC)                         │
│  - runtime_vnics.json (vNIC persistence)                            │
│  - logs/ (operational logs)                                         │
│  - debug/ (debug logs)                                              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ mTLS WebSocket
                                    ▼
                        ┌────────────────────────┐
                        │  Autonomy Edge Cloud   │
                        │  (api.getedge.me)      │
                        └────────────────────────┘
```

### Components

#### orchestrator-agent Container

The main agent container that orchestrates runtime containers and communicates with the cloud.

**Responsibilities:**
- Maintains mTLS-authenticated Socket.IO session to `api.getedge.me`
- Handles cloud command topics (see [Cloud Protocol](#cloud-protocol))
- Emits periodic heartbeat messages with system metrics
- Manages Docker resources: containers, MACVLAN networks, internal bridge networks
- Listens for network change events from the sidecar and reconnects runtime containers

**Key Source Files:**
- `src/index.py` - Entry point with reconnection loop
- `src/controllers/websocket_controller/` - WebSocket client and topic handlers
- `src/use_cases/docker_manager/` - Container and network management
- `src/use_cases/network_monitor/` - Network event listener and interface cache

#### autonomy-netmon Sidecar

A lightweight Python container that monitors the host's physical network interfaces.

**Responsibilities:**
- Runs with `--network=host` to access physical network interfaces
- Monitors netlink events using pyroute2 (no polling, event-driven)
- Discovers active interfaces with IPv4 addresses, subnets, and gateways
- Publishes network discovery and change events via Unix domain socket
- Debounces rapid network changes (3-second window)

**Key Files:**
- `install/autonomy-netmon.py` - Network monitor daemon
- `install/Dockerfile.netmon` - Container image definition

**Communication:**
- Unix domain socket at `/var/orchestrator/netmon.sock` in the shared volume
- JSON-formatted events: `network_discovery` and `network_change`

#### Runtime Containers (OpenPLC v4)

OpenPLC runtime instances managed by the orchestrator agent.

**Image:** `ghcr.io/autonomy-logic/openplc-runtime:latest`

**Network Configuration:**
- Connected to one or more MACVLAN networks derived from physical interfaces
- Each MACVLAN network matches the parent interface's actual subnet and gateway
- Also attached to a per-runtime internal bridge network (pattern: `<container_name>_internal`)
- Supports DHCP or manual IP configuration
- Optional custom MAC addresses and DNS servers

**Control Plane:**
- Runtime containers expose port 8443 for OpenPLC web interface and API
- Agent communicates with runtimes via internal bridge network

## Security and Identity

### Mutual TLS Authentication

The agent uses mutual TLS (mTLS) to authenticate both the client and server:

- **Client Authentication**: Agent loads `~/.mtls/client.crt` and `~/.mtls/client.key`
- **Server Authentication**: Verifies server certificate with `CERT_REQUIRED` and hostname checking
- **TLS Version**: Minimum TLSv1.2
- **Certificate Type**: RSA-4096 self-signed certificates

**Implementation:** `src/tools/ssl.py`

### Agent Identity

The agent's unique identifier is extracted from the client certificate's Common Name (CN) field:

```python
# Certificate subject: /C=BR/ST=SP/L=SaoPaulo/O=AutonomyLogic/OU=Development/CN=07048933
# Agent ID: 07048933
```

The agent ID is:
- Generated by the cloud provisioning API during installation
- Embedded in the certificate CN field
- Extracted once at module load time and cached
- Used to identify the device in all cloud communications

**Implementation:** `src/tools/ssl.py` - `get_agent_id()`

### Certificate Security

The installer sets strict permissions on credentials:
- Private key: `~/.mtls/client.key` (permissions: 600)
- Certificate: `~/.mtls/client.crt` (permissions: 644)
- Directory: `~/.mtls/` (permissions: 700)

## Installation

### Prerequisites

- **Operating System**: Linux (Ubuntu, Debian, RHEL, CentOS, etc.)
- **Privileges**: Root or sudo access
- **Docker**: Installed and running (installer will attempt to install if missing)

The installer will automatically install these dependencies if missing:
- `curl` - For downloading and API requests
- `jq` - For JSON parsing
- `openssl` - For certificate generation
- `docker` - For container management

### Quick Installation

```bash
curl https://getedge.me | bash
```

This command downloads and executes the installation script (`install/install.sh`).

### What the Installer Does

The installation script (`install/install.sh`) performs the following steps:

1. **Dependency Check**: Verifies and installs required packages (curl, jq, openssl, docker)

2. **Volume Creation**: Creates Docker named volume `orchestrator-shared` mounted at `/var/orchestrator`

3. **Network Monitor Deployment**:
   - Attempts to pull `ghcr.io/autonomy-logic/autonomy-netmon:latest`
   - Falls back to cloning repository and building locally if pull fails
   - Starts container with `--network=host` and `--restart unless-stopped`

4. **Orchestrator Provisioning**:
   - Requests unique orchestrator ID from cloud provisioning API
   - Generates RSA-4096 client certificate with CN=<orchestrator_id>
   - Stores certificate and key in `~/.mtls/`
   - Uploads certificate to cloud for registration

5. **Agent Deployment**:
   - Attempts to pull `ghcr.io/autonomy-logic/orchestrator-agent:latest`
   - Falls back to cloning repository and building locally if pull fails
   - Starts container with volume mounts and `--restart unless-stopped`

6. **Verification**: Displays orchestrator ID and expiration information

### Post-Installation

After successful installation, you will have:

**Containers:**
- `orchestrator_agent` - Main orchestrator agent
- `autonomy_netmon` - Network monitor sidecar

**Volumes:**
- `orchestrator-shared` - Shared volume mounted at `/var/orchestrator`

**Credentials:**
- `~/.mtls/client.key` - Private key (600 permissions)
- `~/.mtls/client.crt` - Client certificate (644 permissions)

**Verification Commands:**
```bash
# Check container status
docker ps

# View agent logs
docker logs -f orchestrator_agent

# View network monitor logs
docker logs -f autonomy_netmon

# Check shared volume
docker volume inspect orchestrator-shared
```

### Linking to Cloud

After installation, copy the displayed orchestrator ID and paste it into the Autonomy Edge web application to link your device to your account.

## Networking Model

### MACVLAN Networks

MACVLAN networks allow runtime containers to appear as physical devices on the LAN with their own MAC and IP addresses.

**Key Features:**
- One MACVLAN network per physical interface and subnet combination
- Network name pattern: `macvlan_<interface>_<subnet>` (e.g., `macvlan_eth0_192.168.1.0_24`)
- Automatic subnet and gateway detection via network monitor cache
- Reuses existing MACVLAN networks to avoid Docker pool overlap errors
- Supports both DHCP and manual IP configuration

**Network Creation Logic:**
1. Check if MACVLAN network already exists for the interface/subnet
2. If not, query network monitor cache for subnet and gateway
3. Create MACVLAN network with detected or provided configuration
4. If pool overlap error occurs, search for and reuse existing matching network

**Implementation:** `src/use_cases/docker_manager/create_runtime_container.py` - `get_or_create_macvlan_network()`

### Internal Bridge Networks

Each runtime container gets a dedicated internal bridge network for agent-to-runtime communication.

**Key Features:**
- Network name pattern: `<container_name>_internal`
- Internal-only (no external routing)
- Used for runtime control plane communication (port 8443)
- Independent of MACVLAN configuration changes
- Orchestrator agent connects to all runtime internal networks

**Implementation:** `src/use_cases/docker_manager/create_runtime_container.py` - `create_internal_network()`

### Dynamic Network Adaptation

When the host moves between networks (e.g., DHCP renewal to different subnet), the agent automatically reconnects runtime containers.

**Process:**
1. Network monitor detects interface address/route change via netlink
2. Debounces changes for 3 seconds to avoid rapid reconnections
3. Publishes `network_change` event to agent via Unix socket
4. Agent loads persisted vNIC configurations from `/var/orchestrator/runtime_vnics.json`
5. For each affected runtime container:
   - Disconnects from old MACVLAN network
   - Creates/retrieves new MACVLAN network for new subnet
   - Reconnects container with preserved IP/MAC settings (if manual mode)
6. Container maintains connectivity with brief interruption

**Implementation:**
- `src/use_cases/network_monitor/network_event_listener.py` - Event handling and reconnection
- `src/use_cases/docker_manager/vnic_persistence.py` - vNIC configuration persistence

### vNIC Configuration

Runtime containers support multiple virtual network interfaces (vNICs), each with configurable properties:

**Configuration Options:**
- `name` - Virtual NIC identifier
- `parent_interface` - Physical host interface (e.g., "eth0")
- `parent_subnet` - Parent network subnet (optional, auto-detected if omitted)
- `parent_gateway` - Parent network gateway (optional, auto-detected if omitted)
- `network_mode` - "dhcp" or "manual"
- `ip_address` - Static IP address (manual mode only)
- `subnet` - Subnet mask (manual mode only)
- `gateway` - Gateway address (manual mode only)
- `dns` - List of DNS servers (optional)
- `mac_address` - Custom MAC address (optional, auto-generated if omitted)

**Persistence:**
- vNIC configurations are saved to `/var/orchestrator/runtime_vnics.json`
- Used for automatic reconnection after network changes
- Preserved across container restarts

## Cloud Protocol

### Transport

- **Protocol**: Socket.IO over HTTPS/WebSocket
- **Server**: `api.getedge.me`
- **Authentication**: Mutual TLS (mTLS)
- **Reconnection**: Automatic with exponential backoff (1-5 seconds)

### WebSocket Topics

The agent handles the following command topics from the cloud:

#### Fully Implemented Topics

| Topic | Description | Implementation |
|-------|-------------|----------------|
| `connect` | Connection established | Starts heartbeat emitter |
| `disconnect` | Connection closed | Logs disconnection |
| `create_new_runtime` | Create new runtime container | Creates container with MACVLAN and internal networks |
| `delete_device` | Delete runtime container | Removes container and associated networks |
| `delete_orchestrator` | Self-destruct agent | Removes orchestrator container |
| `run_command` | Execute runtime command | Proxies HTTP command to runtime container |
| `get_consumption_device` | Get device metrics | Returns CPU/memory usage for specified period |
| `get_consumption_orchestrator` | Get orchestrator metrics | Returns agent CPU/memory usage for specified period |

**Source:** `src/controllers/websocket_controller/topics/receivers/`

#### Placeholder Topics

The following topics are registered but return dummy responses (not yet fully implemented):

- `start_device` - Returns `{"action": "start_device", "success": true}`
- `stop_device` - Returns `{"action": "stop_device", "success": true}`
- `restart_device` - Returns `{"action": "restart_device", "success": true}`

### Heartbeat

The agent emits periodic heartbeat messages to report system health and metrics.

**Interval:** 5 seconds

**Payload:**
```json
{
  "agent_id": "07048933",
  "cpu_usage": 15.2,
  "memory_usage": 2.5,
  "memory_total": 16.0,
  "disk_usage": 45.8,
  "disk_total": 500.0,
  "uptime": 86400,
  "status": "online",
  "timestamp": "2025-11-20T20:30:45.123456"
}
```

**Fields:**
- `agent_id` - Unique orchestrator identifier
- `cpu_usage` - CPU usage percentage (0-100)
- `memory_usage` - Memory usage in GB
- `memory_total` - Total memory in GB
- `disk_usage` - Disk usage in GB
- `disk_total` - Total disk space in GB
- `uptime` - Uptime in seconds
- `status` - Agent status ("online")
- `timestamp` - ISO 8601 timestamp

**Implementation:** `src/controllers/websocket_controller/topics/emitters/heartbeat.py`

### Contract Validation

All incoming messages are validated against predefined contracts before processing.

**Validation Features:**
- Type checking (string, number, boolean, date, list)
- Required field validation
- Nested object validation
- Optional field support

**Base Contracts:**
```python
BASE_MESSAGE = {
    "correlation_id": NumberType,
    "action": StringType,
    "requested_at": DateType
}

BASE_DEVICE = {
    **BASE_MESSAGE,
    "device_id": StringType
}
```

**Implementation:** `src/tools/contract_validation.py`

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

### Container Creation Process

1. **Validation**: Validates message against contract schema
2. **Image Pull**: Pulls `ghcr.io/autonomy-logic/openplc-runtime:latest` (uses local if pull fails)
3. **Internal Network**: Creates internal bridge network `<container_name>_internal`
4. **MACVLAN Networks**: Creates or retrieves MACVLAN network for each vNIC
5. **Container Creation**: Creates container with restart policy "always"
6. **Network Attachment**: Connects container to internal network first, then MACVLAN networks
7. **Agent Connection**: Connects orchestrator agent to internal network
8. **IP Registration**: Registers container's internal IP in client registry
9. **vNIC Persistence**: Saves vNIC configurations to `/var/orchestrator/runtime_vnics.json`

### Response

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

## Network Monitor Sidecar

### Purpose

The network monitor sidecar provides real-time network discovery and change detection for the orchestrator agent.

### Architecture

**Container:** `autonomy_netmon`  
**Image:** `ghcr.io/autonomy-logic/autonomy-netmon:latest`  
**Network Mode:** `--network=host` (required for physical interface access)  
**Restart Policy:** `unless-stopped`

### Communication

**IPC Method:** Unix domain socket  
**Socket Path:** `/var/orchestrator/netmon.sock`  
**Protocol:** JSON lines (one event per line)  
**Permissions:** 0666 (readable/writable by all)

### Event Types

#### network_discovery

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

#### network_change

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

### Monitoring Behavior

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

### Agent Integration

The orchestrator agent connects to the network monitor socket on startup:

1. **Connection**: Opens Unix socket connection to `/var/orchestrator/netmon.sock`
2. **Discovery**: Receives initial `network_discovery` event with all interfaces
3. **Caching**: Stores interface information in `INTERFACE_CACHE` for subnet detection
4. **Monitoring**: Listens for `network_change` events
5. **Reconnection**: Triggers container reconnection when parent interface changes

**Implementation:**
- `src/use_cases/network_monitor/network_event_listener.py` - Event listener
- `src/use_cases/network_monitor/interface_cache.py` - Interface cache

### Healthcheck

The network monitor includes a Docker healthcheck:

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD test -S /var/orchestrator/netmon.sock || exit 1
```

Verifies that the Unix socket exists and is accessible.

## Logging and Metrics

### Log Locations

**Container Logs:**
```bash
# Agent logs
docker logs -f orchestrator_agent

# Network monitor logs
docker logs -f autonomy_netmon
```

**File Logs (inside agent container):**
- `/var/orchestrator/logs/orchestrator-logs-YYYY-MM-DD.log` - Operational logs (configurable level)
- `/var/orchestrator/debug/orchestrator-debug-YYYY-MM-DD.log` - Debug logs (DEBUG level)

**Network Monitor Logs (inside netmon container):**
- `/var/log/autonomy-netmon.log` - Network monitor logs

### Log Levels

The agent supports configurable log levels via command-line argument:

```bash
python3 src/index.py --log-level DEBUG
```

**Available Levels:**
- `DEBUG` - Detailed diagnostic information
- `INFO` - General informational messages (default)
- `WARNING` - Warning messages
- `ERROR` - Error messages
- `CRITICAL` - Critical errors

### Log Rotation

Logs are automatically rotated daily with the date in the filename pattern.

### System Metrics

The agent collects and reports system metrics via heartbeat messages:

**CPU Usage:**
- Measured using `psutil.cpu_percent()`
- Non-blocking query (interval=None)
- Reported as percentage (0-100)

**Memory Usage:**
- Total memory computed once at startup
- Current usage queried via `psutil.virtual_memory().used`
- Reported in GB

**Disk Usage:**
- Total disk space computed once at startup
- Current usage summed across physical partitions
- Filters out virtual filesystems (tmpfs, devtmpfs, overlay, etc.)
- Deduplicates devices to prevent double-counting
- Reported in GB

**Uptime:**
- Computed from process start time
- Reported in seconds

**Implementation:** `src/tools/system_metrics.py`

## Directory Structure

```
orchestrator-agent/
├── src/                                    # Source code
│   ├── index.py                            # Entry point with reconnection loop
│   ├── controllers/                        # Communication protocol handlers
│   │   ├── __init__.py                     # Main WebSocket task
│   │   ├── websocket_controller/           # WebSocket client and topics
│   │   │   ├── __init__.py                 # Client configuration
│   │   │   └── topics/                     # Topic handlers
│   │   │       ├── __init__.py             # Topic registration
│   │   │       ├── receivers/              # Incoming message handlers
│   │   │       │   ├── connect.py
│   │   │       │   ├── disconnect.py
│   │   │       │   ├── create_new_runtime.py
│   │   │       │   ├── delete_device.py
│   │   │       │   ├── delete_orchestrator.py
│   │   │       │   ├── run_command.py
│   │   │       │   ├── start_device.py
│   │   │       │   ├── stop_device.py
│   │   │       │   ├── restart_device.py
│   │   │       │   ├── get_consumption_device.py
│   │   │       │   └── get_consumption_orchestrator.py
│   │   │       └── emitters/               # Outgoing message handlers
│   │   │           ├── __init__.py
│   │   │           └── heartbeat.py        # Periodic heartbeat emitter
│   │   └── webrtc_controller/              # WebRTC (not implemented)
│   ├── use_cases/                          # Business logic
│   │   ├── docker_manager/                 # Container and network management
│   │   │   ├── __init__.py                 # Docker client and registry
│   │   │   ├── create_runtime_container.py # Runtime container creation
│   │   │   ├── create_new_container.py     # Legacy container creation
│   │   │   ├── delete_runtime_container.py # Container deletion
│   │   │   ├── vnic_persistence.py         # vNIC configuration persistence
│   │   │   └── selfdestruct.py             # Agent self-termination
│   │   ├── runtime_commands/               # Runtime command execution
│   │   │   ├── __init__.py                 # HTTP request utilities
│   │   │   └── run_command.py              # Command execution
│   │   └── network_monitor/                # Network monitoring
│   │       ├── __init__.py
│   │       ├── network_event_listener.py   # Event listener and reconnection
│   │       └── interface_cache.py          # Interface information cache
│   └── tools/                              # Utilities
│       ├── logger.py                       # Logging with rotation
│       ├── ssl.py                          # mTLS configuration and agent ID
│       ├── system_metrics.py               # System metrics collection
│       ├── system_info.py                  # System information
│       ├── contract_validation.py          # Message schema validation
│       └── usage_buffer.py                 # Usage metrics buffer
├── install/                                # Installation files
│   ├── install.sh                          # Installation script
│   ├── autonomy-netmon.py                  # Network monitor daemon
│   └── Dockerfile.netmon                   # Network monitor container image
├── .devcontainer/                          # VS Code dev container
│   ├── devcontainer.json                   # Dev container configuration
│   ├── Dockerfile                          # Dev container image
│   └── requirements.txt                    # Dev dependencies
├── .github/workflows/                      # CI/CD
│   └── docker.yml                          # Multi-arch image build
├── Dockerfile                              # Production container image
├── requirements.txt                        # Production dependencies
└── README.md                               # This file
```

## Local Development

### Prerequisites

- Python 3.11 or higher
- Docker installed and running
- mTLS certificates in `~/.mtls/` (see [Installation](#installation))

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Autonomy-Logic/orchestrator-agent.git
   cd orchestrator-agent
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Generate mTLS certificates** (if not already provisioned):
   
   The installer normally provisions these certificates. For local development, you can generate self-signed certificates:
   
   ```bash
   mkdir -p ~/.mtls
   openssl req -x509 -newkey rsa:4096 -nodes \
     -keyout ~/.mtls/client.key \
     -out ~/.mtls/client.crt \
     -subj "/C=BR/ST=SP/L=SaoPaulo/O=AutonomyLogic/OU=Development/CN=dev-agent" \
     -days 365
   chmod 600 ~/.mtls/client.key
   ```
   
   **Note:** Development certificates will not authenticate with the production cloud server.

4. **Run the agent:**
   ```bash
   python3 src/index.py
   ```

5. **Set log level** (optional):
   ```bash
   python3 src/index.py --log-level DEBUG
   ```

### VS Code Dev Container

The repository includes a VS Code dev container configuration for consistent development environments.

**Features:**
- Python 3.11 environment
- Docker-outside-of-Docker (uses host Docker daemon)
- Volume mounts for mTLS certificates and Docker socket
- Pre-installed dependencies

**Usage:**
1. Open repository in VS Code
2. Install "Dev Containers" extension
3. Press `F1` → "Dev Containers: Reopen in Container"

**Configuration:** `.devcontainer/devcontainer.json`

## CI/CD

### Multi-Architecture Image Builds

The repository includes a GitHub Actions workflow that builds and publishes multi-architecture Docker images.

**Workflow:** `.github/workflows/docker.yml`

**Trigger Conditions:**
- Push to `main` branch
- Manual workflow dispatch

**Platforms:**
- `linux/amd64` - x86_64 architecture
- `linux/arm64` - ARM 64-bit (e.g., Raspberry Pi 4, AWS Graviton)
- `linux/arm/v7` - ARM 32-bit (e.g., Raspberry Pi 3)

**Build Process:**
1. Checkout code
2. Set up QEMU for cross-architecture emulation
3. Set up Docker Buildx for multi-platform builds
4. Login to GitHub Container Registry (GHCR)
5. Build and push images with tags:
   - `ghcr.io/autonomy-logic/orchestrator-agent:latest`
   - `ghcr.io/autonomy-logic/orchestrator-agent:<commit-sha>`

**Required Secrets:**
- `GHCR_USERNAME` - GitHub Container Registry username
- `GHCR_TOKEN` - GitHub Container Registry token

**Note:** The workflow triggers on `main` branch only. Pull requests to `development` will not trigger image builds.

## Troubleshooting

### mTLS Certificate Issues

**Symptom:** `FileNotFoundError: [Errno 2] No such file or directory: '/root/.mtls/client.crt'`

**Cause:** mTLS certificates not found or incorrect permissions

**Solution:**
1. Verify certificates exist:
   ```bash
   ls -la ~/.mtls/
   ```
2. Check permissions:
   ```bash
   chmod 600 ~/.mtls/client.key
   chmod 644 ~/.mtls/client.crt
   chmod 700 ~/.mtls/
   ```
3. Re-run installer if certificates are missing:
   ```bash
   curl https://getedge.me | bash
   ```

### WebSocket Connection Errors

**Symptom:** `Socket.IO connection error: <error details>`

**Possible Causes:**
- Invalid or expired mTLS certificate
- Network connectivity issues
- Cloud server unavailable
- Incorrect agent ID in certificate

**Solution:**
1. Check agent logs:
   ```bash
   docker logs orchestrator_agent
   ```
2. Verify certificate CN matches agent ID:
   ```bash
   openssl x509 -in ~/.mtls/client.crt -noout -subject
   ```
3. Test network connectivity:
   ```bash
   curl -v https://api.getedge.me
   ```
4. Restart agent container:
   ```bash
   docker restart orchestrator_agent
   ```

### Network Monitor Socket Missing

**Symptom:** `Network monitor socket not found at /var/orchestrator/netmon.sock, waiting for network monitor daemon...`

**Cause:** Network monitor sidecar not running or socket not created

**Solution:**
1. Check netmon container status:
   ```bash
   docker ps -a | grep autonomy_netmon
   ```
2. Check netmon logs:
   ```bash
   docker logs autonomy_netmon
   ```
3. Verify shared volume:
   ```bash
   docker volume inspect orchestrator-shared
   ```
4. Restart netmon container:
   ```bash
   docker restart autonomy_netmon
   ```
5. Check socket permissions:
   ```bash
   docker exec autonomy_netmon ls -la /var/orchestrator/netmon.sock
   ```

### Docker Network Overlap Errors

**Symptom:** `Pool overlaps with other one on this address space`

**Cause:** Attempting to create MACVLAN network with subnet that conflicts with existing network

**Solution:**
The agent automatically handles this by searching for and reusing existing MACVLAN networks. Check logs for:
```
Network overlap detected for subnet X.X.X.X/XX. Searching for existing MACVLAN network to reuse...
Found existing MACVLAN network <name> with matching subnet and parent. Reusing it.
```

If the error persists:
1. List existing networks:
   ```bash
   docker network ls
   docker network inspect <network-name>
   ```
2. Remove conflicting networks (if safe):
   ```bash
   docker network rm <network-name>
   ```
3. Check agent logs for detailed error information

### Container Creation Failures

**Symptom:** Runtime container creation fails or times out

**Possible Causes:**
- Docker daemon issues
- Image pull failures
- Network configuration errors
- Insufficient resources

**Solution:**
1. Check agent logs for detailed error:
   ```bash
   docker logs orchestrator_agent | grep -A 20 "Failed to create runtime container"
   ```
2. Verify Docker daemon is running:
   ```bash
   docker info
   ```
3. Test image pull manually:
   ```bash
   docker pull ghcr.io/autonomy-logic/openplc-runtime:latest
   ```
4. Check available resources:
   ```bash
   docker system df
   df -h
   free -h
   ```
5. Verify parent interface exists:
   ```bash
   ip addr show
   ```

### Sidecar Health Issues

**Symptom:** Network monitor container unhealthy or restarting

**Solution:**
1. Check container health:
   ```bash
   docker inspect autonomy_netmon | grep -A 10 Health
   ```
2. Check logs for errors:
   ```bash
   docker logs autonomy_netmon
   ```
3. Verify host network access:
   ```bash
   docker exec autonomy_netmon ip addr
   ```
4. Restart container:
   ```bash
   docker restart autonomy_netmon
   ```

### Agent Not Reconnecting After Network Change

**Symptom:** Runtime containers lose connectivity after host network change

**Solution:**
1. Verify network monitor is detecting changes:
   ```bash
   docker logs autonomy_netmon | grep "network_change"
   ```
2. Check agent is receiving events:
   ```bash
   docker logs orchestrator_agent | grep "Network change detected"
   ```
3. Verify vNIC persistence file exists:
   ```bash
   docker exec orchestrator_agent cat /var/orchestrator/runtime_vnics.json
   ```
4. Check for reconnection errors in agent logs:
   ```bash
   docker logs orchestrator_agent | grep "Failed to reconnect"
   ```

## Contributing

This is a private repository for the Autonomy Logic team. For contribution guidelines and development workflow, please refer to the team's internal documentation.

**Branch Naming Conventions:**
- Features: `feature/JIRA-123-description`
- Bugfixes: `bugfix/JIRA-123-description`
- Hotfixes: `hotfix/JIRA-123-description`

**Pull Request Process:**
1. Create a branch following the naming convention
2. Make your changes with clear, descriptive commit messages
3. Push your branch to the remote repository
4. Open a Pull Request targeting the `development` branch
5. Reference your JIRA ticket in the PR description
6. Request code review from team members

## License

Copyright © 2025 Autonomy Logic. All rights reserved.
