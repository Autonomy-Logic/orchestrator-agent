# Project Structure

```
orchestrator-agent/
├── src/                                    # Source code
│   ├── index.py                            # Entry point with reconnection loop
│   ├── controllers/                        # Communication protocol handlers
│   │   ├── __init__.py                     # Main WebSocket task
│   │   ├── websocket_controller/           # WebSocket client and topics
│   │   │   ├── __init__.py                 # Client configuration
│   │   │   └── topics/                     # Topic handlers
│   │   │       ├── __init__.py             # Topic registration
│   │   │       ├── receivers/              # Incoming message handlers
│   │   │       │   ├── __init__.py
│   │   │       │   ├── connect.py
│   │   │       │   ├── disconnect.py
│   │   │       │   ├── create_new_runtime.py
│   │   │       │   ├── delete_device.py
│   │   │       │   ├── delete_orchestrator.py
│   │   │       │   ├── get_consumption_device.py
│   │   │       │   ├── get_consumption_orchestrator.py
│   │   │       │   ├── get_device_status.py
│   │   │       │   ├── get_host_interfaces.py
│   │   │       │   ├── get_serial_devices.py
│   │   │       │   └── run_command.py
│   │   │       └── emitters/               # Outgoing message handlers
│   │   │           ├── __init__.py
│   │   │           └── heartbeat.py        # Periodic heartbeat emitter
│   │   └── webrtc_controller/              # WebRTC remote terminal access
│   │       ├── __init__.py                 # Session manager and initialization
│   │       ├── types.py                    # Type definitions
│   │       ├── session_manager.py          # Peer connection session tracking
│   │       ├── data_channel/               # Data channel handling
│   │       │   ├── __init__.py
│   │       │   └── data_channel_handler.py # Terminal I/O and keepalive
│   │       └── signaling/                  # WebRTC signaling handlers
│   │           ├── __init__.py
│   │           ├── offer_handler.py        # SDP offer handling
│   │           ├── ice_handler.py          # ICE candidate handling
│   │           └── disconnect_handler.py   # Peer disconnect handling
│   ├── repos/                              # Data persistence adapters
│   │   ├── __init__.py
│   │   ├── interfaces/                     # Abstract repository interfaces
│   │   │   ├── __init__.py
│   │   │   ├── container_runtime_repo_interface.py
│   │   │   ├── vnic_repo_interface.py
│   │   │   ├── serial_repo_interface.py
│   │   │   ├── client_repo_interface.py
│   │   │   ├── http_client_repo_interface.py
│   │   │   ├── network_commander_repo_interface.py
│   │   │   ├── network_interface_cache_repo_interface.py
│   │   │   └── netmon_client_repo_interface.py
│   │   ├── container_runtime_repo.py       # Docker API adapter
│   │   ├── vnic_repo.py                    # vNIC config persistence (JsonConfigStore)
│   │   ├── serial_repo.py                  # Serial port config persistence (JsonConfigStore)
│   │   ├── client_repo.py                  # Runtime client registry
│   │   ├── http_client_repo.py             # HTTP client for runtime commands
│   │   ├── network_interface_cache_repo.py # Network interface cache
│   │   └── netmon_client_repo.py           # Netmon sidecar communication
│   ├── use_cases/                          # Business logic
│   │   ├── __init__.py
│   │   ├── docker_manager/                 # Container and network management
│   │   │   ├── __init__.py                 # Self-detection + shared helpers
│   │   │   ├── create_runtime_container.py # Runtime container creation
│   │   │   ├── delete_runtime_container.py # Container deletion
│   │   │   ├── get_device_status.py        # Container status queries
│   │   │   └── selfdestruct.py             # Agent self-termination
│   │   ├── runtime_commands/               # Runtime command execution
│   │   │   ├── __init__.py                 # HTTP request utilities
│   │   │   └── run_command.py              # Command execution
│   │   ├── network_monitor/                # Network monitoring
│   │   │   ├── __init__.py
│   │   │   └── get_host_interfaces.py      # Host interface discovery
│   │   ├── collect_device_stats.py         # Device stats collection
│   │   ├── dhcp_manager.py                 # DHCP management
│   │   ├── get_consumption_device.py       # Device consumption data
│   │   ├── get_consumption_orchestrator.py # Orchestrator consumption data
│   │   ├── get_serial_devices.py           # Serial device listing
│   │   ├── network_reconnection.py         # Network reconnection logic
│   │   └── serial_device_manager.py        # Serial device management
│   └── tools/                              # Utilities
│       ├── __init__.py
│       ├── chunking.py                     # Message chunking protocol
│       ├── contract_validation.py          # Message schema validation (incl. NonEmptyStringType)
│       ├── devices_usage_buffer.py         # Device usage metrics buffer
│       ├── dns_utils.py                    # DNS resolution utilities
│       ├── json_file.py                    # JSON file I/O and JsonConfigStore
│       ├── logger.py                       # Logging with rotation
│       ├── network_event_listener.py       # Network event listener and reconnection
│       ├── network_utils.py                # Network helper utilities
│       ├── operations_state.py             # Operation state tracking (incl. begin_operation)
│       ├── ssl.py                          # mTLS configuration and agent ID
│       ├── system_info.py                  # System information
│       ├── system_metrics.py               # System metrics collection (incl. _iter_disk_usage)
│       ├── usage_buffer.py                 # Usage metrics buffer
│       └── utils.py                        # General utilities
├── install/                                # Installation files
│   ├── install.sh                          # Installation script
│   ├── autonomy-netmon.py                  # Network monitor daemon
│   ├── Dockerfile.netmon                   # Network monitor container image
│   ├── udhcpc-script.sh                    # DHCP client script
│   └── udhcpc-wifi.sh                      # WiFi DHCP client script
├── docs/                                   # Documentation
│   ├── architecture/                       # System design
│   │   ├── architecture.md                 # System architecture
│   │   └── structure.md                    # This file
│   ├── features/                           # Feature documentation
│   │   ├── cloud-protocol/
│   │   │   └── cloud-protocol.md           # Cloud communication protocol
│   │   ├── runtime-containers/
│   │   │   └── runtime-containers.md       # Runtime container management
│   │   ├── serial-port-passthrough/
│   │   │   ├── README.md                   # Feature overview
│   │   │   ├── ARCHITECTURE.md             # Technical architecture
│   │   │   └── IMPLEMENTATION_PHASES.md    # Implementation plan
│   │   └── webrtc/
│   │       └── webrtc-debug-implementation.md  # WebRTC implementation
│   ├── guides/                             # How-to guides
│   │   ├── development.md                  # Local development
│   │   ├── installation.md                 # Installation guide
│   │   └── troubleshooting.md              # Troubleshooting guide
│   ├── networking/                         # Networking documentation
│   │   ├── networking.md                   # Networking model
│   │   ├── network-monitor.md              # Network monitor sidecar
│   │   └── wifi-proxy-arp-implementation-plan.md  # WiFi support plan
│   └── operations/                         # Operations documentation
│       ├── ci-cd.md                        # CI/CD pipeline
│       ├── logging-metrics.md              # Logging and metrics
│       └── security.md                     # Security and mTLS
├── .devcontainer/                          # VS Code dev container
│   ├── devcontainer.json                   # Dev container configuration
│   ├── Dockerfile                          # Dev container image
│   └── requirements.txt                    # Dev dependencies
├── .github/workflows/                      # CI/CD
│   ├── docker.yml                          # Agent multi-arch image build
│   └── netmon-docker.yml                   # Netmon multi-arch image build
├── .gitignore                              # Git ignore rules
├── CLAUDE.md                               # Claude Code project instructions
├── Dockerfile                              # Production container image
├── LICENSE                                 # Project license
├── README.md                               # Project overview
└── requirements.txt                        # Production dependencies
```

## Key Directories

### src/
Contains all source code for the orchestrator agent.

### src/controllers/
Protocol handlers for WebSocket and WebRTC communication. Receiver handlers use the `@with_response` decorator to automatically wrap responses with `action` and `correlation_id`.

### src/use_cases/
Business logic for Docker management, runtime commands, and network monitoring. The `docker_manager/__init__.py` provides shared helpers: `stop_and_remove_container()` and `remove_internal_network()`.

### src/repos/
Data persistence adapters implementing repository interfaces. `VNICRepo` and `SerialRepo` use `JsonConfigStore` for thread-safe JSON file access. `ContainerRuntimeRepo` wraps the Docker API.

### src/tools/
Utility modules for logging, SSL/mTLS, metrics, validation, and network event handling. Key shared utilities: `JsonConfigStore` (thread-safe JSON persistence), `begin_operation()` (operation precondition checks), `_iter_disk_usage()` (disk partition iteration).

### install/
Installation script and network monitor sidecar files.

### docs/
Comprehensive documentation for all aspects of the system.

### .devcontainer/
VS Code development container configuration for consistent development environments.

### .github/workflows/
GitHub Actions workflows for CI/CD (multi-architecture Docker image builds).

## Key Files

### src/index.py
Entry point for the orchestrator agent. Implements the main reconnection loop and starts the WebSocket controller.

### src/controllers/websocket_controller/__init__.py
WebSocket client configuration and Socket.IO connection management.

### src/controllers/websocket_controller/topics/receivers/create_new_runtime.py
Handles the `create_new_runtime` topic to create OpenPLC runtime containers.

### src/use_cases/docker_manager/create_runtime_container.py
Core logic for creating runtime containers with MACVLAN and internal networks.

### src/tools/network_event_listener.py
Listens for network change events from the sidecar and triggers container reconnection.

### install/install.sh
Installation script that provisions certificates and deploys containers.

### install/autonomy-netmon.py
Network monitor daemon that detects physical network changes.

## Configuration Files

### Dockerfile
Production container image definition for the orchestrator agent.

### install/Dockerfile.netmon
Container image definition for the network monitor sidecar.

### requirements.txt
Python dependencies for the orchestrator agent.

### .devcontainer/devcontainer.json
VS Code development container configuration.

### .github/workflows/docker.yml
GitHub Actions workflow for multi-architecture Docker image builds.
