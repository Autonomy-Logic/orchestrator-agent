#!/usr/bin/env bash
set -euo pipefail

### --- CONFIGURATION --- ###
IMAGE_NAME="hello-world"                       # <-- change to your desired image
CONTAINER_NAME="custom_container"              # <-- change to your desired container name
SERVER_DNS="server-dns"                        # <-- change to your desired server DNS
SERVER_URL="https://$SERVER_DNS/orchestrator"
GET_ID_URL="$SERVER_URL/id"
UPLOAD_CERT_URL="$SERVER_URL/register-certificate"
MTLS_DIR="$HOME/.mtls"
KEY_PATH="$MTLS_DIR/client.key"
CRT_PATH="$MTLS_DIR/client.crt"

### --- OS CHECK --- ###
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
  echo "[ERROR] This script supports Linux only. Aborting."
  exit 1
fi

### --- DEPENDENCIES --- ###
echo "Checking and installing required dependencies..."
PKG_MANAGER=""

# Detect package manager
if command -v apt-get &>/dev/null; then
  PKG_MANAGER="apt-get"
elif command -v dnf &>/dev/null; then
  PKG_MANAGER="dnf"
elif command -v yum &>/dev/null; then
  PKG_MANAGER="yum"
else
  echo "[ERROR] No supported package manager found (apt, dnf, or yum). Install dependencies manually."
  exit 1
fi

MISSING_PKGS=()
for cmd in curl jq openssl; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "Missing dependency: $cmd"
    MISSING_PKGS+=("$cmd")
  else
    echo "[SUCCESS] $cmd is already installed."
  fi
done

if [ ${#MISSING_PKGS[@]} -ne 0 ]; then
  echo "Updating package lists and installing missing dependencies: ${MISSING_PKGS[*]}"
  sudo "$PKG_MANAGER" update -y >/dev/null 2>&1 || true
  sudo "$PKG_MANAGER" install -y "${MISSING_PKGS[@]}"
fi
### --- STEP 1: CHECK DOCKER INSTALLATION --- ###
echo "Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing..."
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable docker
    sudo systemctl start docker
else
    echo "[SUCCESS] Docker is already installed."
fi

### --- STEP 2: SETUP USER PERMISSIONS --- ###
echo "Setting up Docker user permissions..."
if ! getent group docker &>/dev/null; then
    sudo groupadd docker
fi
sudo usermod -aG docker "$USER"
echo "[INFO]  You may need to log out and log back in for group permissions to take effect."

### --- STEP 3: PULL IMAGE AND CREATE CONTAINER --- ###
echo "Pulling Docker image: $IMAGE_NAME"
docker pull "$IMAGE_NAME"

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Existing container detected. Restarting..."
    docker restart "$CONTAINER_NAME"
else
    echo "Creating new container: $CONTAINER_NAME"
    docker run -d --name "$CONTAINER_NAME" "$IMAGE_NAME"
fi

### --- STEP 4: REQUEST CUSTOM ID --- ###
echo "Requesting ID from $GET_ID_URL..."
response=$(curl -fsSL "$GET_ID_URL")

# Validate JSON format
if ! echo "$response" | jq empty 2>/dev/null; then
  echo "[ERROR] Invalid server response: not JSON."
  echo "$response"
  exit 1
fi

CUSTOM_ID=$(echo "$response" | jq -r '.data.id')
EXPIRES_AT=$(echo "$response" | jq -r '.data.expiresAt')
EXPIRES_IN=$(echo "$response" | jq -r '.data.expiresIn')

if [[ -z "$CUSTOM_ID" || "$CUSTOM_ID" == "null" ]]; then
  echo "[ERROR] Failed to retrieve ID from server."
  exit 1
fi

echo "[SUCCESS] Received ID: $CUSTOM_ID (expires in $EXPIRES_IN seconds, at $EXPIRES_AT)"

### --- STEP 5: GENERATE CLIENT CERTIFICATE --- ###
echo "Generating mTLS certificate for ID: $CUSTOM_ID"
mkdir -p "$MTLS_DIR"
chmod 700 "$MTLS_DIR"

openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout "$KEY_PATH" \
  -out "$CRT_PATH" \
  -subj "/C=BR/ST=SP/L=SaoPaulo/O=AutonomyLogic/OU=Development/CN=${CUSTOM_ID}" \
  -days 365 >/dev/null 2>&1
chmod 600 "$KEY_PATH"

echo "[SUCCESS] Certificate generated: $CRT_PATH"

### --- STEP 6: UPLOAD CERTIFICATE --- ###
echo "Uploading certificate to $UPLOAD_CERT_URL..."
upload_response=$(curl -s -w "%{http_code}" -o /tmp/upload_resp.json \
  -X POST "$UPLOAD_CERT_URL" \
  -F "certificate=@$CRT_PATH")

if [[ "$upload_response" -ne 200 ]]; then
  echo "[ERROR] Upload failed. HTTP code: $upload_response"
  echo "Server response:"
  cat /tmp/upload_resp.json
  echo "\n"
  exit 1
fi

# Extract fields from response JSON
message=$(jq -r '.data.message' /tmp/upload_resp.json)
status=$(jq -r '.data.status' /tmp/upload_resp.json)
id_resp=$(jq -r '.data.id' /tmp/upload_resp.json)

if [[ "$status" != "pending_confirmation" ]]; then
  echo "[WARNING] Unexpected server status: $status"
  cat /tmp/upload_resp.json
  echo
  exit 1
fi

echo "[SUCCESS] Upload completed: $message (ID: $id_resp)"

### --- STEP 7: RESTART CONTAINER --- ###
echo "Restarting container: $CONTAINER_NAME"
docker restart "$CONTAINER_NAME" >/dev/null
echo "[SUCCESS] Container successfully restarted."

echo "[SUCCESS] All steps completed successfully!"
