from tools.logger import *
from tools.contract_validation import BASE_MESSAGE, StringType
from use_cases.get_consumption_orchestrator import get_consumption_orchestrator_data
from . import topic, validate_message, with_response

NAME = "get_consumption_orchestrator"

MESSAGE_TYPE = {**BASE_MESSAGE, "cpuPeriod": StringType, "memoryPeriod": StringType}


@topic(NAME)
def init(client, ctx):
    """
    Handle the 'get_consumption_orchestrator' topic to send consumption data.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME)
    @with_response(NAME)
    async def callback(message):
        log_debug(f"Received get_consumption_orchestrator request: {message}")

        result = get_consumption_orchestrator_data(
            message.get("cpuPeriod", "1h"),
            message.get("memoryPeriod", "1h"),
            static_system_info=ctx.static_system_info,
            usage_buffer=ctx.usage_buffer,
            network_interface_cache=ctx.network_interface_cache,
        )

        log_debug(
            f"Returning get_consumption_orchestrator response with "
            f"{len(result['cpu_usage'])} CPU samples and {len(result['memory_usage'])} memory samples"
        )
        return result
