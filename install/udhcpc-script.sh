#!/bin/sh
# udhcpc script for autonomy-netmon DHCP management
# This script is called by udhcpc when DHCP events occur
# It configures the interface and writes lease info to a file for netmon to read
#
# Environment variables set by netmon:
#   ORCH_DHCP_KEY - Unique key for this DHCP client (container_name:vnic_name with : replaced by _)
#
# If ORCH_DHCP_KEY is not set, falls back to interface name (legacy behavior)

LEASE_DIR="/var/orchestrator/dhcp"
mkdir -p "$LEASE_DIR"

# Determine lease file name - use ORCH_DHCP_KEY if set, otherwise interface name
if [ -n "$ORCH_DHCP_KEY" ]; then
    LEASE_FILE="$LEASE_DIR/${ORCH_DHCP_KEY}.lease"
else
    LEASE_FILE="$LEASE_DIR/${interface}.lease"
fi

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | udhcpc | $1" >> /var/log/autonomy-netmon.log
}

case "$1" in
    deconfig)
        log "Deconfiguring interface $interface"
        ip addr flush dev "$interface" 2>/dev/null
        ;;

    bound|renew)
        log "Configuring interface $interface: IP=$ip, subnet=$subnet, mask=$mask, router=$router, dns=$dns (key=$ORCH_DHCP_KEY)"

        # Remove old addresses
        ip addr flush dev "$interface" 2>/dev/null

        # Determine prefix length from DHCP response.
        # udhcpc may provide the mask in different ways depending on the version:
        #   - $subnet: dotted-decimal (e.g., "255.255.255.0") on some builds
        #   - $mask: dotted-decimal or plain prefix length (e.g., "24")
        # We handle all cases.
        prefix=""

        # Try $subnet first (dotted-decimal netmask)
        if [ -n "$subnet" ] && echo "$subnet" | grep -q '\.'; then
            prefix=$(echo "$subnet" | awk -F. '{
                bits = 0;
                for (i = 1; i <= NF; i++) {
                    n = $i;
                    while (n > 0) { bits += n % 2; n = int(n / 2); }
                }
                print bits;
            }')
        fi

        # Try $mask if $subnet didn't work
        if [ -z "$prefix" ] && [ -n "$mask" ]; then
            if echo "$mask" | grep -q '\.'; then
                # Dotted-decimal mask (e.g., "255.255.255.0")
                prefix=$(echo "$mask" | awk -F. '{
                    bits = 0;
                    for (i = 1; i <= NF; i++) {
                        n = $i;
                        while (n > 0) { bits += n % 2; n = int(n / 2); }
                    }
                    print bits;
                }')
            else
                # Plain prefix length (e.g., "24")
                prefix="$mask"
            fi
        fi

        # Default to /24 if nothing worked
        if [ -z "$prefix" ] || [ "$prefix" -lt 1 ] 2>/dev/null || [ "$prefix" -gt 32 ] 2>/dev/null; then
            log "WARNING: Could not determine prefix length (subnet=$subnet, mask=$mask), defaulting to /24"
            prefix=24
        fi

        # Add new address (with broadcast if available)
        if [ -n "$broadcast" ]; then
            ip addr add "$ip/$prefix" broadcast "$broadcast" dev "$interface"
        else
            ip addr add "$ip/$prefix" dev "$interface"
        fi

        # Set MTU if provided by the DHCP server
        if [ -n "$mtu" ] && [ "$mtu" -gt 0 ] 2>/dev/null; then
            ip link set dev "$interface" mtu "$mtu"
            log "Set MTU=$mtu on $interface"
        fi

        # Add default route if router is provided
        if [ -n "$router" ]; then
            # Remove old default routes via this interface
            ip route del default dev "$interface" 2>/dev/null
            # Add new default route with lower metric to not override main route
            ip route add default via "$router" dev "$interface" metric 100
        fi

        # Add DHCP-provided static routes (option 121 / option 249)
        if [ -n "$staticroutes" ]; then
            log "Adding static routes: $staticroutes"
            # Format: "dest/prefix gateway dest/prefix gateway ..."
            set -- $staticroutes
            while [ -n "$1" ] && [ -n "$2" ]; do
                ip route add "$1" via "$2" dev "$interface" 2>/dev/null
                shift 2
            done
        fi

        # Configure DNS inside the vPLC container's filesystem.
        # udhcpc runs via nsenter -n (network namespace only), so /etc/resolv.conf
        # here refers to netmon's filesystem. We write to /proc/<pid>/root/etc/resolv.conf
        # to reach the container's actual filesystem (netmon runs with --pid=host).
        if [ -n "$dns" ] && [ -n "$ORCH_CONTAINER_PID" ]; then
            resolv_path="/proc/$ORCH_CONTAINER_PID/root/etc/resolv.conf"
            if [ -d "/proc/$ORCH_CONTAINER_PID/root/etc" ]; then
                # Suppress errors on writes in case the container restarts
                # between the directory check and the write (PID becomes stale).
                if : > "$resolv_path" 2>/dev/null; then
                    for server in $dns; do
                        echo "nameserver $server" >> "$resolv_path" 2>/dev/null
                    done
                    if [ -n "$domain" ]; then
                        echo "search $domain" >> "$resolv_path" 2>/dev/null
                    fi
                    log "DNS configured in container (PID=$ORCH_CONTAINER_PID): $dns"
                else
                    log "WARNING: Failed to write DNS - container may have restarted (stale PID)"
                fi
            else
                log "WARNING: Cannot write DNS - container proc path not found"
            fi
        elif [ -n "$dns" ]; then
            log "WARNING: DNS servers available ($dns) but ORCH_CONTAINER_PID not set, cannot configure container DNS"
        fi
        
        # Write lease information to file for netmon to read
        cat > "$LEASE_FILE" << EOF
{
    "interface": "$interface",
    "ip": "$ip",
    "subnet": "$subnet",
    "mask": "$mask",
    "prefix": $prefix,
    "broadcast": "$broadcast",
    "router": "$router",
    "dns": "$dns",
    "domain": "$domain",
    "mtu": "$mtu",
    "hostname": "$hostname",
    "ntpsrv": "$ntpsrv",
    "lease": "$lease",
    "serverid": "$serverid",
    "timestamp": "$(date -Iseconds)",
    "event": "$1"
}
EOF
        log "Lease info written to $LEASE_FILE"
        ;;

    leasefail|nak)
        log "DHCP lease failed for interface $interface (key=$ORCH_DHCP_KEY)"
        cat > "$LEASE_FILE" << EOF
{
    "interface": "$interface",
    "error": "lease_failed",
    "timestamp": "$(date -Iseconds)",
    "event": "$1"
}
EOF
        ;;
esac

exit 0
