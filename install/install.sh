#!/usr/bin/env bash
set -euo pipefail

### --- CONFIGURATION --- ###
IMAGE_NAME="hello-world"                                      # <-- change to your desired image
CONTAINER_NAME="custom_container"                             # <-- change to your desired container name
SERVER_DNS="tegcayxzurngxjwexsha.supabase.co/functions/v1"    # <-- change to your desired server DNS
SERVER_URL="https://$SERVER_DNS"
GET_ID_URL="$SERVER_URL/generate-orchestrator-id"
UPLOAD_CERT_URL="$SERVER_URL/upload-orchestrator-certificate"
MTLS_DIR="$HOME/.mtls"
KEY_PATH="$MTLS_DIR/client.key"
CRT_PATH="$MTLS_DIR/client.crt"

### --- OS CHECK --- ###
if [[ $OSTYPE != linux-gnu* ]]; then
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

# Define package names per package manager
declare -A PKG_MAP
if [[ "$PKG_MANAGER" == "apt-get" ]]; then
  PKG_MAP=(
    [curl]="curl"
    [jq]="jq"
    [openssl]="openssl"
    [docker]="docker.io"
  )
elif [[ "$PKG_MANAGER" == "dnf" ]]; then
  PKG_MAP=(
    [curl]="curl"
    [jq]="jq"
    [openssl]="openssl"
    [docker]="docker"
  )
elif [[ "$PKG_MANAGER" == "yum" ]]; then
  PKG_MAP=(
    [curl]="curl"
    [jq]="jq"
    [openssl]="openssl"
    [docker]="docker"
  )
fi

# Collect missing packages
MISSING_PKGS=()
for cmd in curl jq openssl docker; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "Missing dependency: $cmd"
    MISSING_PKGS+=("${PKG_MAP[$cmd]}")
  else
    echo "[SUCCESS] $cmd is already installed."
  fi
done

# Install missing packages
if [ ${#MISSING_PKGS[@]} -ne 0 ]; then
  echo "Updating package lists and installing missing dependencies: ${MISSING_PKGS[*]}"
  case "$PKG_MANAGER" in
    apt-get)
      sudo apt-get update -y
      sudo apt-get install -y "${MISSING_PKGS[@]}"
      ;;
    dnf)
      sudo dnf install -y "${MISSING_PKGS[@]}"
      ;;
    yum)
      sudo yum install -y "${MISSING_PKGS[@]}"
      ;;
  esac
fi

### --- STEP 1: PULL IMAGE AND CREATE CONTAINER --- ###
echo "Pulling Docker image: $IMAGE_NAME"
docker pull "$IMAGE_NAME"

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Existing container detected. Restarting..."
    docker restart "$CONTAINER_NAME"
else
    echo "Creating new container: $CONTAINER_NAME"
    docker run -d --name "$CONTAINER_NAME" "$IMAGE_NAME"
fi

### --- STEP 2: REQUEST CUSTOM ID --- ###
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

### --- STEP 3: GENERATE CLIENT CERTIFICATE --- ###
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

### --- STEP 5: UPLOAD CERTIFICATE --- ###
echo "Uploading certificate to $UPLOAD_CERT_URL..."
upload_response=$(curl -s -w "%{http_code}" -o /tmp/upload_resp.json \
  -X POST "$UPLOAD_CERT_URL" \
  -F "certificate=@$CRT_PATH" \
  -F "id=$CUSTOM_ID")

if [[ "$upload_response" -ne 200 ]]; then
  echo "[ERROR] Upload failed. HTTP code: $upload_response"
  echo "Server response:"
  cat /tmp/upload_resp.json
  echo
  exit 1
fi

# Extract fields from response JSON
message=$(jq -r '.data.message' /tmp/upload_resp.json)
status=$(jq -r '.statusCode' /tmp/upload_resp.json)
id_resp=$(jq -r '.data.id' /tmp/upload_resp.json)

if [[ $status != 200 ]]; then
  echo "[WARNING] Unexpected server status: $status"
  cat /tmp/upload_resp.json
  echo
  exit 1
fi

echo "[SUCCESS] Upload completed: $message (ID: $id_resp)"

### --- STEP 6: RESTART CONTAINER --- ###
echo "Restarting container: $CONTAINER_NAME"
docker restart "$CONTAINER_NAME" >/dev/null
echo "[SUCCESS] Container successfully restarted."

echo "[SUCCESS] All steps completed successfully!"
