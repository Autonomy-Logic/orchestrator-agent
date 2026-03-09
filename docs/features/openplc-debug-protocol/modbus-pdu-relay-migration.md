# Phase 1: Agent Migration Guide — Modbus PDU Debug Protocol

This document specifies what the agent must change to support the new hybrid debug protocol over WebRTC DataChannel and HTTP fallback.

## Context

The web frontend has been migrated from a custom JSON debug protocol to the same Modbus PDU hex string protocol the editor uses over Socket.io. The agent's role changes from **translator** (JSON-to-Modbus) to **relay** (forward hex strings as-is).

The agent still handles connection lifecycle (JSON control messages). It no longer needs to understand or translate debug data commands — it just relays hex strings between the web frontend and the runtime's Modbus interface.

---

## Protocol Overview

The debug DataChannel (and HTTP fallback) now carries two kinds of messages:

| Category | Format | Direction | Agent role |
|----------|--------|-----------|------------|
| Control plane | JSON `{ type: '...' }` | Both | **Interprets** — manages connections |
| Data plane | Hex string `"44 00 03 ..."` | Both | **Relays** — forwards to/from runtime |

### Discrimination rule

When the agent receives a message on the debug DataChannel:

- **Starts with `{`** → JSON control message → agent interprets it
- **Otherwise** → Modbus PDU hex string → agent relays to runtime

When the agent sends a message to the web frontend on the debug DataChannel:

- Connection lifecycle events → send as JSON
- Modbus responses from the runtime → send as hex string (no wrapping)

---

## Control Messages (JSON) — No change in semantics

These messages keep the same format. The agent interprets them to manage the debug connection lifecycle.

### Web → Agent

```json
{ "type": "debug_start", "device_id": "...", "username": "...", "password": "...", "port": 8443 }
```
Agent establishes a debug connection (Socket.io or direct Modbus TCP) to the runtime at the specified device using the credentials. After connecting, the agent sends `debug_connected` back.

```json
{ "type": "debug_stop" }
```
Agent tears down the debug connection to the runtime.

### Agent → Web

```json
{ "type": "debug_connected" }
```
Sent after the agent successfully establishes a debug connection to the runtime.

```json
{ "type": "debug_disconnected" }
```
Sent when the debug connection to the runtime is lost or closed.

```json
{ "type": "debug_error", "error": "..." }
```
Sent on any error. The `error` string may contain `"ERROR_OUT_OF_MEMORY"` which the frontend handles specially.

```json
{ "type": "debug_ready" }
```
Sent when the debug DataChannel opens (or reopens after reconnection). The frontend uses this to auto-recover active debug sessions.

---

## Data Messages (Hex Strings) — This is what changes

### What the web sends now (BEFORE → AFTER)

| Old JSON format | New hex string format | Modbus FC |
|---|---|---|
| `{ "type": "debug_get_md5" }` | `"45 DE AD 00 00"` | 0x45 |
| `{ "type": "debug_get_list", "indexes": [3, 7, 12] }` | `"44 00 03 00 03 00 07 00 0C"` | 0x44 |
| `{ "type": "debug_set", "index": 5, "force": true, "value": "01" }` | `"42 00 05 01 00 01 01"` | 0x42 |

### What the agent must return now (BEFORE → AFTER)

| Old JSON format | New hex string format |
|---|---|
| `{ "type": "debug_md5_response", "md5": "abc123..." }` | `"45 7E 61 62 63 31 32 33 ..."` (FC + SUCCESS + MD5 bytes) |
| `{ "type": "debug_values_response", "tick": 10, "data": "..." }` | `"44 7E 00 19 00 00 00 0A 00 05 ..."` (FC + SUCCESS + lastIndex + tick + size + data) |
| `{ "type": "debug_set_response", "success": true }` | `"42 7E"` (FC + SUCCESS) |
| `{ "type": "debug_info_response", "variable_count": 25 }` | `"41 7E 00 19"` (FC + SUCCESS + count) |

### Agent relay logic

The agent no longer needs to parse or construct Modbus PDUs. It relays raw hex strings:

```
Web Frontend                    Agent                         Runtime
    │                            │                              │
    │  "44 00 03 00 03 00 07"   │                              │
    │ ──────────────────────────>│                              │
    │  (hex string over          │  socket.emit('debug_command',│
    │   DataChannel)             │    { command: "44 00 03..." })│
    │                            │ ─────────────────────────────>│
    │                            │                              │
    │                            │  socket.on('debug_response', │
    │                            │    { data: "44 7E 00 19..." })│
    │                            │ <─────────────────────────────│
    │  "44 7E 00 19 00 00..."   │                              │
    │ <──────────────────────────│                              │
    │  (hex string over          │                              │
    │   DataChannel)             │                              │
```

This is identical to how the editor's `WebSocketDebugClient` works:
- Editor sends: `socket.emit('debug_command', { command: hexString })`
- Editor receives: `socket.on('debug_response', { data: hexString })`

The agent already speaks this protocol to the runtime. The change is that instead of translating between JSON and hex, it now relays hex strings end-to-end.

---

## WebRTC DataChannel Implementation

### Receiving from web frontend

```python
# Pseudocode for the agent's DataChannel onmessage handler

def on_debug_message(raw_message: str):
    if raw_message.startswith('{'):
        # JSON control message
        msg = json.loads(raw_message)
        if msg['type'] == 'debug_start':
            connect_to_runtime(msg['device_id'], msg['username'], msg['password'], msg['port'])
        elif msg['type'] == 'debug_stop':
            disconnect_from_runtime()
    else:
        # Modbus PDU hex string — relay to runtime
        runtime_socket.emit('debug_command', { 'command': raw_message })
```

### Sending to web frontend

```python
# When runtime sends a Modbus response
def on_runtime_debug_response(response):
    hex_data = response.get('data', '')
    if hex_data:
        # Send hex string as-is over DataChannel (NOT wrapped in JSON)
        debug_datachannel.send(hex_data)

# When connection lifecycle events occur
def on_runtime_connected():
    debug_datachannel.send(json.dumps({ 'type': 'debug_connected' }))

def on_runtime_disconnected():
    debug_datachannel.send(json.dumps({ 'type': 'debug_disconnected' }))

def on_runtime_error(error):
    debug_datachannel.send(json.dumps({ 'type': 'debug_error', 'error': str(error) }))

# When the debug DataChannel opens
def on_debug_channel_open():
    debug_datachannel.send(json.dumps({ 'type': 'debug_ready' }))
```

---

## HTTP Fallback Implementation

When WebRTC is unavailable, debug commands arrive via `POST /orchestrators/run-command` with `api: "debug"`.

### Request format

The web wraps hex strings as `{ command: hexString }` in the HTTP payload, matching the editor's Socket.io emit format:

```json
{
  "agent_id": "...",
  "device_id": "...",
  "method": "POST",
  "api": "debug",
  "data": { "command": "44 00 03 00 03 00 07 00 0C" }
}
```

JSON control messages are sent as-is:

```json
{
  "agent_id": "...",
  "device_id": "...",
  "method": "POST",
  "api": "debug",
  "data": { "type": "debug_start", "device_id": "...", "username": "...", "password": "...", "port": 8443 }
}
```

### Response format

For Modbus hex string commands, return the hex string response:

```json
{
  "status": "success",
  "debug_response": "44 7E 00 19 00 00 00 0A 00 05 01 00 FF 00 01"
}
```

For JSON control messages, return JSON:

```json
{
  "status": "success",
  "debug_response": { "type": "debug_connected" }
}
```

### Discrimination rule (HTTP)

The agent can distinguish request type by checking the `data` payload:
- Has `data.command` (string) → Modbus PDU hex string → relay `data.command` to runtime
- Has `data.type` (string) → JSON control message → interpret

---

## Modbus PDU Reference

For completeness, here are the Modbus PDU formats the runtime speaks. The agent does NOT need to parse these — it relays them as opaque hex strings. This is included for debugging purposes only.

### Function codes

| Code | Name | Direction |
|------|------|-----------|
| 0x41 | DEBUG_INFO | Request/Response |
| 0x42 | DEBUG_SET | Request/Response |
| 0x43 | DEBUG_GET | Request/Response |
| 0x44 | DEBUG_GET_LIST | Request/Response |
| 0x45 | DEBUG_GET_MD5 | Request/Response |

### Response status codes (byte at offset 1)

| Code | Meaning |
|------|---------|
| 0x7E | SUCCESS |
| 0x81 | ERROR_OUT_OF_BOUNDS |
| 0x82 | ERROR_OUT_OF_MEMORY |

### GET_MD5 (FC 0x45)

Request: `45 DE AD 00 00` (5 bytes: FC + endianness marker 0xDEAD + 2 zero bytes)

Response: `45 7E <md5_bytes>` (FC + SUCCESS + UTF-8 MD5 hash string)

### GET_LIST (FC 0x44)

Request: `44 <count_hi> <count_lo> <idx1_hi> <idx1_lo> ...` (FC + index count as BE16 + indexes as BE16 each)

Example for indexes [3, 7, 12]: `44 00 03 00 03 00 07 00 0C`

Response: `44 7E <lastIdx_hi> <lastIdx_lo> <tick_32bit_BE> <size_hi> <size_lo> <data_bytes>`

### SET (FC 0x42)

Request: `42 <idx_hi> <idx_lo> <force_flag> <len_hi> <len_lo> <value_bytes>`

- `force_flag`: 0x01 = force, 0x00 = release
- `value_bytes`: the value to set (length specified by len field)

Response: `42 7E` (FC + SUCCESS) or `42 81` / `42 82` (FC + error code)

---

## Hex String Encoding

Space-separated uppercase hex bytes: `"44 00 03 00 03 00 07 00 0C"`

This matches the editor's `bytesToHexString()` output and the runtime's Socket.io debug protocol.

---

## Migration Checklist

- [ ] Update DataChannel `onmessage` handler to discriminate JSON vs hex strings (starts with `{`)
- [ ] For hex strings: relay to runtime via `socket.emit('debug_command', { command: hexString })` — no parsing
- [ ] For runtime responses: send hex string back over DataChannel as-is (not wrapped in JSON)
- [ ] Keep sending lifecycle events (`debug_connected`, `debug_disconnected`, `debug_error`, `debug_ready`) as JSON
- [ ] Update HTTP fallback handler: detect `data.command` vs `data.type` for request discrimination
- [ ] Return hex string responses as `{ status: 'success', debug_response: hexString }` over HTTP
- [ ] Remove all JSON-to-Modbus translation logic (no more building PDUs from `debug_get_list`/`debug_set`/`debug_get_md5` JSON)
- [ ] Remove all Modbus-to-JSON translation logic (no more parsing PDUs into `debug_values_response`/`debug_md5_response`/`debug_set_response` JSON)
- [ ] Verify `debug_ready` is still sent when the debug DataChannel opens

## What Gets Simpler

The agent no longer needs to:
- Parse `debug_get_md5` JSON → build `[0x45, 0xDE, 0xAD, 0x00, 0x00]` → hex-encode → emit
- Parse `debug_get_list` JSON → build `[0x44, count, ...indexes]` → hex-encode → emit
- Parse `debug_set` JSON → build `[0x42, index, force, len, value]` → hex-encode → emit
- Parse Modbus response hex → extract fields → build `debug_values_response` JSON → send
- Parse Modbus MD5 response hex → extract MD5 string → build `debug_md5_response` JSON → send

Instead, for data plane messages, it does:
- Receive hex string → `socket.emit('debug_command', { command: hexString })`
- Receive `socket.on('debug_response', { data: hexString })` → send hex string

This eliminates a full Modbus PDU builder/parser from the agent codebase.
