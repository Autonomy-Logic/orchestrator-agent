FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-venv \
    build-essential curl git nano && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements.txt

# Ensures the .ssh directory has the correct permissions
RUN mkdir -p /root/.ssh && \
    chmod 700 /root/.ssh

# Ensures the .mtls directory has the correct permissions
RUN mkdir -p /root/.mtls && \
    chmod 700 /root/.mtls

RUN mkdir -p /var/orchestrator/{logs,debug,data}
