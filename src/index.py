## Main Execution Script
from controllers import main_websocket_task
from tools.logger import *
import argparse
import asyncio
from time import sleep

## AWS Dummy Server Address
SERVER_HOST = "api.getedge.me"

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

    while True:
        try:
            log_info(f"Attempting to connect to server at {SERVER_HOST}...")
            asyncio.run(main_websocket_task(SERVER_HOST))
        except KeyboardInterrupt:
            log_warning("Keyboard interrupt received. Closing connection and exiting.")
            break
        except Exception as e:
            log_error(f"Error on websocket interface: {e}")
        log_warning("Reconnecting in 1 second...")
        sleep(1)
