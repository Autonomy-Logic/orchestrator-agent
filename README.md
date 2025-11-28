# Orchestrator Agent

The Orchestrator Agent is a Python daemon that runs on edge devices as a Docker container. It maintains a continuous, mutually authenticated WebSocket connection to the Autonomy Edge Cloud and remotely orchestrates OpenPLC v4 runtime containers (vPLCs) on the host machine.

Communication uses mutual TLS (mTLS) authentication where both client and server verify each other's identity, preventing device impersonation and man-in-the-middle attacks. A companion network monitor sidecar container observes host networking events and enables automatic MACVLAN network reconfiguration when the host's physical network changes.

## Quick Start

**Installation:**
```bash
curl https://getedge.me | bash
```

**Images:**
- Agent: `ghcr.io/autonomy-logic/orchestrator-agent:latest`
- Network Monitor: `ghcr.io/autonomy-logic/autonomy-netmon:latest`
- Runtime: `ghcr.io/autonomy-logic/openplc-runtime:latest`

## Key Capabilities

- **Secure Cloud Control**: Maintains persistent WebSocket connection to Autonomy Edge Cloud using mTLS
- **Container Orchestration**: Creates, configures, and manages OpenPLC v4 runtime containers (vPLCs)
- **MACVLAN Networking**: Runtime containers appear as native devices on the physical LAN with configurable IP addressing (static manual IP or DHCP)
- **Dynamic Network Adaptation**: Automatically reconnects containers when the host moves between networks, preserving IP configuration settings
- **Network Monitor Sidecar**: Event-driven monitoring of physical network interfaces
- **System Monitoring**: Periodic heartbeats with CPU, memory, disk, and uptime metrics
- **Contract Validation**: Type-safe message validation for all cloud commands

## Project Structure

```
orchestrator-agent/
├── src/                    # Source code
│   ├── index.py            # Entry point
│   ├── controllers/        # WebSocket and protocol handlers
│   ├── use_cases/          # Business logic (Docker, network, commands)
│   └── tools/              # Utilities (logging, SSL, metrics, validation, state tracking)
├── install/                # Installation script and network monitor
├── docs/                   # Detailed documentation
├── .devcontainer/          # VS Code dev container
├── .github/workflows/      # CI/CD pipelines
├── Dockerfile              # Production container image
└── requirements.txt        # Python dependencies
```

### Architecture Layers

The codebase follows a layered architecture separating concerns:

- **controllers/**: Transport layer handling WebSocket topics and message routing. Topic handlers use a `@validate_message` decorator for contract validation and delegate business logic to use cases.
- **use_cases/**: Business logic layer containing domain operations like container management (`get_device_status`, `get_host_interfaces`) and Docker orchestration.
- **tools/**: Infrastructure utilities including logging, SSL, contract validation, operations state tracking, interface caching, vNIC persistence, and network event listening.

For the complete directory structure, see [Project Structure](docs/structure.md).

## Documentation

- **[Architecture](docs/architecture.md)** - System architecture, components, and communication paths
- **[Installation](docs/installation.md)** - Installation guide, prerequisites, and post-installation steps
- **[Security](docs/security.md)** - mTLS authentication, agent identity, and certificate management
- **[Networking](docs/networking.md)** - MACVLAN networks, dynamic adaptation, and vNIC configuration
- **[Cloud Protocol](docs/cloud-protocol.md)** - WebSocket topics, heartbeat format, and contract validation
- **[Runtime Containers](docs/runtime-containers.md)** - Creating and managing OpenPLC runtime containers
- **[Network Monitor](docs/network-monitor.md)** - Network monitor sidecar architecture and event types
- **[Logging & Metrics](docs/logging-metrics.md)** - Log locations, levels, rotation, and system metrics
- **[Troubleshooting](docs/troubleshooting.md)** - Common issues and solutions
- **[Development](docs/development.md)** - Local development setup and workflow
- **[CI/CD](docs/ci-cd.md)** - Multi-architecture image builds and deployment

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

**How to Contribute:**
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with clear, descriptive commit messages
4. Push to your branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request targeting the `development` branch

For detailed development setup instructions, see [Development](docs/development.md).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
