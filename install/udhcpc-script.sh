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
            # Write resolv.conf for the container's network namespace
            : > /etc/resolv.conf
            for server in $dns; do
                echo "nameserver $server" >> /etc/resolv.conf
            done
            if [ -n "$domain" ]; then
                echo "search $domain" >> /etc/resolv.conf
            fi
        fi
        
        # Write lease information to file for netmon to read
        cat > "$LEASE_FILE" << EOF
{
    "interface": "$interface",
    "ip": "$ip",
    "subnet": "$subnet",
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
