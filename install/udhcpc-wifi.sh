#!/bin/sh
# udhcpc script for WiFi Proxy ARP DHCP
#
# This script is used when obtaining DHCP leases on the host's WiFi interface
# for containers using the Proxy ARP bridge method.
#
# CRITICAL: Unlike the default udhcpc script, this script NEVER configures the
# interface (no "ip addr flush", no "ip addr add", no route changes).
# The WiFi interface already has its own IP managed by the host's network
# manager. Running "ip addr flush" on wlan0 would destroy the host's WiFi
# connection.
#
# This script ONLY writes lease information to a JSON file for netmon to read.
# The actual network configuration (veth pair, proxy ARP, routes) is handled
# by netmon's setup_proxy_arp_bridge() function.
#
# Environment variables set by netmon:
#   ORCH_DHCP_KEY - Unique key for this DHCP client (container_name:vnic_name with : replaced by _)

LEASE_DIR="/var/orchestrator/dhcp"
mkdir -p "$LEASE_DIR"

# Determine lease file name
if [ -n "$ORCH_DHCP_KEY" ]; then
    LEASE_FILE="$LEASE_DIR/${ORCH_DHCP_KEY}.lease"
else
    LEASE_FILE="$LEASE_DIR/${interface}.lease"
fi

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | udhcpc-wifi | $1" >> /var/log/autonomy-netmon.log
}

case "$1" in
    deconfig)
        # NO-OP: Do NOT flush the WiFi interface - it would destroy the host connection
        log "Deconfig for WiFi interface $interface (no-op, preserving host connection)"
        ;;

    bound|renew)
        log "WiFi DHCP lease obtained on $interface: IP=$ip, mask=$mask, router=$router (key=$ORCH_DHCP_KEY)"

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

        # Write lease information ONLY - do NOT configure the interface
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
        log "WiFi lease info written to $LEASE_FILE"
        ;;

    leasefail|nak)
        log "WiFi DHCP lease failed for interface $interface (key=$ORCH_DHCP_KEY)"
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
