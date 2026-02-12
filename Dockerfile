# syntax=docker/dockerfile:1

FROM python:3.11-slim AS base
WORKDIR /app

# Install runtime deps (libsrtp2-1 needed on armv7 where pylibsrtp is built from source)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    libsrtp2-1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# ---------------------------
# Build av shim wheel (pure Python, used only on armv7)
# ---------------------------
FROM python:3.11-slim AS shim-builder
WORKDIR /shim
COPY av-shim/ .
RUN pip wheel --no-deps --wheel-dir /shim-wheels .

# ---------------------------
# Build all dependency wheels
# ---------------------------
FROM base AS builder
ARG TARGETPLATFORM

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    python3-dev \
    libsrtp2-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=shim-builder /shim-wheels /shim-wheels

RUN if [ "$TARGETPLATFORM" = "linux/arm/v7" ]; then \
      pip wheel --no-cache-dir --wheel-dir /wheels \
        --find-links /shim-wheels --only-binary av \
        -r requirements.txt; \
    else \
      pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt; \
    fi

# ---------------------------
# Final image
# ---------------------------
FROM base AS final

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*

ENV HOST_NAME=orchestrator_agent

# Copy source code
COPY src/ ./src

# Default execution
CMD ["python", "src/index.py"]
