from use_cases.docker_manager.create_new_container import run_new_container
from tools.logger import *
from tools.contract_validation import StringType, validate_contract
from . import topic

NAME = "create_new_runtime"

MESSAGE_TYPE = {"container_image": StringType, "container_name": StringType}


@topic(NAME)
def init(client):
    """
    Handle the 'create_new_runtime' topic to create a new runtime environment.
    """

    @client.on(NAME)
    async def callback(message):
        try:
            validate_contract(MESSAGE_TYPE, message)
        except Exception as e:
            log_error(f"Contract validation error: {e}")
            return

        container_image = message.get("container_image")
        container_name = message.get("container_name")

        log_info(f"Using image: {container_image}")
        await run_new_container(container_image, container_name)
