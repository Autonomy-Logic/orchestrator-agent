# Logging and Metrics

## Log Locations

### Container Logs

```bash
# Agent logs
docker logs -f orchestrator_agent

# Network monitor logs
docker logs -f autonomy_netmon
```

### File Logs (inside agent container)

- `/var/orchestrator/logs/orchestrator-logs-YYYY-MM-DD.log` - Operational logs (configurable level)
- `/var/orchestrator/debug/orchestrator-debug-YYYY-MM-DD.log` - Debug logs (DEBUG level)

### Network Monitor Logs (inside netmon container)

- `/var/log/autonomy-netmon.log` - Network monitor logs

## Log Levels

The agent supports configurable log levels via command-line argument:

```bash
python3 src/index.py --log-level DEBUG
```

**Available Levels:**
- `DEBUG` - Detailed diagnostic information
- `INFO` - General informational messages (default)
- `WARNING` - Warning messages
- `ERROR` - Error messages
- `CRITICAL` - Critical errors

## Log Rotation

Logs are automatically rotated daily with the date in the filename pattern.

## System Metrics

The agent collects and reports system metrics via heartbeat messages:

### CPU Usage

- Measured using `psutil.cpu_percent()`
- Non-blocking query (interval=None)
- Reported as percentage (0-100)

### Memory Usage

- Total memory computed once at startup
- Current usage queried via `psutil.virtual_memory().used`
- Reported in GB

### Disk Usage

- Total disk space computed once at startup
- Current usage summed across physical partitions
- Filters out virtual filesystems (tmpfs, devtmpfs, overlay, etc.)
- Deduplicates devices to prevent double-counting
- Reported in GB

### Uptime

- Computed from process start time
- Reported in seconds

**Implementation:** `src/tools/system_metrics.py`

## Accessing Logs

### View Recent Logs

```bash
# Last 100 lines of agent logs
docker logs --tail 100 orchestrator_agent

# Last 100 lines of network monitor logs
docker logs --tail 100 autonomy_netmon
```

### Follow Logs in Real-Time

```bash
# Follow agent logs
docker logs -f orchestrator_agent

# Follow network monitor logs
docker logs -f autonomy_netmon
```

### Search Logs

```bash
# Search for errors in agent logs
docker logs orchestrator_agent | grep ERROR

# Search for network changes
docker logs autonomy_netmon | grep "network_change"
```

### Export Logs

```bash
# Export agent logs to file
docker logs orchestrator_agent > agent-logs.txt

# Export network monitor logs to file
docker logs autonomy_netmon > netmon-logs.txt
```

## Log Analysis

### Common Log Patterns

**Successful Connection:**
```
Socket.IO connection established
Starting heartbeat emitter
```

**Network Change Detected:**
```
Network change detected for interface ens37
Reconnecting runtime containers on interface ens37
```

**Container Creation:**
```
Creating runtime container plc-001
Created internal network plc-001_internal
Created MACVLAN network macvlan_ens37_192.168.1.0_24
Container plc-001 created successfully
```

**Certificate Issues:**
```
FileNotFoundError: [Errno 2] No such file or directory: '/root/.mtls/client.crt'
```

## Metrics Collection

The agent collects metrics for:
- System health (CPU, memory, disk)
- Container status
- Network connectivity
- Command execution

Metrics are reported to the cloud via heartbeat messages every 5 seconds.

## Troubleshooting

For logging-related issues, check:
- Container logs for errors
- File logs for detailed diagnostic information
- System metrics for resource constraints
