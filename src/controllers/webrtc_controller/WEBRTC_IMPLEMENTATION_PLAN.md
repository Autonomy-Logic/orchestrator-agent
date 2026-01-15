# WebRTC Controller Implementation Plan

This document outlines the investigation and implementation plan for the WebRTC controller that will enable remote terminal access to runtime containers (vPLCs) for debugging purposes.

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Python WebRTC Libraries Comparison](#python-webrtc-libraries-comparison)
4. [Implementation Plan](#implementation-plan)
5. [Use Case Design](#use-case-design)
6. [Security Considerations](#security-considerations)
7. [References](#references)

---

## Overview

### Purpose
Enable browser-based remote terminal access to runtime containers (vPLCs) managed by the orchestrator-agent. This allows developers and operators to debug runtime containers directly from a web interface without SSH access to the host machine.

### Communication Flow
```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────────────┐
│   Web Browser   │◄───────►│  Signaling      │◄───────►│   Orchestrator Agent    │
│   (Client)      │   WS    │  Server (Cloud) │   WS    │   (WebRTC Peer)         │
└────────┬────────┘         └─────────────────┘         └───────────┬─────────────┘
         │                                                          │
         │         WebRTC Data Channel (P2P or relayed)             │
         └──────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  Runtime Container  │
                         │  (docker exec PTY)  │
                         └─────────────────────┘
```

### Key Components
1. **Browser Client**: xterm.js frontend rendering terminal output
2. **Signaling Server**: Separate cloud application handling WebRTC offer/answer exchange
3. **Orchestrator Agent**: WebRTC peer that bridges data channel I/O to container PTY
4. **Runtime Container**: Target container where terminal commands are executed

---

## Architecture

### Integration with Existing Codebase

The WebRTC controller should follow existing patterns:

**Controller Layer** (`src/controllers/webrtc_controller/`)
- Handles WebRTC connection lifecycle (offer, answer, ICE candidates)
- Receives signaling messages via existing Socket.IO connection
- Creates and manages RTCPeerConnection instances

**Use Case Layer** (`src/use_cases/terminal_pty/`)
- Manages PTY sessions on runtime containers via `docker exec`
- Bridges WebRTC data channel to PTY stdin/stdout
- Handles terminal resize (SIGWINCH) commands

### Signaling via Socket.IO

Since the orchestrator already maintains a Socket.IO connection to the cloud, signaling can piggyback on this channel:

```python
# New WebSocket topics needed:
- "webrtc:offer"       # Cloud → Agent: SDP offer from browser
- "webrtc:answer"      # Agent → Cloud: SDP answer to browser
- "webrtc:ice"         # Bidirectional: ICE candidate exchange
- "webrtc:disconnect"  # Either end: Session termination
```

### Data Channel Protocol

The WebRTC data channel will carry JSON messages for terminal I/O:

```json
// Terminal input (browser → agent)
{"type": "input", "data": "ls -la\n"}

// Terminal output (agent → browser)
{"type": "output", "data": "total 42\ndrwxr-xr-x ..."}

// Terminal resize (browser → agent)
{"type": "resize", "cols": 120, "rows": 40}

// Session control
{"type": "ping"}
{"type": "pong"}
{"type": "close"}
```

---

## Python WebRTC Libraries Comparison

### 1. aiortc (Recommended)

**Repository**: https://github.com/aiortc/aiortc
**PyPI**: https://pypi.org/project/aiortc/
**License**: BSD-3-Clause

#### Pros
- **Pure Python**: No C++ compilation required, simple `pip install aiortc`
- **Asyncio Native**: Built on asyncio, perfect for this codebase's async architecture
- **JavaScript-like API**: Familiar RTCPeerConnection, RTCDataChannel interfaces
- **Complete Implementation**: Includes ICE, DTLS, SCTP for data channels
- **Active Maintenance**: Regular updates, good documentation
- **Lightweight**: Minimal dependencies compared to alternatives
- **IoT Friendly**: Designed for server-side and embedded use cases

#### Cons
- **Performance Ceiling**: ~5 Mbps data channel throughput (sufficient for terminal)
- **Message Rate Limit**: Issues above ~10 messages/second with large payloads
- **Single Maintainer**: Primarily maintained by one developer (Jérémy Lainé)
- **Media Focus**: Some features optimized for audio/video, not pure data channels

#### Installation
```bash
pip install aiortc
# System dependencies (Ubuntu):
# apt install libavdevice-dev libavfilter-dev libopus-dev libvpx-dev libsrtp2-dev
```

#### Sample Usage
```python
from aiortc import RTCPeerConnection, RTCSessionDescription

pc = RTCPeerConnection()
channel = pc.createDataChannel("terminal")

@channel.on("message")
async def on_message(message):
    # Handle terminal input
    pass
```

---

### 2. GStreamer WebRTC (via Python bindings)

**Repository**: https://gitlab.freedesktop.org/gstreamer/gst-plugins-bad
**Documentation**: https://gstreamer.freedesktop.org/documentation/webrtc/

#### Pros
- **Pipeline Architecture**: Extremely flexible multimedia processing
- **Extensive Codec Support**: Wide range of audio/video codecs via plugins
- **High Performance**: Native C implementation, very efficient
- **Enterprise Grade**: Used in production multimedia applications
- **Rust/C#/Python bindings**: Multiple language options

#### Cons
- **Heavy Dependency**: Large system library, complex installation
- **No Built-in Signaling**: Must implement ICE/STUN/TURN separately
- **Overkill for Data Channels**: Designed for media pipelines, not terminal I/O
- **Steeper Learning Curve**: Pipeline concepts take time to master
- **Complex Debugging**: GStreamer pipelines can be opaque

#### Installation
```bash
# Ubuntu:
apt install gstreamer1.0-plugins-bad python3-gst-1.0
pip install PyGObject
```

---

### 3. pion/webrtc (Go) + Python Bridge

**Repository**: https://github.com/pion/webrtc

#### Pros
- **Pure Go**: Excellent performance, no system dependencies
- **Data Channel Focused**: Strong support for non-media use cases
- **Very Active Community**: Large contributor base

#### Cons
- **Not Python Native**: Requires Go subprocess or CFFI bridge
- **Architecture Mismatch**: Doesn't integrate with Python asyncio
- **Operational Complexity**: Two runtimes to manage

---

### 4. libdatachannel (via Python bindings)

**Repository**: https://github.com/paullouisageneau/libdatachannel

#### Pros
- **Lightweight C++**: Minimal, data-channel-focused implementation
- **Python Bindings Available**: Via `pylibdatachannel`
- **Fast**: Native performance

#### Cons
- **Less Mature Python Support**: Bindings less documented than aiortc
- **Compilation Required**: Needs C++ toolchain
- **Smaller Community**: Fewer examples and resources

---

### Recommendation Summary

| Library | Data Channels | Ease of Use | Performance | Async Support | Recommendation |
|---------|---------------|-------------|-------------|---------------|----------------|
| **aiortc** | Excellent | High | Good | Native | **Primary Choice** |
| GStreamer | Good | Low | Excellent | Partial | Overkill |
| pion (Go) | Excellent | Medium | Excellent | N/A | Wrong language |
| libdatachannel | Excellent | Medium | Excellent | Partial | Alternative |

**For this project, aiortc is strongly recommended** because:
1. Native asyncio integration matches existing codebase patterns
2. Pure Python installation simplifies container builds
3. Data channel performance (~5 Mbps) far exceeds terminal requirements
4. JavaScript-like API reduces learning curve
5. Well-documented with relevant examples

---

## Implementation Plan

### Phase 1: Foundation

#### Step 1.1: Add aiortc dependency
- Add `aiortc` to `requirements.txt`
- Test installation in Docker container
- Verify system dependencies are met

#### Step 1.2: Create WebRTC controller structure
```
src/controllers/webrtc_controller/
├── __init__.py              # Main entry point, peer connection manager
├── signaling/
│   ├── __init__.py
│   ├── offer_handler.py     # Handle incoming SDP offers
│   ├── answer_emitter.py    # Send SDP answers
│   └── ice_handler.py       # ICE candidate exchange
└── data_channel/
    ├── __init__.py
    └── terminal_channel.py  # Terminal I/O over data channel
```

#### Step 1.3: Implement signaling handlers
- Create Socket.IO topic handlers following existing patterns
- Use `@topic()` and `@validate_message()` decorators
- Define message contracts for WebRTC signaling

### Phase 2: WebRTC Connection Management

#### Step 2.1: Peer connection lifecycle
```python
# Pseudo-code for connection management
class WebRTCSessionManager:
    sessions: Dict[str, RTCPeerConnection] = {}

    async def create_session(self, session_id: str, device_id: str) -> RTCPeerConnection:
        pc = RTCPeerConnection()
        pc.device_id = device_id
        self.sessions[session_id] = pc
        return pc

    async def handle_offer(self, session_id: str, sdp: str):
        pc = self.sessions[session_id]
        await pc.setRemoteDescription(RTCSessionDescription(sdp, "offer"))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return pc.localDescription.sdp
```

#### Step 2.2: ICE candidate handling
- Implement trickle ICE for faster connection establishment
- Handle ICE connection state changes
- Implement reconnection logic for dropped connections

#### Step 2.3: Data channel setup
- Create data channel named "terminal"
- Configure for ordered, reliable delivery (TCP-like semantics)
- Implement message framing protocol

### Phase 3: Terminal Use Case

#### Step 3.1: Create PTY use case structure
```
src/use_cases/terminal_pty/
├── __init__.py
├── create_pty_session.py    # Create PTY on container
├── pty_bridge.py            # Bridge data channel ↔ PTY
└── resize_pty.py            # Handle terminal resize
```

#### Step 3.2: Docker exec integration
```python
# Using Docker SDK to create interactive exec session
import docker

async def create_pty_session(container_name: str, cols: int, rows: int):
    container = CLIENT.containers.get(container_name)
    exec_instance = container.exec_run(
        cmd="/bin/bash",
        stdin=True,
        tty=True,
        environment={"TERM": "xterm-256color", "COLUMNS": str(cols), "ROWS": str(rows)},
        socket=True  # Returns socket for bidirectional I/O
    )
    return exec_instance
```

#### Step 3.3: I/O bridging
- Read from PTY socket, write to data channel
- Read from data channel, write to PTY socket
- Handle backpressure and flow control
- Implement ping/pong keepalive

### Phase 4: Integration & Testing

#### Step 4.1: Controller initialization
- Integrate WebRTC controller into `src/controllers/__init__.py`
- Start WebRTC task alongside WebSocket task
- Handle graceful shutdown

#### Step 4.2: Session cleanup
- Clean up PTY sessions on data channel close
- Clean up peer connections on Socket.IO disconnect
- Implement session timeout for abandoned connections

#### Step 4.3: Manual testing
- Test with browser-based WebRTC client
- Verify signaling flow through cloud server
- Test terminal functionality (vim, htop, etc.)

---

## Use Case Design

### Terminal PTY Use Case

**Location**: `src/use_cases/terminal_pty/`

#### create_pty_session.py
```python
"""
Creates an interactive PTY session on a runtime container.

Input:
    - device_id: Target container identifier
    - cols: Initial terminal width
    - rows: Initial terminal height

Output:
    - session_id: Unique identifier for this PTY session
    - socket: Bidirectional socket for PTY I/O
"""
```

#### pty_bridge.py
```python
"""
Bridges WebRTC data channel to PTY socket.

Responsibilities:
    - Async read from PTY, send to data channel
    - Receive from data channel, write to PTY
    - Handle terminal resize commands
    - Implement flow control
"""
```

### Data Flow Diagram

```
┌──────────────────┐     Data Channel      ┌──────────────────┐
│  Browser/xterm.js│◄─────────────────────►│   PTY Bridge     │
│                  │  {"type":"input",...} │                  │
└──────────────────┘                       └────────┬─────────┘
                                                    │
                                                    │ socket I/O
                                                    ▼
                                           ┌──────────────────┐
                                           │  Docker Exec     │
                                           │  (PTY Session)   │
                                           │                  │
                                           │  /bin/bash       │
                                           └──────────────────┘
```

---

## Security Considerations

### Authentication & Authorization
- Verify session requests via existing mTLS identity
- Validate device_id belongs to requesting user's organization
- Implement session tokens with expiration

### Network Security
- WebRTC connections encrypted via DTLS
- Data channels use SCTP over DTLS
- Consider TURN server for NAT traversal (relay through cloud)

### Container Isolation
- PTY sessions run as non-root user in container
- Consider resource limits on exec sessions (CPU, memory)
- Implement session timeout to prevent zombie processes

### Audit Logging
- Log terminal session start/end
- Consider optional command logging for compliance
- Track session duration and activity

---

## References

### WebRTC Libraries
- [aiortc GitHub](https://github.com/aiortc/aiortc)
- [aiortc Documentation](https://aiortc.readthedocs.io/)
- [aiortc Examples](https://aiortc.readthedocs.io/en/latest/examples.html)

### Terminal Implementations
- [pyxtermjs](https://github.com/cs01/pyxtermjs) - Flask + WebSocket terminal
- [xterm.js](https://xtermjs.org/) - Browser terminal emulator
- [RAWRTC Terminal Demo](https://github.com/rawrtc/rawrtc-terminal-demo) - WebRTC terminal reference

### Docker Integration
- [Docker SDK for Python](https://docker-py.readthedocs.io/)
- [Docker Exec API](https://docs.docker.com/engine/api/v1.41/#operation/ContainerExec)
- [Presidio Terminal Blog](https://www.presidio.com/technical-blog/building-a-browser-based-terminal-using-docker-and-xtermjs/)

### WebRTC Concepts
- [WebRTC for Developers](https://www.webrtc-developers.com/)
- [GStreamer vs WebRTC Comparison](https://stackshare.io/stackups/gstreamer-vs-webrtc)

### Known Limitations
- [aiortc Data Channel Rate Limiting](https://github.com/aiortc/aiortc/issues/462)
- [aiortc Transfer Rates](https://github.com/aiortc/aiortc/issues/36)
