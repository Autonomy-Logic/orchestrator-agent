# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

The Orchestrator Agent is a Python daemon that runs on edge devices as a Docker container. It maintains a persistent mTLS-authenticated WebSocket connection to the Autonomy Edge Cloud and orchestrates OpenPLC v4 runtime containers (vPLCs) on host machines.

## Commands

**Run the agent locally:**
```bash
python3 src/index.py
```

**Run with debug logging:**
```bash
python3 src/index.py --log-level DEBUG
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Note:** There are no automated tests. Manual testing is required against the cloud service.

## Architecture

### Two-Container Architecture
- **orchestrator-agent**: Main container managing Docker resources and cloud communication
- **autonomy-netmon**: Sidecar container (runs with `--network=host`) monitoring physical network interfaces via netlink events

### Communication Paths
- **Agent ↔ Cloud**: Socket.IO over HTTPS with mutual TLS (`api.getedge.me`)
- **Agent ↔ Sidecar**: Unix domain socket at `/var/orchestrator/netmon.sock` (JSON lines, one-way sidecar → agent)
- **Agent ↔ Runtime**: HTTP over internal bridge network (port 8443)

### Layered Code Architecture

**controllers/** - Transport layer handling WebSocket topics and message routing
- Topic handlers use `@topic(name)` decorator for registration
- `@validate_message(contract, name)` decorator validates incoming messages against contracts before processing
- Delegates business logic to use_cases

**use_cases/** - Business logic layer
- `docker_manager/` - Container and MACVLAN network management
- `network_monitor/` - Network event listener and interface cache
- `runtime_commands/` - Proxies commands to runtime containers

**tools/** - Infrastructure utilities
- `contract_validation.py` - Type-safe message validation with BASE_MESSAGE and BASE_DEVICE contracts
- `logger.py` - Logging with rotation
- `ssl.py` - mTLS configuration and agent ID extraction
- `vnic_persistence.py` - Persists vNIC configs to `/var/orchestrator/runtime_vnics.json`
- `network_event_listener.py` - Listens for network change events from sidecar

### Key Patterns

**Adding a new WebSocket topic handler:**
1. Create file in `src/controllers/websocket_controller/topics/receivers/`
2. Use `@topic("topic_name")` decorator
3. Use `@validate_message(CONTRACT, "topic_name")` for validation
4. Register in `src/controllers/websocket_controller/topics/__init__.py`

**Contract validation types:**
- `StringType`, `NumberType`, `BooleanType`, `DateType`
- `ListType(item_type)`, `OptionalType(inner_type)`
- `BASE_MESSAGE` - correlation_id, action, requested_at (all optional)
- `BASE_DEVICE` - extends BASE_MESSAGE with required device_id

**Network model:**
- MACVLAN networks: `macvlan_<interface>_<subnet>` - containers appear as physical devices on LAN
- Internal bridge networks: `<container_name>_internal` - agent-to-runtime control plane
- vNIC configs persisted for automatic reconnection after network changes

## Important Files

- `src/index.py` - Entry point with reconnection loop
- `src/controllers/__init__.py` - Main WebSocket task, starts network event listener
- `src/use_cases/docker_manager/create_runtime_container.py` - Core container creation with MACVLAN/internal networks
- `install/autonomy-netmon.py` - Network monitor sidecar daemon
- `install/install.sh` - Production installation script
