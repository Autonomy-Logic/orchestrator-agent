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
- **MACVLAN Networking**: Runtime containers appear as native devices on the physical LAN
- **Dynamic Network Adaptation**: Automatically reconnects containers when the host moves between networks
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
│   └── tools/              # Utilities (logging, SSL, metrics, validation)
├── install/                # Installation script and network monitor
├── docs/                   # Detailed documentation
├── .devcontainer/          # VS Code dev container
├── .github/workflows/      # CI/CD pipelines
├── Dockerfile              # Production container image
└── requirements.txt        # Python dependencies
```

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

This is a private repository for the Autonomy Logic team. For contribution guidelines and development workflow, please refer to the team's internal documentation.

**Branch Naming Conventions:**
- Features: `feature/JIRA-123-description`
- Bugfixes: `bugfix/JIRA-123-description`
- Hotfixes: `hotfix/JIRA-123-description`

**Pull Request Process:**
1. Create a branch following the naming convention
2. Make your changes with clear, descriptive commit messages
3. Push your branch to the remote repository
4. Open a Pull Request targeting the `development` branch
5. Reference your JIRA ticket in the PR description
6. Request code review from team members

## License

Copyright © 2025 Autonomy Logic. All rights reserved.
