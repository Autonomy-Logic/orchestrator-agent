## Main Execution Script
from controllers import run_websocket_with_reconnection
from tools.logger import set_log_level, log_info, log_debug
import argparse
import asyncio
import docker

## AWS Server Address
SERVER_HOST = "api.autonomylogic.com:3001"

UPGRADER_CONTAINER_NAME = "orchestrator_upgrader"


def cleanup_upgrader_container():
    """Remove the leftover upgrader container from a previous upgrade.

    After a successful upgrade, the one-shot upgrader container exits but
    cannot remove itself. The new orchestrator cleans it up on startup.
    """
    try:
        client = docker.from_env()
        upgrader = client.containers.get(UPGRADER_CONTAINER_NAME)
        upgrader.remove(force=True)
        log_info(f"Cleaned up leftover upgrader container '{UPGRADER_CONTAINER_NAME}'")
    except docker.errors.NotFound:
        pass
    except Exception as e:
        log_debug(f"Could not clean up upgrader container: {e}")


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
    cleanup_upgrader_container()
    run_websocket_with_reconnection(SERVER_HOST, asyncio.run)
