from use_cases.docker_manager.create_new_container import run_new_container
from tools.logger import *
from . import topic

NAME = "create_new_runtime"


@topic(NAME)
def init(client):
    """
    Handle the 'create_new_runtime' topic to create a new runtime environment.
    """

    @client.on(NAME)
    async def callback(message):
        container_image = message.get("container_image")
        container_name = message.get("container_name")

        log_info(f"Using image: {container_image}")
        await run_new_container(container_image, container_name)
