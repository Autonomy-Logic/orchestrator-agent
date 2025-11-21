# Cloud Protocol

## Transport

- **Protocol**: Socket.IO over HTTPS/WebSocket
- **Server**: `api.getedge.me`
- **Authentication**: Mutual TLS (mTLS)
- **Reconnection**: Automatic with exponential backoff (1-5 seconds)

## WebSocket Topics

The agent handles the following command topics from the cloud:

### Fully Implemented Topics

| Topic | Description | Implementation |
|-------|-------------|----------------|
| `connect` | Connection established | Starts heartbeat emitter |
| `disconnect` | Connection closed | Logs disconnection |
| `create_new_runtime` | Create new runtime container | Creates container with MACVLAN and internal networks |
| `delete_device` | Delete runtime container | Removes container and associated networks |
| `delete_orchestrator` | Self-destruct agent | Removes orchestrator container |
| `run_command` | Execute runtime command | Proxies HTTP command to runtime container |
| `get_consumption_device` | Get device metrics | Returns CPU/memory usage for specified period |
| `get_consumption_orchestrator` | Get orchestrator metrics | Returns agent CPU/memory usage for specified period |

**Source:** `src/controllers/websocket_controller/topics/receivers/`

### Placeholder Topics

The following topics are registered but return dummy responses (not yet fully implemented):

- `start_device` - Returns `{"action": "start_device", "success": true}`
- `stop_device` - Returns `{"action": "stop_device", "success": true}`
- `restart_device` - Returns `{"action": "restart_device", "success": true}`

## Heartbeat

The agent emits periodic heartbeat messages to report system health and metrics.

**Interval:** 5 seconds

**Payload:**
```json
{
  "agent_id": "07048933",
  "cpu_usage": 15.2,
  "memory_usage": 2.5,
  "memory_total": 16.0,
  "disk_usage": 45.8,
  "disk_total": 500.0,
  "uptime": 86400,
  "status": "online",
  "timestamp": "2025-11-20T20:30:45.123456"
}
```

**Fields:**
- `agent_id` - Unique orchestrator identifier
- `cpu_usage` - CPU usage percentage (0-100)
- `memory_usage` - Memory usage in GB
- `memory_total` - Total memory in GB
- `disk_usage` - Disk usage in GB
- `disk_total` - Total disk space in GB
- `uptime` - Uptime in seconds
- `status` - Agent status ("online")
- `timestamp` - ISO 8601 timestamp

**Implementation:** `src/controllers/websocket_controller/topics/emitters/heartbeat.py`

## Contract Validation

All incoming messages are validated against predefined contracts before processing.

**Validation Features:**
- Type checking (string, number, boolean, date, list)
- Required field validation
- Nested object validation
- Optional field support

**Base Contracts:**
```python
BASE_MESSAGE = {
    "correlation_id": NumberType,
    "action": StringType,
    "requested_at": DateType
}

BASE_DEVICE = {
    **BASE_MESSAGE,
    "device_id": StringType
}
```

**Implementation:** `src/tools/contract_validation.py`

## Message Flow

### Incoming Commands

1. Cloud sends command message via WebSocket topic
2. Agent receives message and validates against contract
3. If validation fails, agent logs error and sends error response
4. If validation succeeds, agent executes command handler
5. Handler performs requested action (create container, delete device, etc.)
6. Agent sends response back to cloud with correlation_id

### Outgoing Telemetry

1. Heartbeat emitter runs in background loop (5-second interval)
2. Collects system metrics (CPU, memory, disk, uptime)
3. Emits heartbeat message to cloud
4. Cloud updates device status and metrics in database

## Error Handling

The agent handles errors gracefully:
- **Connection errors**: Automatic reconnection with exponential backoff
- **Validation errors**: Logged and reported to cloud with error response
- **Command execution errors**: Caught, logged, and reported to cloud
- **Network errors**: Retried with backoff

## Troubleshooting

For protocol-related issues, see [Troubleshooting - WebSocket Connection Errors](troubleshooting.md#websocket-connection-errors).
