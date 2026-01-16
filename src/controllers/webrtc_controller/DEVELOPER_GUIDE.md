# WebRTC Terminal Feature - Developer Guide

This guide helps developers understand, debug, and modify the WebRTC terminal feature.

---

## Quick Reference

| Component | Location | Purpose |
|-----------|----------|---------|
| Session Manager | `webrtc_controller/__init__.py` | Manages peer connections and session lifecycle |
| Offer Handler | `signaling/offer_handler.py` | Handles SDP offer/answer exchange |
| ICE Handler | `signaling/ice_handler.py` | Handles ICE candidate exchange |
| Terminal Channel | `data_channel/terminal_channel.py` | Terminal I/O protocol over data channel |
| PTY Bridge | `use_cases/terminal_pty/pty_bridge.py` | Bridges data channel to Docker exec |
| PTY Session | `use_cases/terminal_pty/create_pty_session.py` | Creates Docker exec PTY sessions |

---

## Architecture Overview

```
Browser                Cloud Server              Orchestrator Agent
   │                        │                           │
   │  1. webrtc:offer      │   2. webrtc:offer        │
   │ ───────────────────►  │  ─────────────────────►  │
   │                        │                           │
   │                        │   3. webrtc:answer       │
   │  4. webrtc:answer     │  ◄─────────────────────  │
   │ ◄───────────────────  │                           │
   │                        │                           │
   │  5. ICE candidates (bidirectional)                │
   │ ◄─────────────────────────────────────────────►  │
   │                        │                           │
   │  6. WebRTC Data Channel (P2P, bypasses cloud)    │
   │ ◄═══════════════════════════════════════════════►│
   │                        │                           │
   │                        │                    ┌──────┴──────┐
   │                        │                    │ PTY Bridge  │
   │                        │                    └──────┬──────┘
   │                        │                           │
   │                        │                    ┌──────┴──────┐
   │                        │                    │  Container  │
   │                        │                    │  (docker    │
   │                        │                    │   exec)     │
   │                        │                    └─────────────┘
```

### Data Flow

1. **Signaling Phase** (via Socket.IO through cloud):
   - Browser creates RTCPeerConnection and data channel
   - Browser sends SDP offer to agent via cloud
   - Agent creates RTCPeerConnection and sends SDP answer
   - Both sides exchange ICE candidates

2. **Connected Phase** (P2P data channel):
   - Browser sends JSON messages: `{"type": "input", "data": "ls\n"}`
   - Agent writes to PTY, reads output, sends back: `{"type": "output", "data": "..."}`

---

## Session Lifecycle

```
CREATED ──► CONNECTING ──► CONNECTED ──► DISCONNECTED ──► CLOSED
   │             │              │               │
   └─────────────┴──────────────┴───────────────┘
                        │
                   (timeout or error)
                        ▼
                      CLOSED
```

### State Transitions

| From | To | Trigger |
|------|----|---------|
| - | CREATED | `session_manager.create_session()` |
| CREATED | CONNECTING | SDP offer received |
| CONNECTING | CONNECTED | Data channel opens |
| CONNECTED | DISCONNECTED | Connection lost |
| Any | CLOSED | Timeout, error, or explicit close |

---

## Common Tasks

### Adding a New Data Channel Message Type

1. **Define the message format** in `terminal_channel.py` docstring
2. **Add handler** in `_handle_message()`:

```python
async def _handle_message(self, raw_message):
    # ... existing code ...

    if msg_type == "input":
        await self._handle_input(message.get("data", ""))
    elif msg_type == "your_new_type":
        await self._handle_your_new_type(message)
    # ...

async def _handle_your_new_type(self, message):
    """Handle your new message type."""
    # Your logic here
    pass
```

3. **Update documentation** in `WEBRTC_IMPLEMENTATION_PLAN.md`

### Adding a New Signaling Topic

1. **Create handler file** in `signaling/`:

```python
# signaling/your_handler.py
from tools.logger import log_info, log_error

NAME = "webrtc:your_topic"

_client = None
_session_manager = None

def init(client, session_manager):
    global _client, _session_manager
    _client = client
    _session_manager = session_manager

    @client.on(NAME)
    async def handle_your_topic(message):
        log_info(f"Received {NAME}: {message}")
        # Your logic here
```

2. **Register in `signaling/__init__.py`**:

```python
from .your_handler import init as init_your_handler

def initialize_signaling(client, session_manager):
    # ... existing handlers ...
    init_your_handler(client, session_manager)
```

### Changing Session Timeout

Edit `webrtc_controller/__init__.py`:

```python
SESSION_TIMEOUT_SECONDS = 300  # Change this value (in seconds)
CLEANUP_INTERVAL_SECONDS = 60  # How often to check for expired sessions
```

### Changing Default Shell

Edit `use_cases/terminal_pty/create_pty_session.py`:

```python
DEFAULT_SHELL = "/bin/bash"  # Primary shell
FALLBACK_SHELL = "/bin/sh"   # If bash not available
```

---

## Debugging

### Enable Debug Logging

```bash
python3 src/index.py --log-level DEBUG
```

### Key Log Messages to Look For

| Log Message | Meaning |
|-------------|---------|
| `Creating WebRTC session` | New session started |
| `Terminal data channel opened` | Data channel ready |
| `PTY bridge connected` | Docker exec attached |
| `PTY read loop ended` | Container output stream closed |
| `Session timed out` | Inactive session cleaned up |

### Common Issues

#### 1. "Container not found" Error

**Symptom**: PTY connection fails with container not found

**Cause**: The `device_id` in the offer doesn't match any container in `CLIENTS`

**Debug**:
```python
# In offer_handler.py, add logging:
from use_cases.docker_manager import CLIENTS
log_debug(f"Available containers: {list(CLIENTS.keys())}")
log_debug(f"Requested device_id: {device_id}")
```

**Fix**: Ensure the browser sends the correct container name as `device_id`

#### 2. ICE Connection Fails

**Symptom**: Session stays in CONNECTING state, never reaches CONNECTED

**Possible Causes**:
- Firewall blocking UDP
- NAT traversal issues
- STUN/TURN server not configured

**Debug**: Check ICE connection state changes:
```python
# Already logged in offer_handler.py
@pc.on("iceconnectionstatechange")
async def on_ice_state_change():
    log_info(f"ICE state: {pc.iceConnectionState}")
```

**Note**: Current implementation doesn't use TURN servers. For restrictive NATs, you may need to add TURN configuration:
```python
pc = RTCPeerConnection(configuration=RTCConfiguration(
    iceServers=[
        RTCIceServer(urls="stun:stun.l.google.com:19302"),
        RTCIceServer(
            urls="turn:your-turn-server.com",
            username="user",
            credential="pass"
        )
    ]
))
```

#### 3. PTY Output Not Reaching Browser

**Symptom**: Commands typed but no output displayed

**Debug Steps**:
1. Check PTY bridge is connected: `pty_bridge.is_connected`
2. Check data channel is open: `channel.readyState == "open"`
3. Add logging in `send_output_bytes()`:
```python
def send_output_bytes(self, data: bytes):
    log_debug(f"Sending {len(data)} bytes to browser")
    # ...
```

#### 4. Session Memory Leak

**Symptom**: Sessions not being cleaned up, memory grows

**Debug**:
```python
# Check active sessions
from controllers import get_webrtc_session_manager
manager = get_webrtc_session_manager()
print(f"Active sessions: {len(manager._sessions)}")
for sid, session in manager._sessions.items():
    print(f"  {sid}: state={session['state']}, age={time.time() - session['last_activity']}s")
```

**Fix**: Ensure `close_session()` is called on errors and disconnects

---

## Testing

### Unit Testing a Component

```python
import asyncio
import sys
sys.path.insert(0, 'src')

# Test session manager
from controllers.webrtc_controller import WebRTCSessionManager, SessionState

async def test_session_manager():
    manager = WebRTCSessionManager()
    await manager.start()

    # Create session
    pc = await manager.create_session("test-123", "container-1")
    assert pc is not None

    # Check state
    session = manager.get_session("test-123")
    assert session["state"] == SessionState.CREATED

    # Update state
    manager.update_session_state("test-123", SessionState.CONNECTED)
    session = manager.get_session("test-123")
    assert session["state"] == SessionState.CONNECTED

    # Cleanup
    await manager.close_session("test-123")
    await manager.stop()

    print("All tests passed!")

asyncio.run(test_session_manager())
```

### Integration Testing with Mock Browser

See `WEBRTC_IMPLEMENTATION_PLAN.md` for browser client example code.

For local testing without a real browser:
```python
from aiortc import RTCPeerConnection, RTCSessionDescription

async def simulate_browser():
    # Create "browser" peer connection
    browser_pc = RTCPeerConnection()
    channel = browser_pc.createDataChannel("terminal")

    @channel.on("message")
    def on_message(msg):
        print(f"Received: {msg}")

    # Create offer
    offer = await browser_pc.createOffer()
    await browser_pc.setLocalDescription(offer)

    # Send to agent via Socket.IO (mock or real)
    # ...
```

---

## Code Patterns

### Async/Await with Docker API

Docker SDK is synchronous. We use ThreadPoolExecutor to avoid blocking:

```python
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=4)

async def async_docker_operation():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _executor,
        sync_docker_function,
        arg1, arg2
    )
    return result
```

### Socket Read/Write Pattern

PTY socket I/O uses blocking calls in executor:

```python
async def _read_loop(self):
    loop = asyncio.get_event_loop()
    while not self._closed:
        data = await loop.run_in_executor(
            None,  # Default executor
            self._blocking_read,
            sock,
        )
        if data:
            self.output_callback(data)
```

### Event Handler Registration

aiortc uses decorator pattern for events:

```python
@pc.on("datachannel")
def on_datachannel(channel):
    # Handle new data channel
    pass

@channel.on("message")
def on_message(message):
    # Handle message
    pass
```

---

## Important Gotchas

### 1. aiortc ICE Candidate Parsing

**Wrong**:
```python
from aiortc import RTCIceCandidate
candidate = RTCIceCandidate(candidate_str)  # Doesn't work!
```

**Correct**:
```python
from aiortc.sdp import candidate_from_sdp
candidate = candidate_from_sdp(candidate_str)
candidate.sdpMid = sdp_mid
candidate.sdpMLineIndex = sdp_mline_index
```

### 2. Data Channel Must Be Created Before Offer

The browser must create the data channel before creating the offer. The agent receives it via the `datachannel` event.

### 3. Socket.IO Message Format

Responses must include `correlation_id` for the cloud to route them correctly:

```python
return {
    "action": "webrtc:offer",
    "correlation_id": message.get("correlation_id"),
    "status": "success",
    # ... other fields
}
```

### 4. PTY Socket Lifecycle

The Docker exec socket closes when:
- The shell process exits
- The container stops
- The exec is killed

Always handle socket closure gracefully in the read loop.

### 5. Session Cleanup Order

When closing a session, cleanup in this order:
1. Close PTY bridge (stops read loop)
2. Close data channel
3. Close peer connection
4. Remove from session manager

---

## File Dependencies

```
webrtc_controller/
├── __init__.py              ← Imports from signaling/, data_channel/
├── signaling/
│   ├── __init__.py          ← Imports handlers
│   ├── offer_handler.py     ← Uses session_manager, TerminalChannel
│   ├── ice_handler.py       ← Uses session_manager
│   └── disconnect_handler.py← Uses session_manager
└── data_channel/
    ├── __init__.py
    └── terminal_channel.py  ← Uses PTYBridge from use_cases/

use_cases/terminal_pty/
├── __init__.py              ← Exports PTYBridge, create_pty_session
├── create_pty_session.py    ← Uses docker CLIENT, CLIENTS
└── pty_bridge.py            ← Uses create_pty_session
```

---

## Performance Considerations

- **Data channel throughput**: ~5 Mbps sufficient for terminal I/O
- **PTY read chunk size**: 4096 bytes (configurable in `_blocking_read`)
- **Session cleanup interval**: 60 seconds (balance between responsiveness and CPU)
- **ThreadPoolExecutor workers**: 4 (for Docker API calls)

For high-concurrency scenarios, consider:
- Increasing executor workers
- Reducing cleanup interval
- Adding connection pooling for Docker API

---

## Related Documentation

- [WEBRTC_IMPLEMENTATION_PLAN.md](./WEBRTC_IMPLEMENTATION_PLAN.md) - Full protocol specification
- [aiortc Documentation](https://aiortc.readthedocs.io/)
- [Docker SDK for Python](https://docker-py.readthedocs.io/)
- [WebRTC API (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API)
