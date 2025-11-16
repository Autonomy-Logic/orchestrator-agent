# syntax=docker/dockerfile:1

FROM python:3.11-slim AS base
WORKDIR /app

# Install runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# ---------------------------
# Stage for building wheels on ARMv7
# ---------------------------
FROM base AS builder-armv7

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---------------------------
# Final image
# ---------------------------
FROM base AS final

COPY --from=builder-armv7 /wheels /wheels
RUN pip install --no-cache-dir /wheels/*

# Copy source code
COPY src/ ./src

# Default execution
CMD ["python", "src/index.py"]
