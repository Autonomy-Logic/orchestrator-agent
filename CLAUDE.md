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

### Testing

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run architecture dependency tests
pytest tests/architecture/

# Run with coverage
pytest --cov=src tests/
```

## Architecture

The codebase follows Clean Architecture with dependency injection:

```
src/
├── index.py              # Entry point with reconnection loop
├── bootstrap.py          # Composition root (dependency wiring)
├── entities/             # Domain entities (zero dependencies)
├── controllers/          # Transport layer (WebSocket/WebRTC)
├── use_cases/           # Business logic (Docker, networking, commands)
├── repos/               # Data persistence adapters (JSON files, Docker API)
└── tools/               # Infrastructure utilities
```

**Data flow:** `index.py` → `bootstrap.py` (wiring) → `controllers/` (topic routing) → `use_cases/` (business logic) → `repos/` (persistence) / `tools/` (utilities)

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

### WebRTC Debug Bridge

The debug bridge enables real-time PLC debugging from the browser through a dedicated WebRTC DataChannel labeled `"debug"`. It bridges between the browser and the OpenPLC runtime's Socket.IO `/api/debug` endpoint using persistent sessions.

**Architecture:**
```
Browser (WebRTC DataChannel "debug")
    ↓ JSON messages (debug_start, debug_get_md5, debug_get_list, debug_set, debug_stop)
DebugChannelHandler (controller layer)
    ↓ routes to _handle_start / _handle_command / _handle_stop
run_debug_command (use_case layer) — dispatches single commands
    ↓ builds hex commands via debug_protocol.py
DebugSocketRepo (repo layer) — persistent Socket.IO connection
    ↓ Socket.IO emit("debug_command", {command: hex})
Runtime Container (/api/debug namespace)
```

**Key files:**
- `src/controllers/webrtc_controller/data_channel/debug_channel_handler.py` — WebRTC DataChannel message routing, persistent session management
- `src/use_cases/debug_client/run_debug_command.py` — Stateless command dispatcher for a single debug command
- `src/use_cases/debug_client/validate_session.py` — Single-shot validation sequence (kept for backward compatibility)
- `src/repos/debug_socket_repo.py` — Socket.IO client for runtime's `/api/debug`
- `src/tools/debug_protocol.py` — Pure protocol functions: `build_get_md5()`, `build_get_list()`, `build_set_variable()`, `parse_response()`

**Debug function codes (defined in `debug_protocol.py`):**
| Code | Name | Builder | Parser |
|------|------|---------|--------|
| 0x41 | DEBUG_INFO | `build_get_info()` | `_parse_info()` |
| 0x42 | DEBUG_SET | `build_set_variable()` | `_parse_set()` |
| 0x43 | DEBUG_GET | (unused) | — |
| 0x44 | DEBUG_GET_LIST | `build_get_list()` | `_parse_get_list()` |
| 0x45 | DEBUG_GET_MD5 | `build_get_md5()` | `_parse_get_md5()` |

**Message protocol (Browser ↔ Agent):**

| Browser → Agent | Agent → Browser | Description |
|----------------|----------------|-------------|
| `debug_start` | `debug_connected` | Authenticate + connect Socket.IO |
| `debug_get_md5` | `debug_md5_response` | Get runtime program MD5 |
| `debug_get_list` | `debug_values_response` | Get variable values (raw hex) |
| `debug_set` | `debug_set_response` | Force/release a variable |
| `debug_info` | `debug_info_response` | Get variable count |
| `debug_stop` | `debug_disconnected` | Disconnect Socket.IO |
| (any error) | `debug_error` | Error message |

**Session lifecycle:**
1. Browser sends `debug_start` with `device_id`, `username`, `password`, `port`
2. Agent POSTs to `https://{device_ip}:{port}/api/login` → gets JWT
3. Agent connects Socket.IO to `/api/debug` with JWT auth (persistent connection)
4. Agent responds with `debug_connected`
5. Browser sends arbitrary commands (`debug_get_md5`, `debug_get_list`, `debug_set`)
6. Browser sends `debug_stop` → agent disconnects Socket.IO
7. JWT never sent back to browser

**Polling pattern:** The browser polls at 200ms intervals with `debug_get_list` containing batched variable indexes (max 60 per request). The agent returns raw hex variable data for the browser to parse.

### Debug HTTP Fallback

When the WebRTC DataChannel is unavailable (restrictive NAT, firewall), debug commands fall back to the existing `run_command` WebSocket topic. The cloud server requires zero changes — it already passes `data: Record<string, any>` through untouched.

**Architecture (HTTP path):**
```
Browser (HTTP POST /orchestrators/run-command)
    ↓ { method: "POST", api: "debug", data: { type: "debug_get_list", indexes: [...] } }
Cloud Server (passes through via WebSocket)
    ↓ run_command topic
run_command.py (controller layer) — routes api=="debug" to DebugSessionManager
    ↓
DebugSessionManager (controller layer) — persistent sessions keyed by device_id
    ↓ routes to _handle_start / _handle_command / _handle_stop
run_debug_command (use_case layer) — same as WebRTC path
    ↓
DebugSocketRepo (repo layer) — same as WebRTC path
    ↓
Runtime Container (/api/debug namespace)
```

**Key file:**
- `src/controllers/websocket_controller/debug_session_manager.py` — HTTP-path session manager, mirrors `DebugChannelHandler` logic

**Differences from WebRTC path:**
- Sessions keyed by `device_id` (not WebRTC session ID) — one session per device
- Thread-safe via `threading.Lock` (runs in `asyncio.to_thread`, cleanup runs on event loop)
- Background cleanup loop every 60s disconnects sessions idle >5 minutes
- Browser polls at 2s (vs 200ms for WebRTC) to avoid overloading HTTP path
- Response is synchronous: `run_command` returns `{"status": "success", "debug_response": {...}}`

**Transport selection (browser):** `sendDebugMessage` tries WebRTC DataChannel first. If the channel is not open, it wraps the message in an HTTP `run_command` request and feeds the response into the same `onDebugMessage` pipeline. Polling interval adjusts automatically (200ms ↔ 2s) and switches back to WebRTC when the DataChannel recovers.

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
