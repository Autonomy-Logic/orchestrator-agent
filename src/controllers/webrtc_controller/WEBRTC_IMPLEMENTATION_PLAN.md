# WebRTC Controller Implementation

This document describes the WebRTC controller implementation for remote terminal access to runtime containers.

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [File Structure](#file-structure)
4. [Signaling Protocol](#signaling-protocol)
5. [Data Channel Protocol](#data-channel-protocol)
6. [Usage](#usage)
7. [Testing](#testing)

---

## Overview

The WebRTC controller enables browser-based remote terminal access to runtime containers (vPLCs) managed by the orchestrator-agent. It uses WebRTC data channels for low-latency, peer-to-peer terminal I/O.

### Key Features
- WebRTC signaling via existing Socket.IO connection
- Data channel for terminal I/O (not video/audio)
- Docker exec PTY integration
- Session timeout and cleanup
- Terminal resize support

### Library Choice: aiortc
- **Pure Python** WebRTC implementation
- **Asyncio native** - integrates with existing codebase
- **Sufficient performance** for terminal I/O (~5 Mbps data channel)

---

## Architecture

### Communication Flow
```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────────────┐
│   Web Browser   │◄───────►│  Signaling      │◄───────►│   Orchestrator Agent    │
│   (xterm.js)    │   WS    │  Server (Cloud) │   WS    │   (WebRTC Peer)         │
└────────┬────────┘         └─────────────────┘         └───────────┬─────────────┘
         │                                                          │
         │         WebRTC Data Channel (P2P)                        │
         └──────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  Runtime Container  │
                         │  (docker exec PTY)  │
                         └─────────────────────┘
```

### Component Layers
1. **Controller Layer** - WebRTC signaling handlers
2. **Session Layer** - RTCPeerConnection management
3. **Channel Layer** - Data channel message protocol
4. **Use Case Layer** - Docker exec PTY bridge

---

## File Structure

```
src/
├── controllers/
│   ├── __init__.py                      # Integrates WebRTC controller
│   └── webrtc_controller/
│       ├── __init__.py                  # WebRTCSessionManager, init/start/stop
│       ├── signaling/
│       │   ├── __init__.py              # initialize_signaling()
│       │   ├── offer_handler.py         # webrtc:offer topic
│       │   ├── ice_handler.py           # webrtc:ice topic
│       │   └── disconnect_handler.py    # webrtc:disconnect topic
│       └── data_channel/
│           ├── __init__.py              # TerminalChannel export
│           └── terminal_channel.py      # Terminal I/O protocol
│
└── use_cases/
    └── terminal_pty/
        ├── __init__.py                  # PTYBridge, create_pty_session exports
        ├── create_pty_session.py        # Docker exec PTY creation
        └── pty_bridge.py                # Data channel ↔ PTY bridge
```

---

## Signaling Protocol

### Socket.IO Topics

| Topic | Direction | Description |
|-------|-----------|-------------|
| `webrtc:offer` | Cloud → Agent | Browser's SDP offer |
| `webrtc:answer` | Agent → Cloud | Agent's SDP answer (return value) |
| `webrtc:ice` | Bidirectional | ICE candidate exchange |
| `webrtc:disconnect` | Cloud → Agent | Session termination |

### Offer Message
```json
{
  "correlation_id": 123,
  "session_id": "unique-session-id",
  "device_id": "runtime-container-name",
  "sdp": "v=0\r\no=- ...",
  "sdp_type": "offer"
}
```

### Answer Response
```json
{
  "action": "webrtc:offer",
  "correlation_id": 123,
  "status": "success",
  "session_id": "unique-session-id",
  "sdp": "v=0\r\no=- ...",
  "sdp_type": "answer"
}
```

### ICE Candidate Message
```json
{
  "session_id": "unique-session-id",
  "candidate": "candidate:1 1 UDP 2122252543 ...",
  "sdp_mid": "0",
  "sdp_mline_index": 0
}
```

---

## Data Channel Protocol

The browser creates a data channel named `terminal`. Messages are JSON-encoded.

### Input Messages (Browser → Agent)

**Terminal Input**
```json
{"type": "input", "data": "ls -la\n"}
```

**Terminal Resize**
```json
{"type": "resize", "cols": 120, "rows": 40}
```

**Ping (Keepalive)**
```json
{"type": "ping"}
```

**Close Request**
```json
{"type": "close"}
```

**Manual PTY Connect**
```json
{"type": "connect_pty", "container": "runtime-001", "cols": 80, "rows": 24}
```

### Output Messages (Agent → Browser)

**Terminal Output**
```json
{"type": "output", "data": "total 42\ndrwxr-xr-x ..."}
```

**Ready (Channel Open)**
```json
{"type": "ready"}
```

**Pong (Keepalive Response)**
```json
{"type": "pong"}
```

**PTY Connected**
```json
{"type": "pty_connected", "container": "runtime-001"}
```

**PTY Disconnected**
```json
{"type": "pty_disconnected"}
```

**Error**
```json
{"type": "error", "message": "Error description"}
```

---

## Usage

### Initialization

The WebRTC controller is automatically initialized when the agent connects to the cloud:

```python
# In controllers/__init__.py
from .webrtc_controller import init, start, stop

async def main_websocket_task(server_url):
    client = await get_websocket_client()

    # Initialize controllers
    init_websocket_controller(client)
    init_webrtc_controller(client)  # Registers signaling handlers

    # Start background tasks
    await start_webrtc_controller()  # Starts session cleanup task

    try:
        await client.connect(f"https://{server_url}")
        await client.wait()
    finally:
        await stop_webrtc_controller()  # Cleanup
```

### Session States

```python
class SessionState(Enum):
    CREATED = "created"           # Session created, waiting for offer
    CONNECTING = "connecting"     # Offer received, establishing connection
    CONNECTED = "connected"       # Data channel open, PTY connected
    DISCONNECTED = "disconnected" # Connection lost
    CLOSED = "closed"             # Session closed
```

### Session Timeout

Sessions are automatically closed after 5 minutes of inactivity. The cleanup task runs every 60 seconds.

```python
SESSION_TIMEOUT_SECONDS = 300  # 5 minutes
CLEANUP_INTERVAL_SECONDS = 60  # 1 minute
```

---

## Testing

### Run Integration Tests

```bash
cd /Users/daniel/src/orchestrator-agent
python3 -c "
import sys
sys.path.insert(0, 'src')
# ... test code ...
"
```

### Test Components

1. **Session Manager** - Create, state transitions, cleanup
2. **Offer/Answer Flow** - SDP exchange via aiortc
3. **Terminal Protocol** - JSON message encoding/decoding
4. **PTY Bridge** - Docker exec integration
5. **End-to-End** - Full flow simulation

### Manual Testing

1. Start the orchestrator agent
2. Create a runtime container
3. Connect from browser with WebRTC client
4. Send terminal commands via data channel

---

## Browser Client Example

```javascript
// Create peer connection
const pc = new RTCPeerConnection();

// Create data channel for terminal
const channel = pc.createDataChannel('terminal');

channel.onopen = () => {
    console.log('Terminal channel open');
};

channel.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'output') {
        terminal.write(msg.data);  // xterm.js
    } else if (msg.type === 'ready') {
        console.log('Agent ready');
    }
};

// Create offer
const offer = await pc.createOffer();
await pc.setLocalDescription(offer);

// Send offer via signaling server (Socket.IO)
socket.emit('webrtc:offer', {
    session_id: 'unique-id',
    device_id: 'runtime-001',
    sdp: pc.localDescription.sdp,
    sdp_type: 'offer'
});

// Receive answer
socket.on('webrtc:offer', (response) => {
    if (response.status === 'success') {
        pc.setRemoteDescription({
            type: response.sdp_type,
            sdp: response.sdp
        });
    }
});

// Handle ICE candidates
pc.onicecandidate = (event) => {
    if (event.candidate) {
        socket.emit('webrtc:ice', {
            session_id: 'unique-id',
            candidate: event.candidate.candidate,
            sdp_mid: event.candidate.sdpMid,
            sdp_mline_index: event.candidate.sdpMLineIndex
        });
    }
};

// Send terminal input
terminal.onData((data) => {
    channel.send(JSON.stringify({type: 'input', data: data}));
});

// Send terminal resize
terminal.onResize((size) => {
    channel.send(JSON.stringify({
        type: 'resize',
        cols: size.cols,
        rows: size.rows
    }));
});
```

---

## References

- [aiortc Documentation](https://aiortc.readthedocs.io/)
- [Docker SDK for Python](https://docker-py.readthedocs.io/)
- [xterm.js](https://xtermjs.org/)
- [WebRTC API](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API)
