from tools.logger import log_debug
from tools.contract_validation import BASE_MESSAGE
from use_cases.get_orchestrator_version import get_orchestrator_version
from . import topic, validate_message, with_response

NAME = "get_orchestrator_version"

MESSAGE_TYPE = {**BASE_MESSAGE}


@topic(NAME)
def init(client, ctx):
    """
    Handle the 'get_orchestrator_version' topic to return version information
    for the orchestrator agent and netmon sidecar.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME)
    @with_response(NAME)
    async def callback(message):
        log_debug("Received get_orchestrator_version request")

        result = get_orchestrator_version(
            container_runtime=ctx.container_runtime,
        )

        return {"status": "success", **result}
