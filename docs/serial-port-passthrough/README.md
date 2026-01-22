# Serial Port Passthrough Design

This folder contains the design documentation for adding serial port passthrough support to vPLC containers, enabling Modbus/RTU and other serial protocols on physical serial ports (especially USB adapters).

## Documents

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System architecture, component design, and technical details |
| [IMPLEMENTATION_PHASES.md](./IMPLEMENTATION_PHASES.md) | Step-by-step implementation plan with tasks and acceptance criteria |

## Quick Summary

### Problem

OpenPLC-runtime in vPLC containers needs to communicate via serial protocols (Modbus/RTU) using physical serial ports on the host machine, particularly USB-to-serial adapters.

### Challenges

1. USB adapters can be hot-plugged/unplugged
2. Host restarts may change device enumeration (/dev/ttyUSB0 → /dev/ttyUSB1)
3. Container restart during vPLC operation is unacceptable in industrial settings

### Solution

- Use Docker cgroup device rules to grant permission to device classes at container creation
- Dynamically create/remove device nodes using `docker exec mknod` (no container restart)
- Use stable device identifiers (`/dev/serial/by-id/...`) for reliable device matching
- Extend netmon sidecar with pyudev-based device monitoring
- Follow existing NetworkEventListener pattern for device event handling

### Key Benefits

- **No container restart** on device plug/unplug
- **Survives host reboot** with correct device reassignment
- **Fail-safe operation** - container continues running if device temporarily unavailable
- **Reuses proven patterns** from existing vNIC implementation
