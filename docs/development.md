# Local Development

## Prerequisites

- Python 3.11 or higher
- Docker installed and running
- mTLS certificates in `~/.mtls/` (see [Installation](installation.md))

## Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Autonomy-Logic/orchestrator-agent.git
   cd orchestrator-agent
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Generate mTLS certificates** (if not already provisioned):
   
   The installer normally provisions these certificates. For local development, you can generate self-signed certificates:
   
   ```bash
   mkdir -p ~/.mtls
   openssl req -x509 -newkey rsa:4096 -nodes \
     -keyout ~/.mtls/client.key \
     -out ~/.mtls/client.crt \
     -subj "/C=BR/ST=SP/L=SaoPaulo/O=AutonomyLogic/OU=Development/CN=dev-agent" \
     -days 365
   chmod 600 ~/.mtls/client.key
   ```
   
   **Note:** Development certificates will not authenticate with the production cloud server.

4. **Run the agent:**
   ```bash
   python3 src/index.py
   ```

5. **Set log level** (optional):
   ```bash
   python3 src/index.py --log-level DEBUG
   ```

## VS Code Dev Container

The repository includes a VS Code dev container configuration for consistent development environments.

**Features:**
- Python 3.11 environment
- Docker-outside-of-Docker (uses host Docker daemon)
- Volume mounts for mTLS certificates and Docker socket
- Pre-installed dependencies

**Usage:**
1. Open repository in VS Code
2. Install "Dev Containers" extension
3. Press `F1` → "Dev Containers: Reopen in Container"

**Configuration:** `.devcontainer/devcontainer.json`

## Development Workflow

### Making Changes

1. Create a feature branch:
   ```bash
   git checkout -b feature/JIRA-123-description
   ```

2. Make your changes with clear, descriptive commit messages

3. Test your changes locally:
   ```bash
   python3 src/index.py --log-level DEBUG
   ```

4. Push your branch:
   ```bash
   git push origin feature/JIRA-123-description
   ```

5. Open a Pull Request targeting the `development` branch

### Code Style

- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Write clear, descriptive docstrings
- Keep functions focused and single-purpose

### Testing

Currently, the project does not have automated tests. Manual testing is required:

1. Start the agent locally
2. Verify WebSocket connection to cloud
3. Test container creation and deletion
4. Verify network change detection and reconnection
5. Check logs for errors

## Project Structure

See [Project Structure](structure.md) for a detailed overview of the codebase organization.

## Debugging

### Enable Debug Logging

```bash
python3 src/index.py --log-level DEBUG
```

### View Logs

Logs are written to:
- `/var/orchestrator/logs/orchestrator-logs-YYYY-MM-DD.log` - Operational logs
- `/var/orchestrator/debug/orchestrator-debug-YYYY-MM-DD.log` - Debug logs

### Common Issues

**Import Errors:**
- Ensure all dependencies are installed: `pip install -r requirements.txt`

**Docker Connection Errors:**
- Verify Docker daemon is running: `docker info`
- Check Docker socket permissions

**Certificate Errors:**
- Verify certificates exist in `~/.mtls/`
- Check certificate permissions (key: 600, cert: 644)

## Contributing

For contribution guidelines, see the main [README](../README.md#contributing).
