# Project Structure

```
orchestrator-agent/
├── src/                                    # Source code
│   ├── index.py                            # Entry point with reconnection loop
│   ├── bootstrap.py                        # Composition root (dependency wiring)
│   ├── entities/                           # Domain entities (zero dependencies)
│   │   ├── __init__.py
│   │   ├── container_client.py             # Runtime client domain object
│   │   ├── network_interface.py            # Network interface domain object
│   │   ├── operation_state.py              # Operation state domain object
│   │   ├── serial_config.py                # Serial config domain object
│   │   └── vnic_config.py                  # vNIC config domain object
│   ├── controllers/                        # Communication protocol handlers
│   │   ├── __init__.py                     # Main WebSocket task
│   │   ├── websocket_controller/           # WebSocket client and topics
│   │   │   ├── __init__.py                 # Client configuration
│   │   │   ├── debug_session_manager.py    # HTTP-path debug session manager
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
│   │       │   ├── data_channel_handler.py # Terminal I/O and keepalive
│   │       │   └── debug_channel_handler.py # Debug bridge DataChannel handler
│   │       └── signaling/                  # WebRTC signaling handlers
│   │           ├── __init__.py
│   │           ├── offer_handler.py        # SDP offer handling
│   │           ├── ice_handler.py          # ICE candidate handling
│   │           └── disconnect_handler.py   # Peer disconnect handling
│   ├── repos/                              # Data persistence adapters
│   │   ├── __init__.py
│   │   ├── interfaces/                     # Abstract repository interfaces
│   │   │   ├── __init__.py
│   │   │   ├── client_repo_interface.py
│   │   │   ├── container_runtime_repo_interface.py
│   │   │   ├── debug_socket_repo_interface.py
│   │   │   ├── http_client_repo_interface.py
│   │   │   ├── netmon_client_repo_interface.py
│   │   │   ├── network_commander_repo_interface.py
│   │   │   ├── network_interface_cache_repo_interface.py
│   │   │   ├── serial_repo_interface.py
│   │   │   ├── socket_repo_interface.py
│   │   │   └── vnic_repo_interface.py
│   │   ├── client_repo.py                  # Runtime client registry
│   │   ├── container_runtime_repo.py       # Docker API adapter
│   │   ├── debug_socket_repo.py            # Socket.IO client for runtime debug
│   │   ├── http_client_repo.py             # HTTP client for runtime commands
│   │   ├── netmon_client_repo.py           # Netmon sidecar communication
│   │   ├── network_interface_cache_repo.py # Network interface cache
│   │   ├── serial_repo.py                  # Serial port config persistence (JsonConfigStore)
│   │   ├── socket_repo.py                  # Socket.IO client wrapper
│   │   └── vnic_repo.py                    # vNIC config persistence (JsonConfigStore)
│   ├── use_cases/                          # Business logic
│   │   ├── __init__.py
│   │   ├── docker_manager/                 # Container and network management
│   │   │   ├── __init__.py                 # Self-detection + shared helpers
│   │   │   ├── create_runtime_container.py # Runtime container creation
│   │   │   ├── delete_runtime_container.py # Container deletion
│   │   │   ├── get_device_status.py        # Container status queries
│   │   │   └── selfdestruct.py             # Agent self-termination
│   │   ├── debug_client/                   # Debug bridge use cases
│   │   │   ├── __init__.py
│   │   │   ├── run_debug_command.py        # Stateless debug command dispatcher
│   │   │   └── validate_session.py         # Debug session validation
│   │   ├── runtime_commands/               # Runtime command execution
│   │   │   ├── __init__.py
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
│       ├── debug_protocol.py               # Debug protocol builders and parsers
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
├── tests/                                  # Test suite
│   ├── architecture/                       # Architecture dependency rule tests
│   │   └── test_dependency_rules.py
│   └── unit/                               # Unit tests
│       ├── conftest.py
│       ├── entities/                       # Entity tests
│       ├── repos/                          # Repository tests
│       ├── tools/                          # Tool tests
│       └── use_cases/                      # Use case tests
├── scripts/                                # Development scripts
│   ├── install-hooks.sh                    # Git hook installer
│   ├── pre-commit                          # Pre-commit hook (black formatter)
│   ├── run-tests.sh                        # Test runner script
│   └── validate_debug_protocol.py          # Debug protocol validation
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
│   │   │   ├── cloud-protocol.md           # Cloud communication protocol
│   │   │   └── openplc-debug-protocol.md   # OpenPLC debug protocol reference
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
├── .claude/                                # Claude Code configuration
│   ├── CLAUDE.md                           # Clean architecture reference guide
│   ├── hooks/                              # Claude Code hooks
│   └── settings.json                       # Claude Code settings
├── .devcontainer/                          # VS Code dev container
│   ├── devcontainer.json                   # Dev container configuration
│   ├── Dockerfile                          # Dev container image
│   ├── requirements.txt                    # Dev container dependencies
│   └── requirements-dev.txt                # Dev/test dependencies
├── .github/workflows/                      # CI/CD
│   ├── docker.yml                          # Agent multi-arch image build
│   ├── netmon-docker.yml                   # Netmon multi-arch image build
│   ├── unit-tests.yml                      # Unit test workflow (PRs)
│   ├── architecture-tests.yml              # Architecture dependency tests (PRs)
│   ├── format-check.yml                    # Black format check (PRs)
│   └── lint.yml                            # Pylint errors-only check (PRs)
├── .gitignore                              # Git ignore rules
├── CLAUDE.md                               # Claude Code project instructions
├── Dockerfile                              # Production container image
├── LICENSE                                 # Project license
├── README.md                               # Project overview
├── pytest.ini                              # Pytest configuration
├── requirements.txt                        # Production dependencies
└── requirements-dev.txt                    # Development/test dependencies
```

## Key Directories

### src/

Contains all source code for the orchestrator agent.

### src/entities/

Domain entity dataclasses with zero dependencies. Enforce business invariants and serve as the innermost layer of the clean architecture.

### src/controllers/

Protocol handlers for WebSocket and WebRTC communication. Receiver handlers use the `@with_response` decorator to automatically wrap responses with `action` and `correlation_id`.

### src/use_cases/

Business logic for Docker management, runtime commands, debug bridging, and network monitoring. The `docker_manager/__init__.py` provides shared helpers: `stop_and_remove_container()` and `remove_internal_network()`.

### src/repos/

Data persistence adapters implementing repository interfaces defined in `repos/interfaces/`. `VNICRepo` and `SerialRepo` use `JsonConfigStore` for thread-safe JSON file access. `ContainerRuntimeRepo` wraps the Docker API. `DebugSocketRepo` manages persistent Socket.IO connections to runtime debug endpoints.

### src/tools/

Utility modules for logging, SSL/mTLS, metrics, validation, debug protocol, and network event handling. Key shared utilities: `JsonConfigStore` (thread-safe JSON persistence), `begin_operation()` (operation precondition checks), `_iter_disk_usage()` (disk partition iteration), `debug_protocol.py` (hex command builders and response parsers).

### tests/

Automated test suite with architecture dependency rule tests and unit tests covering entities, repos, tools, and use cases.

### scripts/

Development scripts for running tests, installing git hooks, and validating the debug protocol.

### install/

Installation script and network monitor sidecar files.

### docs/

Comprehensive documentation for all aspects of the system.

### .devcontainer/

VS Code development container configuration for consistent development environments.

### .github/workflows/

GitHub Actions workflows for CI/CD: multi-architecture Docker image builds, unit tests, architecture tests, format checks, and linting.

## Key Files

### src/index.py
Entry point for the orchestrator agent. Implements the main reconnection loop and starts the WebSocket controller.

### src/bootstrap.py
Composition root that instantiates all concrete implementations (repos, use cases) and wires dependencies together via constructor injection.

### src/controllers/websocket_controller/__init__.py
WebSocket client configuration and Socket.IO connection management.

### src/controllers/websocket_controller/debug_session_manager.py
HTTP-path debug session manager for the WebSocket fallback path. Mirrors `DebugChannelHandler` logic with thread-safe session management keyed by `device_id`.

### src/controllers/websocket_controller/topics/receivers/create_new_runtime.py
Handles the `create_new_runtime` topic to create OpenPLC runtime containers.

### src/controllers/webrtc_controller/data_channel/debug_channel_handler.py
WebRTC DataChannel handler for the debug bridge. Routes JSON messages between the browser and the runtime's Socket.IO debug endpoint.

### src/use_cases/docker_manager/create_runtime_container.py
Core logic for creating runtime containers with MACVLAN and internal networks.

### src/use_cases/debug_client/run_debug_command.py
Stateless debug command dispatcher. Builds hex commands via `debug_protocol.py` and sends them through `DebugSocketRepo`.

### src/tools/debug_protocol.py
Pure protocol functions for building debug hex commands (`build_get_md5`, `build_get_list`, `build_set_variable`) and parsing responses.

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

### requirements-dev.txt
Development and test dependencies (pytest, coverage, black, pylint).

### pytest.ini
Pytest configuration for test discovery and execution.

### .devcontainer/devcontainer.json
VS Code development container configuration.

### .github/workflows/docker.yml
GitHub Actions workflow for multi-architecture Docker image builds.
