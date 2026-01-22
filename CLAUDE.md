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
└── tools/               # Infrastructure utilities
```

**Data flow:** `index.py` → `controllers/` (topic routing) → `use_cases/` (business logic) → `tools/` (utilities)

### Key Components

- **WebSocket Controller** (`src/controllers/websocket_controller/`): Socket.IO client setup, topic registration, and message routing
- **Topic Receivers** (`src/controllers/websocket_controller/topics/receivers/`): 13 handlers for cloud commands (create_new_runtime, delete_device, run_command, etc.)
- **Topic Emitters** (`src/controllers/websocket_controller/topics/emitters/`): Heartbeat emission every 5 seconds with system metrics
- **Docker Manager** (`src/use_cases/docker_manager/`): Container and MACVLAN network lifecycle
- **Network Event Listener** (`src/tools/network_event_listener.py`): Communicates with sidecar via Unix socket for network change events

### Two-Container Model

The agent runs alongside a network monitor sidecar (`autonomy-netmon`) that uses netlink/pyroute2 to detect host network interface changes and notifies the agent via Unix socket.

## Key Patterns

### Topic Handler Pattern

New topics follow this decorator pattern in `src/controllers/websocket_controller/topics/receivers/`:

```python
from . import topic, validate_message
from tools.contract_validation import StringType, BASE_MESSAGE

NAME = "topic_name"
MESSAGE_TYPE = {**BASE_MESSAGE, "field": StringType}

@topic(NAME)
def init(client):
    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    async def callback(message):
        # Handler logic
        return {"action": NAME, "correlation_id": message.get("correlation_id"), ...}
```

### Contract Validation

Type-safe schema validation in `src/tools/contract_validation.py`:
- `StringType`, `NumberType`, `BooleanType`, `DateType`
- `ListType(ItemType)` for arrays
- `OptionalType(Type)` for optional fields
- `validate_contract(schema, data)` or use `@validate_message` decorator

### Operations State Tracking

Prevents race conditions for container operations (`src/tools/operations_state.py`):
```python
from tools.operations_state import set_creating, is_operation_in_progress, clear_state

if not set_creating(container_name):
    # Race condition - another operation started
    return error_response
# ... do work ...
clear_state(container_name)
```

## Important Files

- **mTLS certs:** `~/.mtls/client.crt`, `~/.mtls/client.key`
- **Client state:** `/var/orchestrator/data/clients.json`
- **vNIC configs:** `/var/orchestrator/data/vnics.json`
- **Logs:** `/var/orchestrator/logs/`, `/var/orchestrator/debug/`

## Git Workflow

- Feature branches from `development` branch
- PRs target `development`
- CI builds multi-arch images (amd64, arm64, arm/v7) on main branch pushes
