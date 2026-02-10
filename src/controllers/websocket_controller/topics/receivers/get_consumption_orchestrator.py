from tools.logger import *
from tools.contract_validation import BASE_MESSAGE, StringType
from use_cases.get_consumption_orchestrator import get_consumption_orchestrator_data
from . import topic, validate_message

NAME = "get_consumption_orchestrator"

MESSAGE_TYPE = {**BASE_MESSAGE, "cpuPeriod": StringType, "memoryPeriod": StringType}


@topic(NAME)
def init(client):
    """
    Handle the 'get_consumption_orchestrator' topic to send consumption data.
    """

    @client.on(NAME)
    @validate_message(MESSAGE_TYPE, NAME)
    async def callback(message):
        log_debug(f"Received get_consumption_orchestrator request: {message}")

        result = get_consumption_orchestrator_data(
            message.get("cpuPeriod", "1h"),
            message.get("memoryPeriod", "1h"),
        )

        log_debug(
            f"Returning get_consumption_orchestrator response with "
            f"{len(result['cpu_usage'])} CPU samples and {len(result['memory_usage'])} memory samples"
        )
        return {"action": NAME, "correlation_id": message.get("correlation_id"), **result}
