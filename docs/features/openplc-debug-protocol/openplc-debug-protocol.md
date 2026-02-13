# OpenPLC Debug Protocol Reference

Analysis of how OpenPLC-Editor communicates with OpenPLC-Runtime during debug sessions.

## Overview

The debug system uses a **custom binary protocol with Modbus-inspired function codes**, transported over three possible channels. The protocol is **stateless** -- each request/response pair is independent, with no session state beyond the transport connection itself.

## Communication Channels

| Channel | Transport | Port | Framing | Use Case |
|---------|-----------|------|---------|----------|
| **WebSocket** | Socket.IO over HTTPS | 8443 | Hex-encoded text via Socket.IO events | OpenPLC Runtime v4 |
| **Modbus TCP** | Raw TCP | 502 | Standard Modbus TCP ADU (7-byte header) | Custom boards |
| **Modbus RTU** | Serial | N/A | Modbus RTU with CRC16-CCITT | Serial boards |

### WebSocket Channel Detail

For the WebSocket channel, binary commands are **hex-encoded as uppercase text with space separators** and exchanged via Socket.IO events:

- Editor sends: `socket.emit('debug_command', {command: "44 00 03 00 00 00 05 00 0A"})`
- Runtime replies: `socket.emit('debug_response', {success: true, data: "44 7E 00 0A ..."})`

Inside the runtime, the Python webserver bridges to the C core via a **Unix domain socket** at `/run/runtime/plc_runtime.socket`, using line-delimited text with a `DEBUG:` prefix:

```
->  DEBUG:44 00 03 00 00 00 05 00 0A\n
<-  DEBUG:44 7E 00 0A 00 00 00 FF 00 08 ...\n
```

### Modbus TCP Channel Detail

Standard 7-byte Modbus TCP ADU header wraps each function code:

```
[txn_id (2)] [proto_id=0x0000 (2)] [length (2)] [unit_id=0x00 (1)] [PDU...]
```

## Function Codes

```
0x41  DEBUG_INFO      -- Get number of debug variables
0x42  DEBUG_SET       -- Force/release a variable value
0x43  DEBUG_GET       -- Get variable range (unused by editor)
0x44  DEBUG_GET_LIST  -- Get specific variables by index array
0x45  DEBUG_GET_MD5   -- Get program MD5 + endianness check
```

### Response Status Codes

```
0x7E  SUCCESS
0x81  ERROR_OUT_OF_BOUNDS
0x82  ERROR_OUT_OF_MEMORY
```

## Message Formats (Binary)

**All multi-byte integers in protocol headers are big-endian. Variable data payloads are little-endian.**

### DEBUG_INFO (0x41)

```
Request (1 byte):
  [0x41]

Response (3 bytes):
  [0x41] [count_hi] [count_lo]
```

### DEBUG_SET (0x42)

```
Request (6 + data_len bytes):
  [0x42] [idx_hi] [idx_lo] [force_flag] [len_hi] [len_lo] [value...]
         force_flag: 1=force, 0=release

Response (2 bytes):
  [0x42] [status]
```

### DEBUG_GET (0x43) -- unused by editor

```
Request (5 bytes):
  [0x43] [start_idx_hi] [start_idx_lo] [end_idx_hi] [end_idx_lo]

Response (10 + data_len bytes):
  [0x43] [status] [last_idx_hi] [last_idx_lo]
  [tick_3] [tick_2] [tick_1] [tick_0]
  [data_len_hi] [data_len_lo]
  [variable data...]
```

### DEBUG_GET_LIST (0x44) -- primary polling command

```
Request (3 + 2*N bytes):
  [0x44] [num_hi] [num_lo] [idx0_hi] [idx0_lo] [idx1_hi] [idx1_lo] ...

Response (10 + data_len bytes):
  [0x44] [status] [last_idx_hi] [last_idx_lo]
  [tick_3] [tick_2] [tick_1] [tick_0]    <- 32-bit PLC scan cycle counter
  [data_len_hi] [data_len_lo]
  [variable data...]                      <- concatenated, little-endian, no padding
```

Max indexes per request: 256.

### DEBUG_GET_MD5 (0x45)

```
Request (5 bytes):
  [0x45] [0xDE] [0xAD] [0x00] [0x00]
         |-- endianness check --|  |- pad -|

Response (2 + ~32 bytes):
  [0x45] [status] [MD5 as ASCII string]
```

The runtime compares the received `0xDEAD` value: if it reads as `0xDEAD` the endianness matches; if `0xADDE`, byte order is reversed.

## Variable Data Layout

Variables are packed sequentially in response payloads with **no padding** between them. Size per IEC 61131-3 type:

| IEC Type | Bytes |
|----------|-------|
| BOOL, SINT, USINT, BYTE | 1 |
| INT, UINT, WORD | 2 |
| DINT, UDINT, DWORD, REAL | 4 |
| LINT, ULINT, LWORD, LREAL | 8 |
| TIME, DATE, TOD, DT | 8 (4-byte seconds + 4-byte nanoseconds) |
| STRING | 127 (1-byte length + 126 bytes data) |

Type information is **not** in the protocol. It comes from the compiled `debug.c` metadata file.

## Variable Index Resolution

The editor does not discover variable metadata from the protocol. Instead:

1. The editor compiles the PLC project, which generates `debug.c` containing a `debug_vars[]` array
2. The editor parses `debug.c` to extract `{name, type, index}` tuples
3. Variable names are mapped to indices using path conventions:
   - Program vars: `RES0__INSTANCE0.VAR_NAME`
   - FB vars: `RES0__INSTANCE0.TON0.Q`
   - Struct fields: `RES0__INSTANCE0.MY_STRUCT.value.FIELD1`
   - Globals: `CONFIG0__GLOBAL_VAR`
4. The MD5 check ensures the runtime's compiled program matches the editor's debug metadata

## Debug Session Sequence

```
 Editor                                          Runtime
   |                                                |
   |  1. Compile project for debug                  |
   |     (generates debug.c with variable table)    |
   |                                                |
   |  2. Connect (Socket.IO wss://:8443/api/debug)  |
   | ---------------------------------------------> |
   |              {status: "ok"}                     |
   | <--------------------------------------------- |
   |                                                |
   |  3. GET_MD5: "45 DE AD 00 00"                  |
   | ---------------------------------------------> |
   |              "45 7E <md5_string>"               |
   | <--------------------------------------------- |
   |                                                |
   |  4. Compare MD5 with local program.st          |
   |     (if mismatch -> upload program, re-verify) |
   |                                                |
   |  5. Parse debug.c -> build variable index map  |
   |                                                |
   |  -- Polling loop begins (every 50ms) --------  |
   |                                                |
   |  6. GET_LIST: "44 00 03 00 00 00 05 00 0A"     |
   | ---------------------------------------------> |
   |      "44 7E 00 0A 00 00 00 42 00 08 <data>"   |
   | <--------------------------------------------- |
   |                                                |
   |  7. Parse binary data, update variable display |
   |                                                |
   |  ... (repeat step 6 every 50ms) ...            |
   |                                                |
   |  8. User forces variable:                      |
   |     SET: "42 00 05 01 00 02 2A 00"             |
   | ---------------------------------------------> |
   |              "42 7E"                            |
   | <--------------------------------------------- |
   |                                                |
   |  9. User releases force:                       |
   |     SET: "42 00 05 00 00 01 00"                |
   | ---------------------------------------------> |
   |              "42 7E"                            |
   | <--------------------------------------------- |
   |                                                |
   |  10. Disconnect                                |
   | ---------------------------------------------> |
```

## Architecture Diagram

```
+----------------------------------------------------------------------+
|                        OpenPLC Editor                                 |
|                                                                       |
|  +-------------+    IPC     +---------------------+                  |
|  |  Renderer    | --------> |  Main Process        |                  |
|  |  (React UI)  | <-------- |  ipc/main.ts         |                  |
|  |              |           |                     |                  |
|  |  - Polling   |           |  +-----------------+|                  |
|  |    (50ms)    |           |  | WebSocket Client || Socket.IO       |
|  |  - Parsing   |           |  | (ws-debug-      ||-------------+   |
|  |  - Display   |           |  |  client.ts)     ||             |   |
|  +-------------+           |  +-----------------+|             |   |
|                             |  | Modbus TCP Client|| TCP:502     |   |
|                             |  | (modbus-         ||----------+  |   |
|                             |  |  client.ts)      ||          |  |   |
|                             |  +-----------------+|          |  |   |
|                             |  | Modbus RTU Client|| Serial   |  |   |
|                             |  | (modbus-rtu-     ||--------+ |  |   |
|                             |  |  client.ts)      ||        | |  |   |
|                             |  +-----------------+|        | |  |   |
|                             +---------------------+        | |  |   |
+------------------------------------------------------------+-+--+---+
                                                              | |  |
                         +------------------------------------+-+--+---+
                         |        OpenPLC Runtime              | |  |   |
                         |                                     | |  |   |
                         |  +--------------------+             | |  |   |
                         |  |  Python Webserver   |<-----------+ |  |   |
                         |  |  debug_websocket.py | wss://:8443  |  |   |
                         |  +--------+-----------+             |  |   |
                         |           | Unix Socket              |  |   |
                         |           | /run/runtime/            |  |   |
                         |           |  plc_runtime.socket      |  |   |
                         |           v                          |  |   |
                         |  +--------------------+             |  |   |
                         |  |   C Runtime Core    |<-----------+  |   |
                         |  |  unix_socket.c      | (TCP:502)     |   |
                         |  |  debug_handler.c    |<--------------+   |
                         |  |                    | (Serial)           |
                         |  |  process_debug     |                    |
                         |  |  _data() reads/    |                    |
                         |  |  writes debug_vars |                    |
                         |  +--------------------+                    |
                         +--------------------------------------------+
```

## File Inventory

### OpenPLC-Runtime

| File | Role |
|------|------|
| `core/src/plc_app/debug_handler.h` | Debug handler interface, function code constants |
| `core/src/plc_app/debug_handler.c` | Core debug message processing (`process_debug_data`) |
| `core/src/plc_app/unix_socket.h` | Unix socket server interface |
| `core/src/plc_app/unix_socket.c` | Unix socket server, `DEBUG:` prefix parsing, hex encode/decode |
| `core/src/plc_app/utils/utils.c` | `parse_hex_string()`, `bytes_to_hex_string()` |
| `core/src/plc_app/image_tables.h` | Debug function pointers (`ext_get_var_count`, `ext_get_var_size`, etc.) |
| `webserver/debug_websocket.py` | Socket.IO `/api/debug` namespace, JWT auth |
| `webserver/unixclient.py` | Unix socket client (`send_and_receive`) bridging webserver to C core |

### OpenPLC-Editor

| File | Role |
|------|------|
| `src/main/modules/websocket/websocket-debug-client.ts` | Socket.IO WebSocket debug transport |
| `src/main/modules/modbus/modbus-client.ts` | Modbus TCP transport, function code definitions |
| `src/main/modules/modbus/modbus-rtu-client.ts` | Modbus RTU serial transport, CRC16 |
| `src/main/modules/ipc/main.ts` | IPC handlers routing debug commands to correct transport |
| `src/utils/debug-parser.ts` | Parse `debug.c` to extract variable entries |
| `src/utils/debug-variable-finder.ts` | Build debug paths, look up variable indices |
| `src/renderer/utils/debug-tree-builder.ts` | Build hierarchical UI tree for complex types |
| `src/renderer/utils/variable-sizes.ts` | Variable size calculations, binary value parsing |
| `src/renderer/components/_organisms/workspace-activity-bar/default.tsx` | Debugger init, MD5 verification, tree building |
| `src/renderer/screens/workspace-screen.tsx` | 50ms polling loop, value parsing, force/release |

## Key Protocol Characteristics

- **Stateless**: No session tokens or sequence numbers in the debug protocol itself
- **No handshake**: Beyond WebSocket/TCP connection setup, the first command can be sent immediately
- **Byte order split**: Protocol headers are big-endian; variable data payloads are little-endian (verified via `0xDEAD` check in `GET_MD5`)
- **Max frame**: 4096 bytes binary (limits variables per `GET_LIST`)
- **Batch splitting**: Editor starts at 50 variables per batch, halves on `ERROR_OUT_OF_MEMORY`
- **Tick synchronization**: Every `GET_LIST` response includes the PLC scan cycle counter
- **MD5 integrity**: Editor verifies the running program matches its local compiled debug metadata before starting
- **Polling interval**: 50ms in the editor
