## Main Execution Script
from controllers.tls_controller import (
    init as init_tls_controller,
    main as main_tls_controller,
)
from tools.logger import *
import argparse
import asyncio

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
    init_tls_controller()

    try:
        asyncio.run(main_tls_controller(host=SERVER_HOST, port=7676))
    except KeyboardInterrupt:
        log_warning("Keyboard interrupt received. Closing connection and exiting.")
