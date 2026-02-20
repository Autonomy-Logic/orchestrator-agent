FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-venv \
    build-essential curl git nano && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements-dev.txt

RUN mkdir -p /var/orchestrator/{logs,debug,data}
