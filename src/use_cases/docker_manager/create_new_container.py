from . import CLIENT
from tools.logger import *


def run_new_container(image_name: str, container_name: str):
    """
    Function to run a new container with the specified image.
    """

    log_debug(
        f'Attempting to run a new container "{container_name}" with image: {image_name}'
    )

    try:
        CLIENT.containers.run(
            image=image_name,
            name=container_name,
        )
        log_info(f"Container {container_name} created successfully")
    except Exception as e:
        log_error(f"Failed to create container {container_name}. Error: {e}")
