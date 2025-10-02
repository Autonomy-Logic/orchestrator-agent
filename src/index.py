## Main Execution Script
from controllers.websocket_controller import (
    init as init_websocket_controller,
    main as main_websocket_controller,
)
from tools.logger import *
import argparse
import asyncio
from time import sleep

## AWS Dummy Server Address
SERVER_HOST = "ec2-18-119-156-107.us-east-2.compute.amazonaws.com"

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

    ## First test script
    init_websocket_controller()

    while True:
        try:
            log_info(f"Attempting to connect to server at {SERVER_HOST}:7676...")
            asyncio.run(main_websocket_controller(host=SERVER_HOST, port=7676))
        except KeyboardInterrupt:
            log_warning("Keyboard interrupt received. Closing connection and exiting.")
            break
        except Exception as e:
            log_error("Error connecting to server. Retrying...")
        sleep(1)
