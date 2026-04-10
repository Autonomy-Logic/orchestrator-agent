"""
Self-upgrade script for the orchestrator agent.

This script runs inside a one-shot "upgrader" container spawned by the old
orchestrator. It replaces the old orchestrator container with a new one
using the latest image while preserving all volume mounts and configuration.

Environment variables (set by the upgrade use case):
    UPGRADE_MODE: Must be "true" to proceed
    TARGET_CONTAINER: Name of the old orchestrator container to replace
    NEW_IMAGE: Docker image to use for the new container
    MTLS_HOST_PATH: Host path for mTLS certificates
    SHARED_VOLUME: Docker volume name for shared orchestrator data

This script is designed to be idempotent: if the target container is already
gone (e.g., crashed), it will proceed to create the new one.
"""

import os
import sys
import time
import docker


def main():
    if os.getenv("UPGRADE_MODE") != "true":
        print("ERROR: UPGRADE_MODE is not set. This script should only be run "
              "by the orchestrator upgrade process.")
        sys.exit(1)

    target_container = os.getenv("TARGET_CONTAINER")
    new_image = os.getenv("NEW_IMAGE")
    mtls_host_path = os.getenv("MTLS_HOST_PATH")
    shared_volume = os.getenv("SHARED_VOLUME")

    if not all([target_container, new_image, mtls_host_path, shared_volume]):
        print("ERROR: Missing required environment variables.")
        print(f"  TARGET_CONTAINER={target_container}")
        print(f"  NEW_IMAGE={new_image}")
        print(f"  MTLS_HOST_PATH={mtls_host_path}")
        print(f"  SHARED_VOLUME={shared_volume}")
        sys.exit(1)

    print(f"Orchestrator upgrade starting...")
    print(f"  Target: {target_container}")
    print(f"  New image: {new_image}")
    print(f"  mTLS path: {mtls_host_path}")
    print(f"  Shared volume: {shared_volume}")

    client = docker.from_env()

    # Wait for old orchestrator to finish sending its response
    print("Waiting for old orchestrator to finish responding...")
    time.sleep(3)

    # Stop and remove old orchestrator
    try:
        old = client.containers.get(target_container)
        print(f"Stopping old orchestrator '{target_container}'...")
        old.stop(timeout=15)
        print(f"Removing old orchestrator '{target_container}'...")
        old.remove(force=True)
        print(f"Old orchestrator removed successfully")
    except docker.errors.NotFound:
        print(f"Old orchestrator '{target_container}' already gone, proceeding")
    except Exception as e:
        print(f"ERROR stopping/removing old orchestrator: {e}")
        sys.exit(1)

    # Create new orchestrator container with same configuration
    print(f"Creating new orchestrator container '{target_container}'...")
    try:
        new_container = client.containers.create(
            image=new_image,
            name=target_container,
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            volumes={
                mtls_host_path: {"bind": "/root/.mtls", "mode": "ro"},
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                shared_volume: {"bind": "/var/orchestrator", "mode": "rw"},
            },
        )
        new_container.start()
        print(f"New orchestrator container '{target_container}' started successfully")
    except Exception as e:
        print(f"ERROR creating new orchestrator container: {e}")
        sys.exit(1)

    # Verify the new container is running
    time.sleep(2)
    try:
        check = client.containers.get(target_container)
        check.reload()
        status = check.status
        if status == "running":
            print(f"Upgrade complete! New orchestrator is running.")
        else:
            print(f"WARNING: New orchestrator status is '{status}', expected 'running'")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR verifying new orchestrator: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
