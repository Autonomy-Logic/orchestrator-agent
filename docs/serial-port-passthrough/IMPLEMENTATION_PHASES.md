# Serial Port Passthrough - Implementation Phases

This document outlines the implementation phases for adding serial port passthrough support to the orchestrator-agent system.

## Phase Overview

| Phase | Description | Risk Level | Dependencies |
|-------|-------------|------------|--------------|
| 1 | Container Creation Changes | Low | None |
| 2 | Serial Persistence Layer | Low | None |
| 3 | Netmon Device Monitor | Medium | Phase 2 |
| 4 | Device Event Listener | Medium | Phase 2, 3 |
| 5 | Topic Handler Extensions | Low | Phase 1, 2, 4 |
| 6 | Testing & Validation | - | All phases |

---

## Phase 1: Container Creation Changes

**Objective**: Enable containers to accept dynamically created device nodes.

**Risk**: Low - Additive changes only, doesn't affect existing functionality.

### Tasks

#### 1.1 Modify create_runtime_container.py

Add device class permissions to container creation:

```python
# File: src/use_cases/docker_manager/create_runtime_container.py

# In _create_runtime_container_sync(), modify create_kwargs:
create_kwargs = {
    ...
    "cap_add": ["SYS_NICE", "MKNOD"],  # Add MKNOD capability
    "device_cgroup_rules": [
        "c 188:* rmw",  # USB-to-serial (ttyUSB*)
        "c 166:* rmw",  # ACM modems (ttyACM*)
    ],
}
```

#### 1.2 Add serial_configs parameter

Extend function signature to accept serial configurations:

```python
async def create_runtime_container(
    container_name: str,
    vnic_configs: list,
    serial_configs: list = None,  # NEW parameter
    ...
) -> dict:
```

### Files to Modify

- `src/use_cases/docker_manager/create_runtime_container.py`

### Acceptance Criteria

- [ ] Containers created with MKNOD capability
- [ ] Device cgroup rules applied to new containers
- [ ] Existing containers unaffected (backward compatible)
- [ ] Manual `docker exec mknod` works in new containers

---

## Phase 2: Serial Persistence Layer

**Objective**: Create persistence layer for serial port configurations.

**Risk**: Low - New files, follows existing vnic_persistence.py pattern.

### Tasks

#### 2.1 Create serial_persistence.py

```python
# File: src/tools/serial_persistence.py

SERIAL_CONFIG_FILE = "/var/orchestrator/data/serial_configs.json"

def load_serial_configs(container_name: str = None) -> dict:
    """Load serial configurations from persistence."""
    pass

def save_serial_configs(container_name: str, serial_configs: list) -> None:
    """Save serial configurations for a container."""
    pass

def delete_serial_configs(container_name: str) -> None:
    """Delete serial configurations when container is removed."""
    pass

def update_serial_status(container_name: str, port_name: str, status: str, **kwargs) -> None:
    """Update status of a specific serial port."""
    pass
```

#### 2.2 Define serial config schema

```python
# Schema for validation
SERIAL_CONFIG_TYPE = {
    "name": StringType,                      # User-friendly name
    "device_id": StringType,                 # Stable USB device identifier
    "container_path": StringType,            # Path inside container
    "baud_rate": OptionalType(NumberType),   # For documentation
}

# Runtime state (managed internally)
SERIAL_STATE = {
    "status": StringType,           # "connected", "disconnected", "unknown"
    "current_host_path": StringType,# Current /dev/ttyUSBx path
    "major": NumberType,            # Device major number
    "minor": NumberType,            # Device minor number
}
```

#### 2.3 Integrate with container deletion

Update `delete_runtime_container.py` to clean up serial configs:

```python
# In deletion flow
delete_serial_configs(container_name)
```

### Files to Create

- `src/tools/serial_persistence.py`

### Files to Modify

- `src/use_cases/docker_manager/delete_runtime_container.py`
- `src/tools/contract_validation.py` (add SERIAL_CONFIG_TYPE)

### Acceptance Criteria

- [ ] Serial configs persist across agent restarts
- [ ] Configs cleaned up on container deletion
- [ ] Schema validation for serial configs

---

## Phase 3: Netmon Device Monitor

**Objective**: Add USB serial device monitoring to netmon sidecar.

**Risk**: Medium - Modifies existing sidecar, requires testing.

### Tasks

#### 3.1 Add pyudev dependency

```dockerfile
# File: install/Dockerfile.netmon

RUN apk add --no-cache \
    python3 \
    py3-pip \
    ... \
    eudev \
    py3-udev
```

#### 3.2 Create DeviceMonitor class

```python
# File: install/autonomy-netmon.py (new class)

class DeviceMonitor:
    """Monitor USB serial devices using pyudev."""

    def __init__(self, event_callback):
        self.event_callback = event_callback
        self.context = None
        self.monitor = None
        self.running = False

    def start(self):
        """Start monitoring for device events."""
        import pyudev
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem='tty')
        self.running = True
        # Start monitor thread

    def get_current_devices(self) -> list:
        """Enumerate currently connected serial devices."""
        pass

    def _handle_device_event(self, device):
        """Process device add/remove events."""
        pass

    def _build_device_info(self, device) -> dict:
        """Extract device information for event payload."""
        return {
            "path": device.device_node,
            "by_id": self._get_by_id_path(device),
            "major": device.major,
            "minor": device.minor,
            "vendor_id": device.get("ID_VENDOR_ID"),
            "product_id": device.get("ID_MODEL_ID"),
            "serial": device.get("ID_SERIAL_SHORT"),
            "subsystem": device.subsystem,
        }
```

#### 3.3 Integrate with existing event system

```python
# In NetmonServer class

def __init__(self):
    ...
    self.device_monitor = DeviceMonitor(self._send_device_event)

async def _on_client_connect(self, writer):
    # Existing: send network_discovery
    await self._send_network_discovery(writer)

    # NEW: send device_discovery
    await self._send_device_discovery(writer)

def _send_device_event(self, action: str, device_info: dict):
    """Broadcast device event to all connected clients."""
    event = {
        "type": "device_change",
        "data": {
            "action": action,
            "device": device_info,
        }
    }
    self._broadcast_event(event)
```

#### 3.4 Update netmon container privileges

```yaml
# docker-compose.yml or container creation
autonomy-netmon:
  volumes:
    - /var/orchestrator:/var/orchestrator
    - /run/udev:/run/udev:ro
    - /dev:/dev:ro
  # OR for simplicity during development:
  privileged: true
```

### Files to Modify

- `install/autonomy-netmon.py`
- `install/Dockerfile.netmon`
- Container deployment configuration

### Acceptance Criteria

- [ ] device_discovery sent on client connection
- [ ] device_change events sent on hotplug
- [ ] Device info includes stable by_id path
- [ ] Works with USB-to-serial adapters (FTDI, CH340, etc.)

---

## Phase 4: Device Event Listener

**Objective**: Handle device events in orchestrator-agent.

**Risk**: Medium - New component, follows existing NetworkEventListener pattern.

### Tasks

#### 4.1 Extend NetworkEventListener or create DeviceEventListener

Option A: Extend existing NetworkEventListener with device handling
Option B: Create separate DeviceEventListener class

Recommended: Option A (extend existing) for simplicity.

```python
# File: src/tools/network_event_listener.py (extended)

class NetworkEventListener:
    def __init__(self):
        ...
        self.device_cache = {}  # NEW
        self.device_update_callbacks = []  # NEW

    async def _handle_event(self, event_data: dict):
        event_type = event_data.get("type")

        if event_type == "network_discovery":
            await self._handle_network_discovery(event_data)
        elif event_type == "network_change":
            await self._handle_network_change(event_data)
        elif event_type == "dhcp_update":
            await self._handle_dhcp_update(event_data)
        # NEW event types
        elif event_type == "device_discovery":
            await self._handle_device_discovery(event_data)
        elif event_type == "device_change":
            await self._handle_device_change(event_data)
```

#### 4.2 Implement device node creation

```python
# File: src/tools/network_event_listener.py (new methods)

async def _create_device_node(
    self,
    container_name: str,
    host_device: str,
    container_path: str
) -> bool:
    """Create device node inside running container."""

    # Get device numbers
    stat_info = os.stat(host_device)
    major = os.major(stat_info.st_rdev)
    minor = os.minor(stat_info.st_rdev)

    # Remove existing node if present
    await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-u", "root", container_name, "rm", "-f", container_path],
        capture_output=True
    )

    # Create new node
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-u", "root", container_name,
         "mknod", container_path, "c", str(major), str(minor)],
        capture_output=True
    )

    if result.returncode == 0:
        # Set permissions
        await asyncio.to_thread(
            subprocess.run,
            ["docker", "exec", "-u", "root", container_name, "chmod", "666", container_path]
        )
        return True

    return False
```

#### 4.3 Implement startup resync

```python
# File: src/tools/network_event_listener.py (new method)

async def _resync_serial_devices_for_existing_containers(self):
    """Resync serial device nodes after host restart."""

    all_configs = load_serial_configs()

    for container_name, config_data in all_configs.items():
        serial_configs = config_data.get("serial_ports", [])

        for serial_config in serial_configs:
            device_id = serial_config.get("device_id")
            by_id_path = f"/dev/serial/by-id/{device_id}"

            if os.path.exists(by_id_path):
                actual_path = os.path.realpath(by_id_path)

                success = await self._create_device_node(
                    container_name,
                    actual_path,
                    serial_config["container_path"]
                )

                if success:
                    update_serial_status(
                        container_name,
                        serial_config["name"],
                        "connected",
                        current_host_path=actual_path
                    )
            else:
                update_serial_status(
                    container_name,
                    serial_config["name"],
                    "disconnected"
                )
```

#### 4.4 Implement device matching

```python
def _match_device_to_config(self, device_event: dict) -> list:
    """Find containers that need this device."""

    device_by_id = device_event.get("by_id", "")
    matches = []

    all_configs = load_serial_configs()

    for container_name, config_data in all_configs.items():
        for serial_config in config_data.get("serial_ports", []):
            if serial_config["device_id"] in device_by_id:
                matches.append({
                    "container_name": container_name,
                    "serial_config": serial_config,
                })

    return matches
```

### Files to Modify

- `src/tools/network_event_listener.py`

### Acceptance Criteria

- [ ] Device discovery populates device cache
- [ ] Device add event creates device node in correct container
- [ ] Device remove event updates status (doesn't crash container)
- [ ] Startup resync recreates device nodes
- [ ] Callbacks triggered for device status changes

---

## Phase 5: Topic Handler Extensions

**Objective**: Expose serial port functionality via WebSocket API.

**Risk**: Low - Extends existing topic handlers.

### Tasks

#### 5.1 Extend create_new_runtime topic

```python
# File: src/controllers/websocket_controller/topics/receivers/create_new_runtime.py

SERIAL_CONFIG_TYPE = {
    "name": StringType,
    "device_id": StringType,
    "container_path": StringType,
    "baud_rate": OptionalType(NumberType),
}

MESSAGE_TYPE = {
    **BASE_MESSAGE,
    "container_name": StringType,
    "vnic_configs": ListType(VNIC_CONFIG_TYPE),
    "serial_configs": OptionalType(ListType(SERIAL_CONFIG_TYPE)),  # NEW
}

@topic(NAME)
def init(client):
    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    async def callback(message):
        ...
        serial_configs = message.get("serial_configs", [])

        # Validate serial configs
        if serial_configs:
            valid, error = _validate_serial_configs(serial_configs)
            if not valid:
                return {"action": NAME, "status": "error", "message": error}

        # Pass to container creation
        await create_runtime_container(
            container_name,
            vnic_configs,
            serial_configs=serial_configs,
        )
```

#### 5.2 Extend get_device_status topic

```python
# File: src/use_cases/docker_manager/get_device_status.py

def get_device_status_data(device_id: str) -> dict:
    ...

    # Add serial device status
    serial_configs = load_serial_configs(device_id)
    if serial_configs:
        response["serial_devices"] = []
        for config in serial_configs.get("serial_ports", []):
            response["serial_devices"].append({
                "name": config.get("name"),
                "device_id": config.get("device_id"),
                "container_path": config.get("container_path"),
                "status": config.get("status", "unknown"),
                "host_path": config.get("current_host_path"),
            })

    return response
```

#### 5.3 (Optional) Create attach_serial_device topic

```python
# File: src/controllers/websocket_controller/topics/receivers/attach_serial_device.py

NAME = "attach_serial_device"

MESSAGE_TYPE = {
    **BASE_MESSAGE,
    "container_name": StringType,
    "serial_config": SERIAL_CONFIG_TYPE,
}

@topic(NAME)
def init(client):
    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME, add_defaults=True)
    async def callback(message):
        container_name = message.get("container_name")
        serial_config = message.get("serial_config")

        # Attach device to running container
        ...
```

### Files to Modify

- `src/controllers/websocket_controller/topics/receivers/create_new_runtime.py`
- `src/use_cases/docker_manager/get_device_status.py`

### Files to Create (Optional)

- `src/controllers/websocket_controller/topics/receivers/attach_serial_device.py`
- `src/controllers/websocket_controller/topics/receivers/detach_serial_device.py`

### Acceptance Criteria

- [ ] create_new_runtime accepts serial_configs
- [ ] get_device_status returns serial device status
- [ ] (Optional) Runtime attach/detach of serial devices

---

## Phase 6: Testing & Validation

**Objective**: Validate the implementation works correctly.

### Test Scenarios

#### 6.1 Basic Functionality

- [ ] Create container with serial config
- [ ] Verify device node created in container
- [ ] Verify OpenPLC can communicate via serial

#### 6.2 Hot-Plug Testing

- [ ] Plug in USB adapter while container running
- [ ] Verify device node created automatically
- [ ] Unplug USB adapter
- [ ] Verify container keeps running
- [ ] Verify status updates to "disconnected"
- [ ] Plug adapter back in
- [ ] Verify device node recreated
- [ ] Verify communication resumes

#### 6.3 Host Restart Testing

- [ ] Create container with serial config
- [ ] Reboot host
- [ ] Verify container auto-starts
- [ ] Verify device node recreated on startup
- [ ] Verify communication works after reboot

#### 6.4 USB Port Change Testing

- [ ] Create container with serial config
- [ ] Unplug adapter, plug into different USB port
- [ ] Verify device_id (by-id path) is same
- [ ] Verify device node updated with new major:minor
- [ ] Verify communication works

#### 6.5 Multiple Devices Testing

- [ ] Create container with multiple serial configs
- [ ] Verify each device mapped correctly
- [ ] Swap physical devices between USB ports
- [ ] Verify correct mapping maintained (by device_id)

### Test Hardware

- USB-to-Serial adapters (FTDI FT232, CH340, PL2303)
- Modbus/RTU slave device (or simulator)
- Multiple USB ports on host

---

## Implementation Order Recommendation

```
Week 1: Phase 1 + Phase 2
  - Container creation changes (low risk)
  - Persistence layer (low risk)
  - Can test manual mknod at this point

Week 2: Phase 3
  - Netmon device monitoring
  - Requires hardware testing

Week 3: Phase 4
  - Device event listener
  - Integration with persistence

Week 4: Phase 5 + Phase 6
  - Topic handler extensions
  - Full integration testing
```

---

## Rollback Plan

Each phase can be rolled back independently:

1. **Phase 1**: Remove cap_add and device_cgroup_rules from container creation
2. **Phase 2**: Delete serial_persistence.py, remove deletion hook
3. **Phase 3**: Revert netmon changes, remove pyudev
4. **Phase 4**: Remove device event handling from NetworkEventListener
5. **Phase 5**: Remove serial_configs from topic handlers

Feature flags can be added if gradual rollout is needed:

```python
# In config
ENABLE_SERIAL_PASSTHROUGH = os.environ.get("ENABLE_SERIAL_PASSTHROUGH", "false") == "true"
```

---

## Dependencies Summary

### Python Packages

- `pyudev` - USB device monitoring (netmon only)

### System Packages (Alpine)

- `eudev` - udev implementation for Alpine
- `py3-udev` - Python udev bindings

### Container Requirements

- Netmon: Access to `/dev` and `/run/udev`
- vPLC: `MKNOD` capability, device cgroup rules
