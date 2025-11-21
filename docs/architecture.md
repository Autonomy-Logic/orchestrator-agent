# Architecture

The Orchestrator Agent uses a two-container architecture with a main agent container and a network monitor sidecar that work together to orchestrate OpenPLC v4 runtime containers on edge devices.

## High-Level Overview

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

## Components

### orchestrator-agent Container

The main agent container that orchestrates runtime containers and communicates with the cloud.

**Responsibilities:**
- Maintains mTLS-authenticated Socket.IO session to `api.getedge.me`
- Handles cloud command topics (see [Cloud Protocol](cloud-protocol.md))
- Emits periodic heartbeat messages with system metrics
- Manages Docker resources: containers, MACVLAN networks, internal bridge networks
- Listens for network change events from the sidecar and reconnects runtime containers

**Key Source Files:**
- `src/index.py` - Entry point with reconnection loop
- `src/controllers/websocket_controller/` - WebSocket client and topic handlers
- `src/use_cases/docker_manager/` - Container and network management
- `src/use_cases/network_monitor/` - Network event listener and interface cache

### autonomy-netmon Sidecar

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

See [Network Monitor](network-monitor.md) for detailed documentation.

### Runtime Containers (OpenPLC v4)

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

See [Runtime Containers](runtime-containers.md) for detailed documentation.

## Shared Volume

The `orchestrator-shared` Docker volume is mounted at `/var/orchestrator` in both containers and serves as the communication and persistence layer.

**Contents:**
- `netmon.sock` - Unix domain socket for agent-sidecar IPC
- `runtime_vnics.json` - Persisted vNIC configurations for automatic reconnection
- `logs/` - Operational logs with configurable level
- `debug/` - Debug logs (always DEBUG level)

## Communication Paths

### Agent ↔ Cloud
- **Protocol:** Socket.IO over HTTPS/WebSocket
- **Authentication:** Mutual TLS (mTLS)
- **Direction:** Bidirectional
- **Purpose:** Cloud commands and heartbeat telemetry

### Agent ↔ Sidecar
- **Protocol:** Unix domain socket (JSON lines)
- **Direction:** Sidecar → Agent (one-way)
- **Purpose:** Network discovery and change notifications

### Agent ↔ Runtime Containers
- **Protocol:** HTTP over internal bridge network
- **Direction:** Agent → Runtime (commands)
- **Purpose:** Runtime control and configuration

### Sidecar ↔ Host Network
- **Protocol:** Netlink (pyroute2)
- **Direction:** Host → Sidecar (events)
- **Purpose:** Physical network interface monitoring
