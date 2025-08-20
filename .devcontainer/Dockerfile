FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-venv \
    build-essential curl git nano \
    sudo && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create user 'dev' with passwordless sudo
RUN useradd -m -s /bin/bash dev && \
    echo "dev ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER dev

COPY requirements.txt .
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements.txt

RUN sudo mkdir -p /var/orchestrator && sudo mkdir -p /var/orchestrator/logs && sudo mkdir -p /var/orchestrator/debug
RUN sudo chown -R dev:dev /var/orchestrator