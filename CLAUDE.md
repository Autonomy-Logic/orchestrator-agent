# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Orchestrator Agent is a Python daemon that runs on edge devices as a Docker container. It maintains a persistent WebSocket connection (via Socket.IO) to the Autonomy Edge Cloud using mTLS authentication and orchestrates OpenPLC v4 runtime containers (vPLCs) on the host machine.

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the agent
python3 src/index.py

# Run with debug logging
python3 src/index.py --log-level DEBUG

# Build Docker image
docker build -t orchestrator-agent:latest .
```

**Note:** There is no automated test suite. Manual testing is required.

## Architecture

The codebase follows a layered architecture:

```
src/
├── index.py              # Entry point with reconnection loop
├── controllers/          # Transport layer (WebSocket/WebRTC)
├── use_cases/           # Business logic (Docker, networking, commands)
├── repos/               # Data persistence adapters (JSON files, Docker API)
└── tools/               # Infrastructure utilities
```

**Data flow:** `index.py` → `controllers/` (topic routing) → `use_cases/` (business logic) → `repos/` (persistence) / `tools/` (utilities)

### Two-Container Model

The agent runs alongside a network monitor sidecar (`autonomy-netmon`) that uses netlink/pyroute2 to detect host network interface changes and notifies the agent via Unix socket.

- **orchestrator-agent**: Main container managing Docker resources and cloud communication
- **autonomy-netmon**: Sidecar container (runs with `--network=host`) monitoring physical network interfaces via netlink events

### Communication Paths

- **Agent ↔ Cloud**: Socket.IO over HTTPS with mutual TLS (`api.getedge.me`)
- **Agent ↔ Sidecar**: Unix domain socket at `/var/orchestrator/netmon.sock` (JSON lines, one-way sidecar → agent)
- **Agent ↔ Runtime**: HTTP over internal bridge network (port 8443)

### Key Components

- **WebSocket Controller** (`src/controllers/websocket_controller/`): Socket.IO client setup, topic registration, and message routing
- **WebRTC Controller** (`src/controllers/webrtc_controller/`): Manages WebRTC peer connections for remote terminal access to runtime containers
- **Topic Receivers** (`src/controllers/websocket_controller/topics/receivers/`): Handlers for cloud commands (create_new_runtime, delete_device, run_command, etc.)
- **Topic Emitters** (`src/controllers/websocket_controller/topics/emitters/`): Heartbeat emission every 5 seconds with system metrics
- **Docker Manager** (`src/use_cases/docker_manager/`): Container and MACVLAN network lifecycle, shared helpers (`stop_and_remove_container`, `remove_internal_network`)
- **Repos** (`src/repos/`): Data persistence adapters — `VNICRepo`, `SerialRepo` (backed by `JsonConfigStore`), `ClientRepo`, `ContainerRuntimeRepo`, etc.
- **Network Event Listener** (`src/tools/network_event_listener.py`): Communicates with sidecar via Unix socket for network change events

### WebRTC Remote Terminal

The WebRTC controller enables real-time terminal access to runtime containers from the cloud UI:

- **Signaling**: Uses existing Socket.IO connection for WebRTC offer/answer/ICE exchange
- **Session Manager**: Tracks peer connections with automatic cleanup of stale sessions (5-minute timeout)
- **Data Channels**: Terminal I/O and keepalive messages over WebRTC data channels
- **NAT Traversal**: Configured with Google STUN servers for connectivity through NAT

Key files:
- `src/controllers/webrtc_controller/__init__.py` - Session manager and initialization
- `src/controllers/webrtc_controller/signaling/` - Offer, ICE, and disconnect handlers
- `src/controllers/webrtc_controller/data_channel/` - Terminal and keepalive channel handling

## Key Patterns

### Topic Handler Pattern

New topics follow this decorator pattern in `src/controllers/websocket_controller/topics/receivers/`:

```python
from . import topic, validate_message, with_response
from tools.contract_validation import StringType, BASE_MESSAGE

NAME = "topic_name"
MESSAGE_TYPE = {**BASE_MESSAGE, "field": StringType}

@topic(NAME)
def init(client, ctx):
    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    @with_response(NAME)
    async def callback(message):
        # Handler logic — return plain dict, decorator adds action + correlation_id
        return {"status": "success", ...}
```

The `@with_response` decorator automatically wraps the return value with `action` and `correlation_id` from the message, eliminating boilerplate in each handler.

### Contract Validation

Type-safe schema validation in `src/tools/contract_validation.py`:
- `StringType`, `NonEmptyStringType`, `NumberType`, `BooleanType`, `DateType`
- `ListType(ItemType)` for arrays
- `OptionalType(Type)` for optional fields
- `validate_contract(schema, data)` or use `@validate_message` decorator
- `BASE_DEVICE` uses `NonEmptyStringType` for `device_id` to reject empty strings at the validation layer

### Operations State Tracking

Prevents race conditions for container operations (`src/tools/operations_state.py`):
```python
from tools.operations_state import begin_operation

# begin_operation checks is_operation_in_progress and sets state atomically
error, ok = begin_operation(container_name, operations_state.set_creating, operations_state=operations_state)
if not ok:
    return error, False
# ... do work ...
operations_state.clear_state(container_name)
```

### Network Model

- MACVLAN networks: `macvlan_<interface>_<subnet>` - containers appear as physical devices on LAN
- Internal bridge networks: `<container_name>_internal` - agent-to-runtime control plane
- vNIC configs persisted for automatic reconnection after network changes

## Important Files

- `src/index.py` - Entry point with reconnection loop
- `src/controllers/__init__.py` - Main WebSocket task, starts network event listener and WebRTC controller
- `src/use_cases/docker_manager/create_runtime_container.py` - Core container creation with MACVLAN/internal networks
- `install/autonomy-netmon.py` - Network monitor sidecar daemon
- `install/install.sh` - Production installation script
- **mTLS certs:** `~/.mtls/client.crt`, `~/.mtls/client.key`
- **Client state:** `/var/orchestrator/data/clients.json`
- **vNIC configs:** `/var/orchestrator/data/vnics.json`
- **Logs:** `/var/orchestrator/logs/`, `/var/orchestrator/debug/`

## Git Workflow

- Feature branches from `development` branch
- PRs target `development`
- CI builds multi-arch images (amd64, arm64, arm/v7) on main branch pushes
