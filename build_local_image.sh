#!/bin/bash
# Build orchestrator-agent and autonomy-netmon images locally and block ghcr.io
# so Docker uses the local images instead of pulling from the registry.
#
# Usage: sudo bash build_local_image.sh
#
# To undo: remove the ghcr.io line from /etc/hosts and docker pull the images.

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo bash $0"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Removing existing images ==="
docker rmi ghcr.io/autonomy-logic/orchestrator-agent:latest 2>/dev/null || true
docker rmi ghcr.io/autonomy-logic/autonomy-netmon:latest 2>/dev/null || true
# Remove any dangling images with the same name (different tags/digests)
docker images --filter=reference='ghcr.io/autonomy-logic/orchestrator-agent' -q | xargs -r docker rmi -f 2>/dev/null || true
docker images --filter=reference='ghcr.io/autonomy-logic/autonomy-netmon' -q | xargs -r docker rmi -f 2>/dev/null || true

echo "=== Building orchestrator-agent image ==="
docker build -t ghcr.io/autonomy-logic/orchestrator-agent:latest "$SCRIPT_DIR"

echo "=== Building autonomy-netmon image ==="
docker build -t ghcr.io/autonomy-logic/autonomy-netmon:latest \
    -f "$SCRIPT_DIR/install/Dockerfile.netmon" \
    "$SCRIPT_DIR/install"

echo "=== Blocking ghcr.io in /etc/hosts ==="
if grep -q "ghcr.io" /etc/hosts; then
    echo "ghcr.io already blocked in /etc/hosts"
else
    echo "127.0.0.1 ghcr.io" >> /etc/hosts
    echo "Added ghcr.io block to /etc/hosts"
fi

echo ""
echo "Done. Local images built successfully."
echo "Restart containers manually to use the new images:"
echo "  sudo docker restart autonomy_netmon orchestrator_agent"
echo ""
echo "To undo ghcr.io block: sudo bash remove_ghcr_block.sh"
