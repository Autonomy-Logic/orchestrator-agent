# Troubleshooting

## mTLS Certificate Issues

**Symptom:** `FileNotFoundError: [Errno 2] No such file or directory: '/root/.mtls/client.crt'`

**Cause:** mTLS certificates not found or incorrect permissions

**Solution:**
1. Verify certificates exist:
   ```bash
   ls -la ~/.mtls/
   ```
2. Check permissions:
   ```bash
   chmod 600 ~/.mtls/client.key
   chmod 644 ~/.mtls/client.crt
   chmod 700 ~/.mtls/
   ```
3. Re-run installer if certificates are missing:
   ```bash
   curl https://getedge.me | bash
   ```

## WebSocket Connection Errors

**Symptom:** `Socket.IO connection error: <error details>`

**Possible Causes:**
- Invalid or expired mTLS certificate
- Network connectivity issues
- Cloud server unavailable
- Incorrect agent ID in certificate

**Solution:**
1. Check agent logs:
   ```bash
   docker logs orchestrator_agent
   ```
2. Verify certificate CN matches agent ID:
   ```bash
   openssl x509 -in ~/.mtls/client.crt -noout -subject
   ```
3. Test network connectivity:
   ```bash
   curl -v https://api.getedge.me
   ```
4. Restart agent container:
   ```bash
   docker restart orchestrator_agent
   ```

## Network Monitor Socket Missing

**Symptom:** `Network monitor socket not found at /var/orchestrator/netmon.sock, waiting for network monitor daemon...`

**Cause:** Network monitor sidecar not running or socket not created

**Solution:**
1. Check netmon container status:
   ```bash
   docker ps -a | grep autonomy_netmon
   ```
2. Check netmon logs:
   ```bash
   docker logs autonomy_netmon
   ```
3. Verify shared volume:
   ```bash
   docker volume inspect orchestrator-shared
   ```
4. Restart netmon container:
   ```bash
   docker restart autonomy_netmon
   ```
5. Check socket permissions:
   ```bash
   docker exec autonomy_netmon ls -la /var/orchestrator/netmon.sock
   ```

## Docker Network Overlap Errors

**Symptom:** `Pool overlaps with other one on this address space`

**Cause:** Attempting to create MACVLAN network with subnet that conflicts with existing network

**Solution:**
The agent automatically handles this by searching for and reusing existing MACVLAN networks. Check logs for:
```
Network overlap detected for subnet X.X.X.X/XX. Searching for existing MACVLAN network to reuse...
Found existing MACVLAN network <name> with matching subnet and parent. Reusing it.
```

If the error persists:
1. List existing networks:
   ```bash
   docker network ls
   docker network inspect <network-name>
   ```
2. Remove conflicting networks (if safe):
   ```bash
   docker network rm <network-name>
   ```
3. Check agent logs for detailed error information

## Container Creation Failures

**Symptom:** Runtime container creation fails or times out

**Possible Causes:**
- Docker daemon issues
- Image pull failures
- Network configuration errors
- Insufficient resources

**Solution:**
1. Check agent logs for detailed error:
   ```bash
   docker logs orchestrator_agent | grep -A 20 "Failed to create runtime container"
   ```
2. Verify Docker daemon is running:
   ```bash
   docker info
   ```
3. Test image pull manually:
   ```bash
   docker pull ghcr.io/autonomy-logic/openplc-runtime:latest
   ```
4. Check available resources:
   ```bash
   docker system df
   df -h
   free -h
   ```
5. Verify parent interface exists:
   ```bash
   ip addr show
   ```

## Sidecar Health Issues

**Symptom:** Network monitor container unhealthy or restarting

**Solution:**
1. Check container health:
   ```bash
   docker inspect autonomy_netmon | grep -A 10 Health
   ```
2. Check logs for errors:
   ```bash
   docker logs autonomy_netmon
   ```
3. Verify host network access:
   ```bash
   docker exec autonomy_netmon ip addr
   ```
4. Restart container:
   ```bash
   docker restart autonomy_netmon
   ```

## Agent Not Reconnecting After Network Change

**Symptom:** Runtime containers lose connectivity after host network change

**Solution:**
1. Verify network monitor is detecting changes:
   ```bash
   docker logs autonomy_netmon | grep "network_change"
   ```
2. Check agent is receiving events:
   ```bash
   docker logs orchestrator_agent | grep "Network change detected"
   ```
3. Verify vNIC persistence file exists:
   ```bash
   docker exec orchestrator_agent cat /var/orchestrator/runtime_vnics.json
   ```
4. Check for reconnection errors in agent logs:
   ```bash
   docker logs orchestrator_agent | grep "Failed to reconnect"
   ```

## Getting Help

If you encounter issues not covered in this guide:

1. Check the agent logs for detailed error messages
2. Review the [Architecture](architecture.md) documentation to understand system components
3. Consult the relevant documentation:
   - [Installation](installation.md) for setup issues
   - [Security](security.md) for certificate issues
   - [Networking](networking.md) for network configuration issues
   - [Cloud Protocol](cloud-protocol.md) for communication issues
4. Contact Autonomy Logic support with:
   - Agent logs (`docker logs orchestrator_agent`)
   - Network monitor logs (`docker logs autonomy_netmon`)
   - System information (`docker info`, `ip addr`)
   - Steps to reproduce the issue
