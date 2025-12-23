#!/usr/bin/env bash
set -euo pipefail

### --- OS CHECK --- ###
if [[ $OSTYPE != linux-gnu* ]]; then
  echo "[ERROR] This script supports Linux only. Aborting."
  exit 1
fi

# --- Auto-save if running from a pipe ---
if [ -p /dev/stdin ]; then
  TMP_SCRIPT="/tmp/install-edge.sh"
  echo "[INFO] Detected script running from a pipe. Saving to $TMP_SCRIPT..."
  cat >"$TMP_SCRIPT"
  chmod +x "$TMP_SCRIPT"

  echo "[INFO] Re-running saved script..."
  exec /usr/bin/env bash "$TMP_SCRIPT" "$@"
fi

### --- CONFIGURATION --- ###
IMAGE_NAME="ghcr.io/autonomy-logic/orchestrator-agent:latest"
NETMON_IMAGE_NAME="ghcr.io/autonomy-logic/autonomy-netmon:latest"
CONTAINER_NAME="orchestrator_agent"
NETMON_CONTAINER_NAME="autonomy_netmon"
SOURCE_DIR="/tmp/orchestrator-agent"
SHARED_VOLUME="orchestrator-shared"
SERVER_DNS="api.autonomylogic.com"
SERVER_URL="https://$SERVER_DNS"
GET_ID_URL="$SERVER_URL/orchestrators/id"
ENROLL_URL="$SERVER_URL/orchestrators/enroll"
MTLS_DIR="$HOME/.mtls"
KEY_PATH="$MTLS_DIR/client.key"
CRT_PATH="$MTLS_DIR/client.crt"
CSR_PATH="$MTLS_DIR/client.csr"
CSR_CONFIG_FILE="$MTLS_DIR/client.conf"

# Cleanup function for trap - ensures temp files are removed on exit
cleanup_temp_files() {
  rm -f "${CSR_PATH:-}" "${CSR_CONFIG_FILE:-}" /tmp/enroll_resp.json 2>/dev/null || true
}
trap cleanup_temp_files EXIT

# Check for root privileges
check_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "[INFO] Root privileges are required. Trying to elevate with sudo..."
    # Re-run the script with sudo, passing all original arguments
    exec sudo /usr/bin/env bash "$0" "$@"
    # exec replaces the current shell with the new command, so the rest of the script continues as root
  fi
}

# Make sure we are root before proceeding
check_root "$@"

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
  echo "Required packages: curl, jq, openssl, docker"
  echo "Attempting to continue without automatic dependency installation..."
  PKG_MANAGER="none"
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
    if [[ -n "${PKG_MAP[$cmd]}" ]]; then
      MISSING_PKGS+=("${PKG_MAP[$cmd]}")
    fi
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
  none)
    echo "[ERROR] Cannot install dependencies automatically. Please install: ${MISSING_PKGS[*]}"
    exit 1
    ;;
  esac
fi

echo "Creating shared volume for container communication..."
if docker volume inspect "$SHARED_VOLUME" &>/dev/null; then
  echo "[SUCCESS] Shared volume $SHARED_VOLUME already exists"
else
  docker volume create "$SHARED_VOLUME"
  echo "[SUCCESS] Created shared volume $SHARED_VOLUME"
fi

### --- DEPLOY NETWORK MONITOR SIDECAR --- ###
echo "Deploying network monitor sidecar container..."

if docker pull "$NETMON_IMAGE_NAME" 2>/dev/null; then
  echo "[SUCCESS] Pulled network monitor image: $NETMON_IMAGE_NAME"
else
  echo "[WARNING] No prebuilt netmon image found. Falling back to local build..."

  if [ -d "$SOURCE_DIR/.git" ]; then
    echo "Updating existing source clone..."
    if ! git -C "$SOURCE_DIR" pull --rebase; then
      echo "Pull failed, stashing local changes and retrying..."
      git -C "$SOURCE_DIR" stash push --include-untracked -m "installer-auto-stash $(date +%s)" || true
      if ! git -C "$SOURCE_DIR" pull --rebase; then
        echo "[ERROR] git pull still failing after stash. Please inspect $SOURCE_DIR."
        exit 1
      fi
    fi
  else
    echo "Cloning source to $SOURCE_DIR..."
    git clone https://github.com/autonomy-logic/orchestrator-agent.git "$SOURCE_DIR"
  fi

  echo "Building network monitor image locally..."
  docker build -t "$NETMON_IMAGE_NAME" -f "$SOURCE_DIR/install/Dockerfile.netmon" "$SOURCE_DIR/install"

  echo "[SUCCESS] Local netmon build completed: $NETMON_IMAGE_NAME"
fi

if docker ps -a --format '{{.Names}}' | grep -q "^${NETMON_CONTAINER_NAME}$"; then
  echo "Removing existing network monitor container..."
  docker rm -f "$NETMON_CONTAINER_NAME"
fi


docker run -d \
  --name "$NETMON_CONTAINER_NAME" \
  --network=host \
  --pid=host \
  --cap-add=NET_ADMIN \
  --cap-add=NET_RAW \
  --cap-add=SYS_ADMIN \
  --cap-add=SYS_PTRACE \
  --restart unless-stopped \
  -v "$SHARED_VOLUME:/var/orchestrator" \
  "$NETMON_IMAGE_NAME"

echo "[SUCCESS] Network monitor sidecar started"

### --- STEP 1: PULL ORCHESTRATOR AGENT IMAGE AND CREATE CONTAINER --- ###
echo "Pulling Docker image: $IMAGE_NAME"
if docker pull "$IMAGE_NAME"; then
  echo "Pulled image: $IMAGE_NAME"
else
  echo "[WARNING] No prebuilt image found for this host architecture. Falling back to local build..."
  # Clone or update the source tree
  if [ -d "$SOURCE_DIR/.git" ]; then
    echo "Updating existing source clone..."
    if ! git -C "$SOURCE_DIR" pull --rebase; then
      echo "Pull failed, stashing local changes and retrying..."
      git -C "$SOURCE_DIR" stash push --include-untracked -m "installer-auto-stash $(date +%s)" || true
      if ! git -C "$SOURCE_DIR" pull --rebase; then
        echo "[ERROR] git pull still failing after stash. Please inspect $SOURCE_DIR."
        exit 1
      fi
    fi
  else
    echo "Cloning source to $SOURCE_DIR..."
    git clone https://github.com/autonomy-logic/orchestrator-agent.git "$SOURCE_DIR"
  fi

  # Build locally for the host architecture
  # Use 'docker build' which builds for the local machine arch (simplest and most reliable for fallback)
  echo "Building Docker image locally for this host architecture..."
  docker build -t "$IMAGE_NAME" "$SOURCE_DIR"

  echo "Local build completed: $IMAGE_NAME"
fi

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Existing container detected. Removing and recreating..."
  docker rm -f "$CONTAINER_NAME"
fi

echo "Creating new container: $CONTAINER_NAME"
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -v "$MTLS_DIR:/root/.mtls:ro" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$SHARED_VOLUME:/var/orchestrator" \
  "$IMAGE_NAME"

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

### --- STEP 3: GENERATE CLIENT KEY AND CSR --- ###
echo "Generating client key and certificate signing request..."
mkdir -p "$MTLS_DIR"
chmod 700 "$MTLS_DIR"

echo ""
echo "Generating client certificate for orchestrator ID: $CUSTOM_ID"
echo ""

# STEP 3.1: Generate client private key
echo "--- 1. Generating client private key ---"
if ! openssl genrsa -out "$KEY_PATH" 4096 2>/dev/null; then
  echo "[ERROR] Failed to generate client private key. Aborting."
  exit 1
fi
chmod 600 "$KEY_PATH"
echo "Client private key generated: $KEY_PATH"

# STEP 3.2: Create CSR configuration file
echo "--- 2. Creating CSR configuration ---"
cat << EOF > "$CSR_CONFIG_FILE"
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C=BR
ST=SP
L=SaoPaulo
O=AutonomyLogic
OU=Production
CN=${CUSTOM_ID}

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = clientAuth
EOF

echo "CSR configuration created"

# STEP 3.3: Generate CSR (Certificate Signing Request)
echo "--- 3. Generating Certificate Signing Request (CSR) ---"
openssl req -new \
  -key "$KEY_PATH" \
  -out "$CSR_PATH" \
  -config "$CSR_CONFIG_FILE" 2>/dev/null

echo "CSR generated: $CSR_PATH"

### --- STEP 4: ENROLL WITH SERVER (CSR SIGNING) --- ###
echo "--- 4. Submitting CSR to server for signing ---"
echo "Enrolling with $ENROLL_URL..."
http_code=$(curl -sS -w "%{http_code}" -o /tmp/enroll_resp.json \
  -X POST "$ENROLL_URL" \
  -F "csr=@$CSR_PATH") || {
  echo "[ERROR] Enrollment request failed. Please check network connectivity."
  exit 1
}

if [[ -z "$http_code" || ! "$http_code" =~ ^[0-9]{3}$ ]]; then
  echo "[ERROR] Invalid HTTP response code received: $http_code"
  exit 1
fi

if [[ "$http_code" -ne 200 ]]; then
  echo "[ERROR] Enrollment failed. HTTP code: $http_code"
  echo "Server response:"
  cat /tmp/enroll_resp.json
  echo
  exit 1
fi

# Extract certificate from response JSON
certificate=$(jq -r '.data.certificate' /tmp/enroll_resp.json)
message=$(jq -r '.data.message' /tmp/enroll_resp.json)
id_resp=$(jq -r '.data.id' /tmp/enroll_resp.json)
status=$(jq -r '.statusCode' /tmp/enroll_resp.json)

if [[ "$status" != "200" ]]; then
  echo "[WARNING] Unexpected server status: $status"
  cat /tmp/enroll_resp.json
  echo
  exit 1
fi

if [[ -z "$certificate" || "$certificate" == "null" ]]; then
  echo "[ERROR] No certificate received from server"
  cat /tmp/enroll_resp.json
  echo
  exit 1
fi

# Save the signed certificate
echo "$certificate" > "$CRT_PATH"
chmod 644 "$CRT_PATH"
echo "Client certificate signed and saved: $CRT_PATH"

# Verify the certificate has correct extensions for mTLS client auth
echo "--- 5. Verifying certificate extensions ---"
if ! openssl x509 -in "$CRT_PATH" -noout -purpose 2>/dev/null | grep -q "SSL client : Yes"; then
  echo "[ERROR] Server returned a certificate that is not valid for SSL client authentication."
  echo "This may indicate a server misconfiguration. Please contact support."
  exit 1
fi
echo "Certificate verified: valid for SSL client authentication"

# Note: Temporary files (CSR, config, response) are cleaned up automatically by trap handler

echo ""
echo "CERTIFICATE ENROLLMENT COMPLETE!"
echo "=================================================="
echo "Files created:"
echo "   - Client key:         $KEY_PATH"
echo "   - Client certificate: $CRT_PATH"
echo ""
echo "   Valid until:"
openssl x509 -in "$CRT_PATH" -noout -enddate
echo ""
echo "   Fingerprint SHA256:"
openssl x509 -in "$CRT_PATH" -noout -fingerprint -sha256
echo ""
echo "=================================================="
echo ""

echo "[SUCCESS] Enrollment completed: $message (ID: $id_resp)"

### --- STEP 6: RESTART CONTAINER --- ###
echo "Restarting container: $CONTAINER_NAME"
docker restart "$CONTAINER_NAME" >/dev/null
echo "[SUCCESS] Container successfully restarted."

# Detect color support
if [ -t 1 ] && command -v tput >/dev/null && [ "$(tput colors 2>/dev/null)" -ge 8 ]; then
  GREEN="$(tput setaf 2)"
  CYAN="$(tput setaf 6)"
  YELLOW="$(tput setaf 3)"
  GRAY="$(tput setaf 8)"
  BOLD="$(tput bold)"
  RESET="$(tput sgr0)"
else
  GREEN=""
  CYAN=""
  YELLOW=""
  GRAY=""
  BOLD=""
  RESET=""
fi

echo
echo
echo -e "${BOLD}${GREEN}INSTALLATION COMPLETE${RESET}"
echo -e "${GRAY}=====================================================${RESET}"
echo
echo -e "Orchestrator ID: ${BOLD}${CYAN}${CUSTOM_ID}${RESET}"
echo -e "Expires in: ${YELLOW}${EXPIRES_IN} seconds${RESET} (at ${YELLOW}${EXPIRES_AT}${RESET})"
echo
echo "Copy the Orchestrator ID above and paste it into the "
echo "Autonomy Edge app to link your device."
echo -e "${GRAY}=====================================================${RESET}"
