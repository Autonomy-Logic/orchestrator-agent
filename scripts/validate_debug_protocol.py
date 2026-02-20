#!/usr/bin/env python3
"""
Standalone script to validate the OpenPLC debug protocol.

Connects to an OpenPLC-Runtime container, authenticates, opens a debug
session, sends each protocol command, and logs the raw responses.

Usage:
    python scripts/validate_debug_protocol.py <runtime_ip> [options]

Examples:
    python scripts/validate_debug_protocol.py 172.18.0.2
    python scripts/validate_debug_protocol.py 172.18.0.2 --username openplc --password openplc
    python scripts/validate_debug_protocol.py 172.18.0.2 --port 8443
"""

import argparse
import json
import logging
import os
import sys

# Add src/ to path so imports work when running the script directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from repos.debug_socket_repo import DebugSocketRepo
from repos.http_client_repo import HTTPClientRepo
from use_cases.debug_client.validate_session import validate_debug_session
from tools.logger import set_log_level


def main():
    parser = argparse.ArgumentParser(
        description="Validate the OpenPLC debug protocol against a runtime container."
    )
    parser.add_argument("ip", help="Runtime container IP address")
    parser.add_argument(
        "--username",
        default="openplc",
        help="Runtime login username (default: openplc)",
    )
    parser.add_argument(
        "--password",
        default="openplc",
        help="Runtime login password (default: openplc)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8443,
        help="Runtime HTTPS port (default: 8443)",
    )
    args = parser.parse_args()

    set_log_level(logging.DEBUG)

    http_client = HTTPClientRepo()
    debug_socket = DebugSocketRepo()

    result = validate_debug_session(
        device_ip=args.ip,
        username=args.username,
        password=args.password,
        http_client=http_client,
        debug_socket=debug_socket,
        port=args.port,
    )

    print("\n" + "=" * 60)
    print("VALIDATION RESULT")
    print("=" * 60)
    print(json.dumps(result, indent=2))

    sys.exit(0 if result.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
