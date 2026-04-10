#!/bin/bash
# Remove the ghcr.io block from /etc/hosts so Docker can pull remote images again.
#
# Usage: sudo bash remove_ghcr_block.sh

if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo bash $0"
    exit 1
fi

if grep -q "ghcr.io" /etc/hosts; then
    sed -i '/ghcr.io/d' /etc/hosts
    echo "Removed ghcr.io block from /etc/hosts"
else
    echo "ghcr.io is not blocked in /etc/hosts"
fi
