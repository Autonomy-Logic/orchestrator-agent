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
│   │   │       │   ├── connect.py
│   │   │       │   ├── disconnect.py
│   │   │       │   ├── create_new_runtime.py
│   │   │       │   ├── delete_device.py
│   │   │       │   ├── delete_orchestrator.py
│   │   │       │   ├── run_command.py
│   │   │       │   ├── start_device.py
│   │   │       │   ├── stop_device.py
│   │   │       │   ├── restart_device.py
│   │   │       │   ├── get_consumption_device.py
│   │   │       │   └── get_consumption_orchestrator.py
│   │   │       └── emitters/               # Outgoing message handlers
│   │   │           ├── __init__.py
│   │   │           └── heartbeat.py        # Periodic heartbeat emitter
│   │   └── webrtc_controller/              # WebRTC (not implemented)
│   ├── use_cases/                          # Business logic
│   │   ├── docker_manager/                 # Container and network management
│   │   │   ├── __init__.py                 # Docker client and registry
│   │   │   ├── create_runtime_container.py # Runtime container creation
│   │   │   ├── create_new_container.py     # Legacy container creation
│   │   │   ├── delete_runtime_container.py # Container deletion
│   │   │   ├── vnic_persistence.py         # vNIC configuration persistence
│   │   │   └── selfdestruct.py             # Agent self-termination
│   │   ├── runtime_commands/               # Runtime command execution
│   │   │   ├── __init__.py                 # HTTP request utilities
│   │   │   └── run_command.py              # Command execution
│   │   └── network_monitor/                # Network monitoring
│   │       ├── __init__.py
│   │       ├── network_event_listener.py   # Event listener and reconnection
│   │       └── interface_cache.py          # Interface information cache
│   └── tools/                              # Utilities
│       ├── logger.py                       # Logging with rotation
│       ├── ssl.py                          # mTLS configuration and agent ID
│       ├── system_metrics.py               # System metrics collection
│       ├── system_info.py                  # System information
│       ├── contract_validation.py          # Message schema validation
│       └── usage_buffer.py                 # Usage metrics buffer
├── install/                                # Installation files
│   ├── install.sh                          # Installation script
│   ├── autonomy-netmon.py                  # Network monitor daemon
│   └── Dockerfile.netmon                   # Network monitor container image
├── docs/                                   # Documentation
│   ├── architecture.md                     # System architecture
│   ├── installation.md                     # Installation guide
│   ├── security.md                         # Security and mTLS
│   ├── networking.md                       # Networking model
│   ├── cloud-protocol.md                   # Cloud communication protocol
│   ├── runtime-containers.md               # Runtime container management
│   ├── network-monitor.md                  # Network monitor sidecar
│   ├── logging-metrics.md                  # Logging and metrics
│   ├── troubleshooting.md                  # Troubleshooting guide
│   ├── development.md                      # Local development
│   ├── ci-cd.md                            # CI/CD pipeline
│   └── structure.md                        # This file
├── .devcontainer/                          # VS Code dev container
│   ├── devcontainer.json                   # Dev container configuration
│   ├── Dockerfile                          # Dev container image
│   └── requirements.txt                    # Dev dependencies
├── .github/workflows/                      # CI/CD
│   └── docker.yml                          # Multi-arch image build
├── Dockerfile                              # Production container image
├── requirements.txt                        # Production dependencies
└── README.md                               # Project overview
```

## Key Directories

### src/
Contains all source code for the orchestrator agent.

### src/controllers/
Protocol handlers for WebSocket and WebRTC communication (WebRTC not implemented).

### src/use_cases/
Business logic for Docker management, runtime commands, and network monitoring.

### src/tools/
Utility modules for logging, SSL/mTLS, metrics, and validation.

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

### src/use_cases/network_monitor/network_event_listener.py
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
