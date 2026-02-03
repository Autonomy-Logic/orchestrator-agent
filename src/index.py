## Main Execution Script
from controllers import run_websocket_with_reconnection
from tools.logger import set_log_level
import argparse
import asyncio

## AWS Server Address
SERVER_HOST = "api.autonomylogic.com:3001"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orchestrator Agent")
    parser.add_argument(
        "-l",
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level (use -l or --log-level)",
    )
    args = parser.parse_args()

    set_log_level(args.log_level)
    run_websocket_with_reconnection(SERVER_HOST, asyncio.run)
