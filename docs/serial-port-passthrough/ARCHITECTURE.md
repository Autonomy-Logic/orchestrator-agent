# Serial Port Passthrough Architecture

This document describes the architecture for passing through physical serial ports (especially USB adapters) to vPLC containers running OpenPLC-runtime, enabling Modbus/RTU and other serial protocols.

## Design Goals

1. **Hot-plug support without container restart** - USB serial adapters can be plugged/unplugged without restarting the vPLC container (critical for industrial operations)
2. **Host restart recovery** - Serial ports are correctly reassigned after host reboot
3. **Fail-safe operation** - Container continues running even if serial device is temporarily unavailable
4. **Leverage existing patterns** - Reuse the proven vNIC/network event architecture

## Architecture Overview

```
+-------------------------------------------------------------------------+
|                              HOST MACHINE                                |
+-------------------------------------------------------------------------+
|                                                                          |
|  USB Serial Adapter                                                      |
|  /dev/ttyUSB0 <--------------------------+                               |
|  /dev/serial/by-id/usb-FTDI_..._ABC123   | (stable identifier)           |
|                                          |                               |
|  +----------------------------+          |                               |
|  |  autonomy-netmon           |          |                               |
|  |  (sidecar container)       |          |                               |
|  |  +----------------------+  |   +------+---------------+               |
|  |  | NetworkMonitor       |  |   | DeviceMonitor (NEW)  |               |
|  |  | (existing)           |  |   | - pyudev integration |               |
|  |  | - netlink events     |  |   | - hotplug detection  |               |
|  |  | - interface discovery|  |   | - device discovery   |               |
|  |  +----------------------+  |   +----------------------+               |
|  |  +----------------------+  |                                          |
|  |  | DHCPManager          |  |                                          |
|  |  | (existing)           |  |                                          |
|  |  +----------------------+  |                                          |
|  +-------------+--------------+                                          |
|                | Unix socket                                             |
|                v /var/orchestrator/netmon.sock                           |
|  +----------------------------------------------------------------------+|
|  |  orchestrator-agent                                                  ||
|  |  +----------------------------+   +--------------------------------+ ||
|  |  | NetworkEventListener       |   | DeviceEventListener (NEW)      | ||
|  |  | (existing)                 |   | - handle device_discovery      | ||
|  |  | - network_discovery        |   | - handle device_change         | ||
|  |  | - network_change           |   | - docker exec mknod            | ||
|  |  | - dhcp_update              |   | - serial config persistence    | ||
|  |  +----------------------------+   +--------------------------------+ ||
|  +----------------------------------------------------------------------+|
|                                          |                               |
|                                          v                               |
|  +----------------------------------------------------------------------+|
|  |  vPLC Container (OpenPLC-runtime)                                    ||
|  |                                                                      ||
|  |  Created with:                                                       ||
|  |  - cap_add: [MKNOD]                                                  ||
|  |  - device_cgroup_rules: ["c 188:* rmw"]  <- allows USB serial class  ||
|  |                                                                      ||
|  |  /dev/modbus0 <-- dynamically created via mknod (no restart!)        ||
|  |       |                                                              ||
|  |  OpenPLC Modbus/RTU slave                                            ||
|  +----------------------------------------------------------------------+|
+-------------------------------------------------------------------------+
```

## Key Technical Concepts

### Why This Works Without Container Restart

Docker's `--device` flag only works at container creation time. However, we can work around this limitation:

1. **At creation time**: Grant the container *permission* to access USB serial device classes via cgroup rules (`device_cgroup_rules: ["c 188:* rmw"]`)
2. **At runtime**: Create/remove device nodes dynamically using `docker exec mknod`
3. **Result**: Container keeps running; only the device node inside it changes

### Device Class Permissions (cgroup rules)

| Device Type | Major Number | Rule | Description |
|-------------|--------------|------|-------------|
| USB-to-Serial | 188 | `c 188:* rmw` | /dev/ttyUSB* devices |
| ACM Modems | 166 | `c 166:* rmw` | /dev/ttyACM* devices |

The `rwm` permissions allow:
- `r` - read from device
- `w` - write to device
- `m` - create device nodes (mknod)

### Stable Device Identification

USB serial devices have volatile paths that can change:
- **Volatile**: `/dev/ttyUSB0` (changes on reconnect/reboot)
- **Stable**: `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_ABC123-if00-port0`

The `by-id` path contains the USB device's serial number and remains constant for the same physical adapter, regardless of which USB port it's plugged into or enumeration order.

## Component Details

### 1. DeviceMonitor (in autonomy-netmon)

Integrated into the existing netmon sidecar using pyudev for USB device detection.

**Responsibilities:**
- Monitor USB serial device hotplug events (add/remove)
- Enumerate available devices on startup
- Send device events via existing Unix socket protocol

**Required netmon changes:**
- Add pyudev dependency
- Add DeviceMonitor class (parallel to existing NetworkMonitor)
- Host device access for /dev and udev socket

**New event types:**

```json
// device_discovery (sent on connection, alongside network_discovery)
{
  "type": "device_discovery",
  "data": {
    "devices": [
      {
        "path": "/dev/ttyUSB0",
        "by_id": "/dev/serial/by-id/usb-FTDI_FT232R_ABC123-if00-port0",
        "major": 188,
        "minor": 0,
        "vendor_id": "0403",
        "product_id": "6001",
        "serial": "ABC123",
        "subsystem": "tty"
      }
    ]
  }
}

// device_change (hotplug events)
{
  "type": "device_change",
  "data": {
    "action": "add",
    "device": {
      "path": "/dev/ttyUSB0",
      "by_id": "/dev/serial/by-id/usb-FTDI_FT232R_ABC123-if00-port0",
      "major": 188,
      "minor": 0,
      "vendor_id": "0403",
      "product_id": "6001",
      "serial": "ABC123",
      "subsystem": "tty"
    }
  }
}
```

### 2. DeviceEventListener (in orchestrator-agent)

New component following the NetworkEventListener pattern.

**Responsibilities:**
- Handle device_discovery and device_change events
- Create/remove device nodes in containers via `docker exec mknod`
- Persist serial port configurations
- Resync device nodes on startup (host reboot recovery)
- Notify cloud of device availability changes

### 3. Serial Configuration Persistence

**File**: `/var/orchestrator/data/serial_configs.json`

**Schema:**
```json
{
  "vplc-production-1": {
    "serial_ports": [
      {
        "name": "modbus_rtu",
        "device_id": "usb-FTDI_FT232R_USB_UART_ABC123-if00-port0",
        "container_path": "/dev/modbus0",
        "baud_rate": 9600,
        "status": "connected",
        "current_host_path": "/dev/ttyUSB0",
        "major": 188,
        "minor": 0
      }
    ]
  }
}
```

### 4. Container Creation Changes

vPLC containers are created with device class permissions:

```python
create_kwargs = {
    ...
    "cap_add": ["SYS_NICE", "MKNOD"],
    "device_cgroup_rules": [
        "c 188:* rmw",  # USB-to-serial (ttyUSB*)
        "c 166:* rmw",  # ACM modems (ttyACM*)
    ],
}
```

## Event Flows

### Flow 1: Device Plugged In

```
1. USB adapter plugged into host
2. pyudev in netmon detects ADD event
3. netmon sends device_change event via Unix socket
4. DeviceEventListener receives event
5. Matches device to configured serial port by device_id
6. Gets major:minor numbers from event
7. Runs: docker exec -u root vplc mknod /dev/modbus0 c 188 0
8. Updates serial config status to "connected"
9. OpenPLC immediately sees device (no restart needed)
10. Notifies cloud of device availability
```

### Flow 2: Device Unplugged

```
1. USB adapter unplugged from host
2. pyudev detects REMOVE event
3. netmon sends device_change event
4. DeviceEventListener receives event
5. Updates serial config status to "disconnected"
6. Device node in container becomes non-functional
7. OpenPLC gets I/O errors but KEEPS RUNNING
8. Notifies cloud of device unavailability
```

### Flow 3: Device Plugged Back In

```
1. Same adapter plugged back in
2. May get different minor number (ttyUSB1 instead of ttyUSB0)
3. But by_id path is the same (stable identifier)
4. DeviceEventListener matches by device_id
5. Removes old device node, creates new one with new major:minor
6. OpenPLC resumes communication (no restart)
```

### Flow 4: Host Reboot Recovery

```
1. Host boots, containers auto-start
2. netmon starts, DeviceMonitor enumerates devices
3. Sends device_discovery with all current devices
4. DeviceEventListener loads serial_configs.json
5. For each configured port:
   a. Find device by stable device_id
   b. Resolve to current /dev/ttyUSBx path
   c. Get current major:minor numbers
   d. Create device node in container
6. vPLC containers resume Modbus/RTU without restart
```

## Fail-Safe Behavior Matrix

| Scenario | Container Status | Serial Status | Action |
|----------|-----------------|---------------|--------|
| Device unplugged | **Running** | I/O errors | Log, notify cloud |
| Device plugged back | **Running** | Working | Recreate node, notify cloud |
| Different USB port | **Running** | Working | Same by-id, new minor |
| Host reboot, device present | **Running** | Working | Resync nodes on startup |
| Host reboot, device missing | **Running** | Unavailable | Log, wait for device |
| Container restart, device present | Restarting | Working | Recreate node |
| Multiple devices swapped | **Running** | Correct | by-id ensures correct mapping |

## Netmon Privilege Requirements

To support device monitoring, netmon requires additional access:

```yaml
# docker-compose or container creation
volumes:
  - /var/orchestrator:/var/orchestrator
  - /run/udev:/run/udev:ro          # NEW: udev socket access
  - /dev:/dev:ro                     # NEW: device enumeration

# Or specific device access
devices:
  - /dev/ttyUSB0:/dev/ttyUSB0       # Specific devices
```

Alternative: Run netmon with `--privileged` flag for full device access (simpler but less secure).

## API Extensions

### Topic: create_new_runtime (extended)

```json
{
  "action": "create_new_runtime",
  "correlation_id": "uuid",
  "container_name": "vplc-1",
  "vnic_configs": [...],
  "serial_configs": [
    {
      "name": "modbus_rtu",
      "device_id": "usb-FTDI_FT232R_USB_UART_ABC123-if00-port0",
      "container_path": "/dev/modbus0",
      "baud_rate": 9600
    }
  ]
}
```

### Topic: get_device_status (extended response)

```json
{
  "action": "get_device_status",
  "status": "running",
  "serial_devices": [
    {
      "name": "modbus_rtu",
      "device_id": "usb-FTDI_FT232R_USB_UART_ABC123-if00-port0",
      "container_path": "/dev/modbus0",
      "status": "connected",
      "host_path": "/dev/ttyUSB0"
    }
  ]
}
```

### Topic: attach_serial_device (new, optional)

```json
{
  "action": "attach_serial_device",
  "correlation_id": "uuid",
  "container_name": "vplc-1",
  "serial_config": {
    "name": "modbus_rtu",
    "device_id": "usb-FTDI_FT232R_USB_UART_ABC123-if00-port0",
    "container_path": "/dev/modbus0"
  }
}
```

## Comparison with vNIC Pattern

| Aspect | vNIC | Serial Port |
|--------|------|-------------|
| Identification | MAC address | USB serial number (by-id) |
| Persistence file | runtime_vnics.json | serial_configs.json |
| Docker mechanism | Network connect/disconnect | cgroup rules + mknod |
| Hotplug handling | Network reconnection | Device node recreation |
| Event source | netlink (pyroute2) | udev (pyudev) |
| Container restart | Not required | Not required |

## Security Considerations

1. **Cgroup rules are permissive** - Container can access any device of the allowed class (major number)
2. **MKNOD capability** - Container can create device nodes (limited by cgroup rules)
3. **Device isolation** - Each container should only have access to its assigned devices
4. **Netmon privileges** - Needs read access to /dev and udev socket

## References

- [Docker device access documentation](https://docs.docker.com/engine/containers/run/#runtime-privilege-and-linux-capabilities)
- [Linux cgroup device controller](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v1/devices.html)
- [pyudev documentation](https://pyudev.readthedocs.io/)
- [udev stable device naming](https://wiki.archlinux.org/title/Udev#Setting_static_device_names)
