# WebRTC Debug Implementation Plan

This document outlines the implementation plan for establishing direct WebRTC connections between openplc-web (browser-based IDE) and orchestrator-agent for real-time PLC debugging. This approach bypasses the current high-latency communication path for debug traffic while maintaining the existing architecture for other operations.

## Table of Contents

1. [Background and Motivation](#background-and-motivation)
2. [Current Architecture](#current-architecture)
3. [Proposed Architecture](#proposed-architecture)
4. [Implementation Overview](#implementation-overview)
5. [Phase 1: MVP Implementation](#phase-1-mvp-implementation)
6. [Phase 2: Future Enhancements](#phase-2-future-enhancements)
7. [Security Considerations](#security-considerations)
8. [Testing Strategy](#testing-strategy)
9. [Appendix](#appendix)

---

## Background and Motivation

### The Problem

The openplc-web IDE needs to implement real-time debugging capabilities similar to the desktop openplc-editor. The debugger works by opening a WebSocket connection with the runtime and polling variable values at high frequency (100-200ms intervals).

The current communication architecture introduces significant latency:

```
openplc-web -> autonomy-edge-vue -> api-service -> orchestrator-agent -> openplc-runtime
```

Each hop adds latency, making real-time debugging impractical. The TLS handshake overhead for each HTTP request further compounds the problem.

### The Solution

Establish a direct peer-to-peer WebRTC DataChannel between the browser (openplc-web) and the orchestrator-agent. This provides:

- Low-latency, bidirectional communication
- DTLS encryption for security
- NAT traversal capabilities
- Persistent connection without repeated TLS handshakes

---

## Current Architecture

### Communication Flow

```
┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│   openplc-web   │────>│  autonomy-edge-vue  │────>│   api-service   │
│    (Browser)    │     │  (Supabase Edge Fn) │     │ (api.getedge.me)│
└─────────────────┘     └─────────────────────┘     └────────┬────────┘
                                                             │
                                                    Socket.IO (mTLS)
                                                             │
                                                             v
┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│ openplc-runtime │<────│  orchestrator-agent │<────│   api-service   │
│  (Docker: 8443) │     │     (Docker)        │     │                 │
└─────────────────┘     └─────────────────────┘     └─────────────────┘
```

### Key Components

**openplc-web** (`Autonomy-Logic/openplc-web`)
- Web-based IEC 61131-3 IDE running in browser
- Embedded in autonomy-edge-vue at `/public/editor-web`
- Communicates via Supabase edge functions
- Uses `runtime-api.ts` for device commands

**autonomy-edge-vue** (`Autonomy-Logic/autonomy-edge-vue`)
- Cloud platform hosting openplc-web
- Provides Supabase edge functions for device communication
- `run-device-command` function validates user access and forwards to api-service

**api-service** (`Autonomy-Logic/api-service`)
- Backend at `api.getedge.me`
- Maintains Socket.IO connections with all orchestrator-agents
- `/agent/command` endpoint forwards commands to agents

**orchestrator-agent** (`Autonomy-Logic/orchestrator-agent`)
- Software bridge on user's machine
- Connects to api-service via mTLS Socket.IO
- Manages Docker containers running openplc-runtime
- Has existing `webrtc_controller` directory (currently empty)

**openplc-runtime** (`Autonomy-Logic/openplc-runtime`)
- PLC runtime in Docker container
- Exposes WebSocket debug interface at `/api/debug` (Socket.IO)
- Uses JWT authentication for debug connections

### Debug Protocol Reference

The openplc-editor desktop application implements debugging via WebSocket:

```typescript
// From openplc-editor: src/main/modules/websocket/websocket-debug-client.ts
const url = `https://${this.host}:${this.port}/api/debug`
this.socket = io(url, {
  transports: ['websocket'],
  auth: { token: this.token },
  rejectUnauthorized: false,
  reconnection: false,
  timeout: 5000,
})
```

Debug commands use hex-encoded binary format:
- Function code `0x41`: Get variables list
- Function code `0x44`: Read variables
- Function code `0x45`: Write variable

---

## Proposed Architecture

### WebRTC Data Path

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SIGNALING (one-time setup)                  │
│  Browser -> Supabase (validates access) -> api-service -> Agent     │
│           (SDP offer/answer, ICE candidates)                        │
└─────────────────────────────────────────────────────────────────────┘
                                    |
                                    v
┌─────────────────────────────────────────────────────────────────────┐
│                    DATA PATH (real-time debugging)                  │
│  Browser <──── WebRTC DataChannel (DTLS encrypted) ────> Agent      │
│                        (via STUN/TURN)                     |        │
│                                                      Socket.IO      │
│                                                            |        │
│                                                            v        │
│                                                    openplc-runtime  │
│                                                      /api/debug     │
└─────────────────────────────────────────────────────────────────────┘
```

### Design Decisions

1. **WebRTC peer is orchestrator-agent, not runtime**
   - Agent already manages runtime containers
   - Avoids adding WebRTC to runtime image
   - Single NAT traversal point per host
   - Agent can handle multiple runtime debug sessions

2. **Signaling via existing infrastructure**
   - Use api-service Socket.IO channel for SDP/ICE exchange
   - Supabase edge functions validate user access
   - No new endpoints needed in api-service

3. **Agent as debug relay**
   - Agent terminates WebRTC from browser
   - Agent maintains Socket.IO connection to runtime's `/api/debug`
   - Debug commands forwarded transparently

---

## Implementation Overview

### Repository Changes Summary

| Repository | Changes Required | Complexity |
|------------|-----------------|------------|
| orchestrator-agent | WebRTC controller, runtime debug client, new topics | High |
| autonomy-edge-vue | New Supabase edge functions for signaling | Medium |
| openplc-web | WebRTC debug client service | Medium |
| api-service | None (existing `/agent/command` suffices) | None |
| openplc-runtime | None (existing `/api/debug` suffices) | None |

---

## Phase 1: MVP Implementation

### 1.1 orchestrator-agent Changes

#### 1.1.1 Dependencies

Add to `requirements.txt`:
```
aiortc>=1.6.0
python-socketio[asyncio_client]>=5.0.0
```

#### 1.1.2 WebRTC Controller Implementation

Create `src/controllers/webrtc_controller/__init__.py`:

```python
"""
WebRTC Controller for Debug Sessions

Manages WebRTC peer connections for real-time debugging between
browser (openplc-web) and runtime containers.
"""

import asyncio
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from tools.logger import log_info, log_error, log_debug

# Active debug sessions: session_id -> DebugSession
debug_sessions = {}

# ICE servers configuration (STUN only for MVP)
ICE_SERVERS = [
    RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
    RTCIceServer(urls=["stun:stun1.l.google.com:19302"]),
]

class DebugSession:
    """Represents an active WebRTC debug session"""
    
    def __init__(self, session_id: str, device_id: str):
        self.session_id = session_id
        self.device_id = device_id
        self.peer_connection = None
        self.data_channel = None
        self.runtime_client = None
        self.runtime_token = None
        
    async def create_peer_connection(self):
        """Create and configure RTCPeerConnection"""
        config = RTCConfiguration(iceServers=ICE_SERVERS)
        self.peer_connection = RTCPeerConnection(configuration=config)
        
        @self.peer_connection.on("datachannel")
        def on_datachannel(channel):
            self.data_channel = channel
            log_info(f"DataChannel opened for session {self.session_id}")
            
            @channel.on("message")
            async def on_message(message):
                await self._handle_debug_message(message)
                
            @channel.on("close")
            def on_close():
                log_info(f"DataChannel closed for session {self.session_id}")
                asyncio.create_task(self.cleanup())
        
        @self.peer_connection.on("connectionstatechange")
        async def on_connectionstatechange():
            state = self.peer_connection.connectionState
            log_debug(f"Connection state: {state} for session {self.session_id}")
            if state in ["failed", "closed", "disconnected"]:
                await self.cleanup()
                
        return self.peer_connection
    
    async def _handle_debug_message(self, message: str):
        """Handle incoming debug message from browser"""
        try:
            import json
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "init":
                # Initialize runtime connection with provided token
                self.runtime_token = data.get("runtimeToken")
                await self._connect_to_runtime()
                self._send_response({"type": "init_ack", "success": True})
                
            elif msg_type == "debug-command":
                # Forward debug command to runtime
                request_id = data.get("requestId")
                command_hex = data.get("commandHex")
                response = await self._forward_to_runtime(command_hex)
                self._send_response({
                    "type": "debug-response",
                    "requestId": request_id,
                    **response
                })
                
        except Exception as e:
            log_error(f"Error handling debug message: {e}")
            self._send_response({"type": "error", "error": str(e)})
    
    async def _connect_to_runtime(self):
        """Connect to runtime's /api/debug WebSocket"""
        from controllers.webrtc_controller.runtime_debug_client import RuntimeDebugClient
        from use_cases.docker_manager import CLIENTS
        
        instance = CLIENTS.get(self.device_id)
        if not instance:
            raise ValueError(f"Device not found: {self.device_id}")
        
        # Get runtime container's internal IP
        runtime_ip = instance.get("ip", "localhost")
        runtime_port = 8443
        
        self.runtime_client = RuntimeDebugClient(
            host=runtime_ip,
            port=runtime_port,
            token=self.runtime_token
        )
        await self.runtime_client.connect()
        log_info(f"Connected to runtime {self.device_id} for debug session {self.session_id}")
    
    async def _forward_to_runtime(self, command_hex: str) -> dict:
        """Forward debug command to runtime and return response"""
        if not self.runtime_client:
            return {"success": False, "error": "Runtime not connected"}
        
        return await self.runtime_client.send_debug_command(command_hex)
    
    def _send_response(self, data: dict):
        """Send response to browser via DataChannel"""
        if self.data_channel and self.data_channel.readyState == "open":
            import json
            self.data_channel.send(json.dumps(data))
    
    async def cleanup(self):
        """Clean up session resources"""
        log_info(f"Cleaning up debug session {self.session_id}")
        
        if self.runtime_client:
            await self.runtime_client.disconnect()
            self.runtime_client = None
            
        if self.peer_connection:
            await self.peer_connection.close()
            self.peer_connection = None
            
        if self.session_id in debug_sessions:
            del debug_sessions[self.session_id]


async def create_debug_session(session_id: str, device_id: str) -> DebugSession:
    """Create a new debug session"""
    # Check if device is already being debugged
    for existing in debug_sessions.values():
        if existing.device_id == device_id:
            raise ValueError(f"Device {device_id} is already being debugged")
    
    session = DebugSession(session_id, device_id)
    await session.create_peer_connection()
    debug_sessions[session_id] = session
    
    log_info(f"Created debug session {session_id} for device {device_id}")
    return session


async def handle_webrtc_signal(session_id: str, signal_type: str, signal_data: dict) -> dict:
    """Handle WebRTC signaling message"""
    session = debug_sessions.get(session_id)
    
    if signal_type == "offer":
        if not session:
            raise ValueError(f"Session {session_id} not found. Call init first.")
        
        # Set remote description (browser's offer)
        offer = RTCSessionDescription(sdp=signal_data["sdp"], type="offer")
        await session.peer_connection.setRemoteDescription(offer)
        
        # Create and set local description (our answer)
        answer = await session.peer_connection.createAnswer()
        await session.peer_connection.setLocalDescription(answer)
        
        return {
            "type": "answer",
            "sdp": session.peer_connection.localDescription.sdp
        }
        
    elif signal_type == "candidate":
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        from aiortc import RTCIceCandidate
        candidate = RTCIceCandidate(
            sdpMid=signal_data.get("sdpMid"),
            sdpMLineIndex=signal_data.get("sdpMLineIndex"),
            candidate=signal_data.get("candidate")
        )
        await session.peer_connection.addIceCandidate(candidate)
        return {"success": True}
    
    else:
        raise ValueError(f"Unknown signal type: {signal_type}")


def get_ice_candidates(session_id: str) -> list:
    """Get gathered ICE candidates for a session"""
    session = debug_sessions.get(session_id)
    if not session or not session.peer_connection:
        return []
    
    candidates = []
    for transceiver in session.peer_connection.getTransceivers():
        # Note: aiortc handles ICE candidate gathering internally
        pass
    
    return candidates
```

#### 1.1.3 Runtime Debug Client

Create `src/controllers/webrtc_controller/runtime_debug_client.py`:

```python
"""
Runtime Debug Client

Socket.IO client for connecting to openplc-runtime's /api/debug endpoint.
"""

import asyncio
import socketio
from tools.logger import log_info, log_error, log_debug

class RuntimeDebugClient:
    """Client for runtime's WebSocket debug interface"""
    
    def __init__(self, host: str, port: int, token: str):
        self.host = host
        self.port = port
        self.token = token
        self.sio = None
        self.connected = False
        self._pending_responses = {}
        self._response_counter = 0
        
    async def connect(self):
        """Connect to runtime's /api/debug endpoint"""
        self.sio = socketio.AsyncClient(
            ssl_verify=False,  # Runtime uses self-signed certs
            logger=False,
            engineio_logger=False
        )
        
        @self.sio.on("connected", namespace="/api/debug")
        async def on_connected(data):
            if data.get("status") == "ok":
                self.connected = True
                log_info(f"Connected to runtime debug at {self.host}:{self.port}")
            else:
                log_error(f"Runtime debug connection failed: {data}")
                
        @self.sio.on("debug_response", namespace="/api/debug")
        async def on_debug_response(data):
            # Match response to pending request
            response_id = data.get("_response_id")
            if response_id in self._pending_responses:
                future = self._pending_responses.pop(response_id)
                future.set_result(data)
        
        @self.sio.on("disconnect", namespace="/api/debug")
        async def on_disconnect():
            self.connected = False
            log_info(f"Disconnected from runtime debug at {self.host}:{self.port}")
        
        url = f"https://{self.host}:{self.port}"
        await self.sio.connect(
            url,
            namespaces=["/api/debug"],
            auth={"token": self.token},
            transports=["websocket"]
        )
        
        # Wait for connection confirmation
        for _ in range(50):  # 5 second timeout
            if self.connected:
                return
            await asyncio.sleep(0.1)
        
        raise TimeoutError("Timeout waiting for runtime debug connection")
    
    async def send_debug_command(self, command_hex: str, timeout: float = 5.0) -> dict:
        """Send debug command and wait for response"""
        if not self.connected:
            return {"success": False, "error": "Not connected to runtime"}
        
        # Create response future
        self._response_counter += 1
        response_id = self._response_counter
        future = asyncio.get_event_loop().create_future()
        self._pending_responses[response_id] = future
        
        try:
            # Send command with response ID
            await self.sio.emit(
                "debug_command",
                {"command": command_hex, "_response_id": response_id},
                namespace="/api/debug"
            )
            
            # Wait for response
            response = await asyncio.wait_for(future, timeout=timeout)
            return {
                "success": response.get("success", False),
                "dataHex": response.get("data", ""),
                "error": response.get("error")
            }
            
        except asyncio.TimeoutError:
            self._pending_responses.pop(response_id, None)
            return {"success": False, "error": "Timeout waiting for runtime response"}
        except Exception as e:
            self._pending_responses.pop(response_id, None)
            return {"success": False, "error": str(e)}
    
    async def disconnect(self):
        """Disconnect from runtime"""
        if self.sio:
            await self.sio.disconnect()
            self.sio = None
        self.connected = False
```

#### 1.1.4 WebSocket Topic Handlers

Create `src/controllers/websocket_controller/topics/receivers/webrtc_debug_init.py`:

```python
"""
WebRTC Debug Init Topic Handler

Initializes a new WebRTC debug session for a device.
"""

from controllers.websocket_controller.topics import topic
from controllers.webrtc_controller import create_debug_session
from tools.logger import log_info, log_error
from tools.contract_validation import validate_message
import uuid

NAME = "webrtc_debug_init"

MESSAGE_TYPE = {
    "device_id": str,
}

@topic(NAME)
def init(client):
    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    async def callback(message):
        device_id = message.get("device_id")
        correlation_id = message.get("correlation_id")
        
        log_info(f"Received webrtc_debug_init for device {device_id}")
        
        try:
            # Generate session ID
            session_id = str(uuid.uuid4())
            
            # Create debug session
            session = await create_debug_session(session_id, device_id)
            
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "success",
                "session_id": session_id,
            }
            
        except ValueError as e:
            log_error(f"Failed to init debug session: {e}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": str(e),
            }
        except Exception as e:
            log_error(f"Error in webrtc_debug_init: {e}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Internal error: {str(e)}",
            }
```

Create `src/controllers/websocket_controller/topics/receivers/webrtc_debug_signal.py`:

```python
"""
WebRTC Debug Signal Topic Handler

Handles WebRTC signaling (SDP offer/answer, ICE candidates) for debug sessions.
"""

from controllers.websocket_controller.topics import topic
from controllers.webrtc_controller import handle_webrtc_signal
from tools.logger import log_info, log_error, log_debug
from tools.contract_validation import validate_message

NAME = "webrtc_debug_signal"

MESSAGE_TYPE = {
    "session_id": str,
    "signal_type": str,  # "offer", "answer", "candidate"
    "signal_data": dict,
}

@topic(NAME)
def init(client):
    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    async def callback(message):
        session_id = message.get("session_id")
        signal_type = message.get("signal_type")
        signal_data = message.get("signal_data")
        correlation_id = message.get("correlation_id")
        
        log_debug(f"Received webrtc_debug_signal: {signal_type} for session {session_id}")
        
        try:
            result = await handle_webrtc_signal(session_id, signal_type, signal_data)
            
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "success",
                "signal_response": result,
            }
            
        except ValueError as e:
            log_error(f"Signal error: {e}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": str(e),
            }
        except Exception as e:
            log_error(f"Error in webrtc_debug_signal: {e}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Internal error: {str(e)}",
            }
```

#### 1.1.5 Register New Topics

Update `src/controllers/websocket_controller/topics/receivers/__init__.py` to include:

```python
from . import webrtc_debug_init
from . import webrtc_debug_signal
```

### 1.2 autonomy-edge-vue Changes

#### 1.2.1 New Supabase Edge Function: start-device-debug-webrtc

Create `supabase/functions/start-device-debug-webrtc/index.ts`:

```typescript
import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.55.0";

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
};

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    const authHeader = req.headers.get('authorization');
    if (!authHeader) {
      return new Response(
        JSON.stringify({ error: 'Missing authorization header' }),
        { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL') ?? '',
      Deno.env.get('SUPABASE_ANON_KEY') ?? '',
      { global: { headers: { Authorization: authHeader } } }
    );

    const { data: { user }, error: userError } = await supabase.auth.getUser();
    if (userError || !user) {
      return new Response(
        JSON.stringify({ error: 'Unauthorized' }),
        { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const { agent_id, device_id } = await req.json();

    if (!agent_id || !device_id) {
      return new Response(
        JSON.stringify({ error: 'Missing required fields: agent_id, device_id' }),
        { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    // Validate user has access to this device
    const { data: hasAccess, error: accessError } = await supabase.rpc('user_can_access_device', {
      _device_id: device_id,
      _user_id: user.id
    });

    if (accessError || !hasAccess) {
      return new Response(
        JSON.stringify({ error: 'Unauthorized: You do not have access to this device' }),
        { status: 403, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const edgeApiKey = Deno.env.get('EDGE_API_KEY');
    if (!edgeApiKey) {
      return new Response(
        JSON.stringify({ error: 'Service configuration error' }),
        { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    // Initialize debug session on orchestrator
    const response = await fetch('https://api.getedge.me/agent/command', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${edgeApiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        agent_id,
        topic: 'webrtc_debug_init',
        command: { device_id },
      }),
    });

    const responseData = await response.json();

    if (responseData.response?.status !== 'success') {
      return new Response(
        JSON.stringify({ error: responseData.response?.error || 'Failed to initialize debug session' }),
        { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    return new Response(
      JSON.stringify({
        session_id: responseData.response.session_id,
        ice_servers: [
          { urls: 'stun:stun.l.google.com:19302' },
          { urls: 'stun:stun1.l.google.com:19302' },
        ],
      }),
      { status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );

  } catch (error: any) {
    return new Response(
      JSON.stringify({ error: error.message }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }
});
```

#### 1.2.2 New Supabase Edge Function: signal-device-debug

Create `supabase/functions/signal-device-debug/index.ts`:

```typescript
import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.55.0";

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
};

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    const authHeader = req.headers.get('authorization');
    if (!authHeader) {
      return new Response(
        JSON.stringify({ error: 'Missing authorization header' }),
        { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL') ?? '',
      Deno.env.get('SUPABASE_ANON_KEY') ?? '',
      { global: { headers: { Authorization: authHeader } } }
    );

    const { data: { user }, error: userError } = await supabase.auth.getUser();
    if (userError || !user) {
      return new Response(
        JSON.stringify({ error: 'Unauthorized' }),
        { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const { agent_id, device_id, session_id, signal_type, signal_data } = await req.json();

    if (!agent_id || !device_id || !session_id || !signal_type || !signal_data) {
      return new Response(
        JSON.stringify({ error: 'Missing required fields' }),
        { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    // Validate user has access to this device
    const { data: hasAccess, error: accessError } = await supabase.rpc('user_can_access_device', {
      _device_id: device_id,
      _user_id: user.id
    });

    if (accessError || !hasAccess) {
      return new Response(
        JSON.stringify({ error: 'Unauthorized: You do not have access to this device' }),
        { status: 403, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const edgeApiKey = Deno.env.get('EDGE_API_KEY');
    if (!edgeApiKey) {
      return new Response(
        JSON.stringify({ error: 'Service configuration error' }),
        { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    // Forward signal to orchestrator
    const response = await fetch('https://api.getedge.me/agent/command', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${edgeApiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        agent_id,
        topic: 'webrtc_debug_signal',
        command: { session_id, signal_type, signal_data },
      }),
    });

    const responseData = await response.json();

    return new Response(
      JSON.stringify(responseData.response || responseData),
      { status: response.status, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );

  } catch (error: any) {
    return new Response(
      JSON.stringify({ error: error.message }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }
});
```

### 1.3 openplc-web Changes

#### 1.3.1 WebRTC Debug Client Service

Create `src/services/debug/webrtc-debug-client.ts`:

```typescript
/**
 * WebRTC Debug Client
 * 
 * Establishes WebRTC DataChannel connection to orchestrator-agent
 * for real-time PLC debugging.
 */

interface WebRTCDebugClientOptions {
  agentId: string
  deviceId: string
  runtimeToken: string
  bearerToken: string
  onConnected?: () => void
  onDisconnected?: () => void
  onError?: (error: Error) => void
}

interface DebugResponse {
  success: boolean
  dataHex?: string
  error?: string
}

export class WebRTCDebugClient {
  private agentId: string
  private deviceId: string
  private runtimeToken: string
  private bearerToken: string
  private sessionId: string | null = null
  private peerConnection: RTCPeerConnection | null = null
  private dataChannel: RTCDataChannel | null = null
  private pendingRequests: Map<number, {
    resolve: (value: DebugResponse) => void
    reject: (error: Error) => void
  }> = new Map()
  private requestCounter = 0
  private connected = false
  
  private onConnected?: () => void
  private onDisconnected?: () => void
  private onError?: (error: Error) => void

  constructor(options: WebRTCDebugClientOptions) {
    this.agentId = options.agentId
    this.deviceId = options.deviceId
    this.runtimeToken = options.runtimeToken
    this.bearerToken = options.bearerToken
    this.onConnected = options.onConnected
    this.onDisconnected = options.onDisconnected
    this.onError = options.onError
  }

  async connect(): Promise<void> {
    try {
      // Step 1: Initialize debug session
      const initResponse = await this.callEdgeFunction('start-device-debug-webrtc', {
        agent_id: this.agentId,
        device_id: this.deviceId,
      })

      if (!initResponse.session_id) {
        throw new Error(initResponse.error || 'Failed to initialize debug session')
      }

      this.sessionId = initResponse.session_id
      const iceServers = initResponse.ice_servers || []

      // Step 2: Create peer connection
      this.peerConnection = new RTCPeerConnection({ iceServers })

      // Step 3: Create data channel
      this.dataChannel = this.peerConnection.createDataChannel('debug', {
        ordered: true,
      })

      this.setupDataChannelHandlers()
      this.setupPeerConnectionHandlers()

      // Step 4: Create and send offer
      const offer = await this.peerConnection.createOffer()
      await this.peerConnection.setLocalDescription(offer)

      // Wait for ICE gathering to complete
      await this.waitForIceGathering()

      // Step 5: Send offer to agent via signaling
      const signalResponse = await this.callEdgeFunction('signal-device-debug', {
        agent_id: this.agentId,
        device_id: this.deviceId,
        session_id: this.sessionId,
        signal_type: 'offer',
        signal_data: {
          sdp: this.peerConnection.localDescription?.sdp,
          type: 'offer',
        },
      })

      if (signalResponse.status === 'error') {
        throw new Error(signalResponse.error || 'Signaling failed')
      }

      // Step 6: Set remote description (agent's answer)
      const answer = signalResponse.signal_response
      await this.peerConnection.setRemoteDescription(
        new RTCSessionDescription({ type: 'answer', sdp: answer.sdp })
      )

      // Wait for connection
      await this.waitForConnection()

      // Step 7: Initialize runtime connection
      this.sendMessage({
        type: 'init',
        runtimeToken: this.runtimeToken,
      })

    } catch (error) {
      this.onError?.(error as Error)
      throw error
    }
  }

  async sendDebugCommand(commandHex: string): Promise<DebugResponse> {
    if (!this.connected || !this.dataChannel) {
      return { success: false, error: 'Not connected' }
    }

    return new Promise((resolve, reject) => {
      const requestId = ++this.requestCounter
      this.pendingRequests.set(requestId, { resolve, reject })

      this.sendMessage({
        type: 'debug-command',
        requestId,
        commandHex,
      })

      // Timeout after 5 seconds
      setTimeout(() => {
        if (this.pendingRequests.has(requestId)) {
          this.pendingRequests.delete(requestId)
          resolve({ success: false, error: 'Request timeout' })
        }
      }, 5000)
    })
  }

  async disconnect(): Promise<void> {
    this.connected = false

    if (this.dataChannel) {
      this.dataChannel.close()
      this.dataChannel = null
    }

    if (this.peerConnection) {
      this.peerConnection.close()
      this.peerConnection = null
    }

    this.sessionId = null
    this.pendingRequests.clear()
  }

  isConnected(): boolean {
    return this.connected
  }

  private setupDataChannelHandlers(): void {
    if (!this.dataChannel) return

    this.dataChannel.onopen = () => {
      this.connected = true
      this.onConnected?.()
    }

    this.dataChannel.onclose = () => {
      this.connected = false
      this.onDisconnected?.()
    }

    this.dataChannel.onerror = (event) => {
      this.onError?.(new Error('DataChannel error'))
    }

    this.dataChannel.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        this.handleMessage(data)
      } catch (error) {
        console.error('Failed to parse message:', error)
      }
    }
  }

  private setupPeerConnectionHandlers(): void {
    if (!this.peerConnection) return

    this.peerConnection.onicecandidate = async (event) => {
      if (event.candidate && this.sessionId) {
        // Send ICE candidate to agent
        await this.callEdgeFunction('signal-device-debug', {
          agent_id: this.agentId,
          device_id: this.deviceId,
          session_id: this.sessionId,
          signal_type: 'candidate',
          signal_data: {
            candidate: event.candidate.candidate,
            sdpMid: event.candidate.sdpMid,
            sdpMLineIndex: event.candidate.sdpMLineIndex,
          },
        }).catch(console.error)
      }
    }

    this.peerConnection.onconnectionstatechange = () => {
      const state = this.peerConnection?.connectionState
      if (state === 'failed' || state === 'disconnected' || state === 'closed') {
        this.connected = false
        this.onDisconnected?.()
      }
    }
  }

  private handleMessage(data: any): void {
    if (data.type === 'debug-response') {
      const pending = this.pendingRequests.get(data.requestId)
      if (pending) {
        this.pendingRequests.delete(data.requestId)
        pending.resolve({
          success: data.success,
          dataHex: data.dataHex,
          error: data.error,
        })
      }
    } else if (data.type === 'init_ack') {
      console.log('Runtime connection initialized')
    } else if (data.type === 'error') {
      this.onError?.(new Error(data.error))
    }
  }

  private sendMessage(data: any): void {
    if (this.dataChannel?.readyState === 'open') {
      this.dataChannel.send(JSON.stringify(data))
    }
  }

  private async callEdgeFunction(name: string, body: any): Promise<any> {
    const baseUrl = import.meta.env.VITE_SUPABASE_URL
    const response = await fetch(`${baseUrl}/functions/v1/${name}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.bearerToken}`,
      },
      body: JSON.stringify(body),
    })
    return response.json()
  }

  private waitForIceGathering(): Promise<void> {
    return new Promise((resolve) => {
      if (this.peerConnection?.iceGatheringState === 'complete') {
        resolve()
        return
      }

      const checkState = () => {
        if (this.peerConnection?.iceGatheringState === 'complete') {
          this.peerConnection.removeEventListener('icegatheringstatechange', checkState)
          resolve()
        }
      }

      this.peerConnection?.addEventListener('icegatheringstatechange', checkState)

      // Timeout after 10 seconds
      setTimeout(resolve, 10000)
    })
  }

  private waitForConnection(): Promise<void> {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('Connection timeout'))
      }, 30000)

      const checkState = () => {
        const state = this.peerConnection?.connectionState
        if (state === 'connected') {
          clearTimeout(timeout)
          this.peerConnection?.removeEventListener('connectionstatechange', checkState)
          resolve()
        } else if (state === 'failed') {
          clearTimeout(timeout)
          this.peerConnection?.removeEventListener('connectionstatechange', checkState)
          reject(new Error('Connection failed'))
        }
      }

      this.peerConnection?.addEventListener('connectionstatechange', checkState)
      checkState()
    })
  }
}
```

#### 1.3.2 Integration with Existing Debug Infrastructure

The `WebRTCDebugClient` should be integrated with the existing debug infrastructure in openplc-web. The debug UI components and variable polling logic can be ported from openplc-editor, replacing the direct Socket.IO connection with WebRTC DataChannel calls.

Key integration points:
- `src/services/api/runtime-api.ts` - Add WebRTC debug client factory
- Debug panel components - Port from openplc-editor
- Variable polling service - Use `sendDebugCommand` instead of Socket.IO

---

## Phase 2: Future Enhancements

### 2.1 TURN Server Integration

For reliable connectivity in restrictive network environments, deploy a TURN server.

#### 2.1.1 TURN Server Setup (coturn on AWS EC2)

Install coturn on the same EC2 instance as api-service:

```bash
sudo apt-get update
sudo apt-get install coturn
```

Configure `/etc/turnserver.conf`:

```ini
# Network settings
listening-port=3478
tls-listening-port=5349
listening-ip=0.0.0.0
external-ip=<EC2_PUBLIC_IP>

# Authentication
use-auth-secret
static-auth-secret=<SHARED_SECRET>
realm=getedge.me

# Security
no-multicast-peers
no-cli
no-loopback-peers

# Logging
log-file=/var/log/turnserver.log
verbose
```

#### 2.1.2 TURN Credential Generation

Implement TURN REST API credential generation in Supabase edge functions:

```typescript
function generateTurnCredentials(username: string, sharedSecret: string, ttl: number = 86400) {
  const timestamp = Math.floor(Date.now() / 1000) + ttl
  const turnUsername = `${timestamp}:${username}`
  
  const hmac = crypto.createHmac('sha1', sharedSecret)
  hmac.update(turnUsername)
  const turnPassword = hmac.digest('base64')
  
  return {
    username: turnUsername,
    credential: turnPassword,
    ttl,
  }
}
```

Return TURN credentials in `start-device-debug-webrtc` response:

```typescript
const turnCreds = generateTurnCredentials(user.id, TURN_SECRET)

return {
  session_id: responseData.response.session_id,
  ice_servers: [
    { urls: 'stun:stun.l.google.com:19302' },
    { 
      urls: 'turn:api.getedge.me:3478',
      username: turnCreds.username,
      credential: turnCreds.credential,
    },
  ],
}
```

#### 2.1.3 Security Considerations for TURN

- Use short-lived credentials (24 hours max)
- Rate-limit allocations per user
- Monitor bandwidth usage
- Configure security groups to only expose TURN ports (3478, 5349)

### 2.2 Netmon Integration for Improved Connectivity

Use netmon's host network visibility to optimize ICE candidate gathering for same-LAN scenarios.

#### 2.2.1 Query Host Interfaces from Netmon

Add a new message type to netmon protocol:

```python
# In autonomy-netmon.py
@self.sio.on("get_host_interfaces")
async def get_host_interfaces():
    interfaces = self.discover_all_interfaces()
    return {"interfaces": interfaces}
```

#### 2.2.2 Use Host IPs for Local Candidates

In the WebRTC controller, query netmon for host interfaces and use them to improve candidate selection for local network scenarios:

```python
async def get_host_candidates():
    """Get host IP candidates from netmon for same-LAN optimization"""
    from tools.interface_cache import INTERFACE_CACHE
    
    candidates = []
    for iface_name, iface_data in INTERFACE_CACHE.items():
        for addr in iface_data.get("addresses", []):
            ip = addr.get("address")
            if ip and not ip.startswith("172.") and not ip.startswith("127."):
                candidates.append(ip)
    
    return candidates
```

Note: This optimization requires additional Docker networking configuration (port mappings) to be effective for inbound connections.

### 2.3 Debug Session Token (session_id) Security Enhancement

Add explicit session token validation for defense-in-depth security.

#### 2.3.1 Session Token Generation

```python
import secrets
import hashlib
import time

def generate_session_token(session_id: str, device_id: str, user_id: str) -> dict:
    """Generate a secure session token"""
    timestamp = int(time.time())
    expiry = timestamp + 3600  # 1 hour
    
    secret = secrets.token_hex(32)
    token_data = f"{session_id}:{device_id}:{user_id}:{expiry}"
    signature = hashlib.sha256(f"{token_data}:{secret}".encode()).hexdigest()
    
    return {
        "session_id": session_id,
        "expiry": expiry,
        "signature": signature,
        "secret": secret,  # Store server-side only
    }
```

#### 2.3.2 Token Validation in Agent

```python
def validate_session_token(session_id: str, provided_signature: str, stored_secret: str) -> bool:
    """Validate session token from browser"""
    session = debug_sessions.get(session_id)
    if not session:
        return False
    
    # Verify signature matches
    expected_data = f"{session_id}:{session.device_id}:{session.user_id}:{session.expiry}"
    expected_signature = hashlib.sha256(f"{expected_data}:{stored_secret}".encode()).hexdigest()
    
    return secrets.compare_digest(provided_signature, expected_signature)
```

### 2.4 Multiple Concurrent Debuggers per Device

If needed in the future, support multiple browser tabs debugging the same device.

#### 2.4.1 Architecture Changes

- Remove single-debugger-per-device restriction
- Each debug session gets its own runtime Socket.IO connection
- Implement session isolation to prevent interference

#### 2.4.2 Considerations

- Runtime may need to handle multiple debug connections
- Consider read-only vs read-write debug modes
- Implement session priority/ownership model

---

## Security Considerations

### Authentication Chain

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. Browser → Supabase: JWT authentication                           │
│    - User identity verified                                         │
│    - RLS policies enforced                                          │
│    - user_can_access_device() validates device access               │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 2. Supabase → api-service: EDGE_API_KEY                            │
│    - Server-side secret, never exposed to browser                   │
│    - Authenticates edge function to backend                         │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 3. api-service → orchestrator-agent: mTLS                          │
│    - Mutual TLS with client certificates                            │
│    - Agent identity verified by certificate CN                      │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 4. WebRTC DataChannel: DTLS encryption                             │
│    - End-to-end encryption between browser and agent                │
│    - SDP/ICE only exchanged through authenticated signaling path    │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 5. Agent → Runtime: Runtime JWT                                     │
│    - Browser provides runtime token via DataChannel                 │
│    - Agent uses token for /api/debug authentication                 │
│    - Agent treats token as opaque (never logs or parses)            │
└─────────────────────────────────────────────────────────────────────┘
```

### Security Properties

1. **User isolation**: User A cannot debug User B's devices because Supabase validates device access
2. **Agent isolation**: Signaling only reaches agents through authenticated api-service channel
3. **Data confidentiality**: WebRTC DataChannel is DTLS encrypted; TURN server only sees encrypted packets
4. **Runtime protection**: Runtime JWT required for debug access; agent doesn't store credentials

### Threat Mitigations

| Threat | Mitigation |
|--------|------------|
| Unauthorized device access | Supabase RLS + user_can_access_device() |
| SDP/ICE interception | Signaling through authenticated HTTPS path |
| Direct agent connection | Agent only accepts sessions initiated via api-service |
| Runtime credential theft | Agent treats JWT as opaque, never logs |
| TURN abuse | Per-session credentials, rate limiting |

---

## Testing Strategy

### Unit Tests

1. **orchestrator-agent**
   - WebRTC controller session management
   - Runtime debug client message handling
   - Topic handler validation

2. **openplc-web**
   - WebRTC debug client connection flow
   - Message serialization/deserialization
   - Error handling

### Integration Tests

1. **Signaling flow**
   - Edge function → api-service → agent round-trip
   - SDP offer/answer exchange
   - ICE candidate trickling

2. **Debug session lifecycle**
   - Session creation
   - Runtime connection
   - Command forwarding
   - Session cleanup

### End-to-End Tests

1. **Happy path**
   - Browser connects to agent via WebRTC
   - Debug commands forwarded to runtime
   - Variable values returned correctly

2. **Error scenarios**
   - Network disconnection recovery
   - Runtime unavailable
   - Invalid credentials

3. **NAT traversal**
   - Test with various NAT types
   - Verify STUN candidate gathering
   - Test TURN fallback (Phase 2)

---

## Appendix

### A. Debug Protocol Reference

The debug protocol uses hex-encoded binary commands:

| Function Code | Name | Description |
|--------------|------|-------------|
| 0x41 | GET_LIST | Get list of debuggable variables |
| 0x44 | READ_VARS | Read variable values |
| 0x45 | WRITE_VAR | Write single variable value |

Example command format:
```
"45 DE AD 00 00"
 │  └──────────── Payload (variable-specific)
 └─────────────── Function code
```

### B. ICE Server Configuration

Default STUN servers for MVP:
```javascript
[
  { urls: 'stun:stun.l.google.com:19302' },
  { urls: 'stun:stun1.l.google.com:19302' },
]
```

With TURN (Phase 2):
```javascript
[
  { urls: 'stun:stun.l.google.com:19302' },
  { 
    urls: 'turn:api.getedge.me:3478',
    username: '<timestamp>:<user_id>',
    credential: '<hmac_signature>',
  },
]
```

### C. DataChannel Message Format

Browser → Agent:
```json
{
  "type": "init",
  "runtimeToken": "<jwt>"
}

{
  "type": "debug-command",
  "requestId": 123,
  "commandHex": "45 DE AD 00 00"
}
```

Agent → Browser:
```json
{
  "type": "init_ack",
  "success": true
}

{
  "type": "debug-response",
  "requestId": 123,
  "success": true,
  "dataHex": "7E 61 62 63..."
}

{
  "type": "error",
  "error": "Error message"
}
```

### D. Related Documentation

- [Architecture Overview](./architecture.md)
- [Cloud Protocol](./cloud-protocol.md)
- [Network Monitor](./network-monitor.md)
- [Security](./security.md)

### E. References

- [WebRTC API (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API)
- [aiortc Documentation](https://aiortc.readthedocs.io/)
- [coturn TURN Server](https://github.com/coturn/coturn)
- [ICE (Interactive Connectivity Establishment)](https://datatracker.ietf.org/doc/html/rfc8445)
