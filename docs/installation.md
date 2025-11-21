# Installation

## Prerequisites

- **Operating System**: Linux (Ubuntu, Debian, RHEL, CentOS, etc.)
- **Privileges**: Root or sudo access
- **Docker**: Installed and running (installer will attempt to install if missing)

The installer will automatically install these dependencies if missing:
- `curl` - For downloading and API requests
- `jq` - For JSON parsing
- `openssl` - For certificate generation
- `docker` - For container management

## Quick Installation

```bash
curl https://getedge.me | bash
```

This command downloads and executes the installation script (`install/install.sh`).

## What the Installer Does

The installation script (`install/install.sh`) performs the following steps:

1. **Dependency Check**: Verifies and installs required packages (curl, jq, openssl, docker)

2. **Volume Creation**: Creates Docker named volume `orchestrator-shared` mounted at `/var/orchestrator`

3. **Network Monitor Deployment**:
   - Attempts to pull `ghcr.io/autonomy-logic/autonomy-netmon:latest`
   - Falls back to cloning repository and building locally if pull fails
   - Starts container with `--network=host` and `--restart unless-stopped`

4. **Orchestrator Provisioning**:
   - Requests unique orchestrator ID from Autonomy Edge provisioning API
   - Generates RSA-4096 client certificate with CN=<orchestrator_id>
   - Stores certificate and key in `~/.mtls/`
   - Uploads certificate to cloud for registration

5. **Agent Deployment**:
   - Attempts to pull `ghcr.io/autonomy-logic/orchestrator-agent:latest`
   - Falls back to cloning repository and building locally if pull fails
   - Starts container with volume mounts and `--restart unless-stopped`

6. **Verification**: Displays orchestrator ID and expiration information

## Post-Installation

After successful installation, you will have:

**Containers:**
- `orchestrator_agent` - Main orchestrator agent
- `autonomy_netmon` - Network monitor sidecar

**Volumes:**
- `orchestrator-shared` - Shared volume mounted at `/var/orchestrator`

**Credentials:**
- `~/.mtls/client.key` - Private key (600 permissions)
- `~/.mtls/client.crt` - Client certificate (644 permissions)

**Verification Commands:**
```bash
# Check container status
docker ps

# View agent logs
docker logs -f orchestrator_agent

# View network monitor logs
docker logs -f autonomy_netmon

# Check shared volume
docker volume inspect orchestrator-shared
```

## Linking to Cloud

After installation, copy the displayed orchestrator ID and paste it into the Autonomy Edge web application to link your device to your account.

## Manual Installation

For advanced users or troubleshooting, you can manually execute the installation steps. See `install/install.sh` for the complete implementation details.

## Uninstallation

To remove the orchestrator agent:

```bash
# Stop and remove containers
docker stop orchestrator_agent autonomy_netmon
docker rm orchestrator_agent autonomy_netmon

# Remove volume
docker volume rm orchestrator-shared

# Remove credentials (optional)
rm -rf ~/.mtls/
```

**Note:** This will not remove runtime containers created by the agent. Remove them separately if needed.
