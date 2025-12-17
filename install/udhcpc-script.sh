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
        log "Configuring interface $interface: IP=$ip, mask=$mask, router=$router (key=$ORCH_DHCP_KEY)"
        
        # Remove old addresses
        ip addr flush dev "$interface" 2>/dev/null
        
        # Calculate prefix length from netmask
        if [ -n "$mask" ]; then
            prefix=$(echo "$mask" | awk -F. '{
                split($0, a, ".");
                bits = 0;
                for (i = 1; i <= 4; i++) {
                    n = a[i];
                    while (n > 0) {
                        bits += n % 2;
                        n = int(n / 2);
                    }
                }
                print bits;
            }')
        else
            prefix=24
        fi
        
        # Add new address
        ip addr add "$ip/$prefix" dev "$interface"
        
        # Add default route if router is provided
        if [ -n "$router" ]; then
            # Remove old default routes via this interface
            ip route del default dev "$interface" 2>/dev/null
            # Add new default route with lower metric to not override main route
            ip route add default via "$router" dev "$interface" metric 100
        fi
        
        # Configure DNS if provided
        if [ -n "$dns" ]; then
            log "DNS servers: $dns"
        fi
        
        # Write lease information to file for netmon to read
        cat > "$LEASE_FILE" << EOF
{
    "interface": "$interface",
    "ip": "$ip",
    "mask": "$mask",
    "prefix": $prefix,
    "router": "$router",
    "dns": "$dns",
    "domain": "$domain",
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
