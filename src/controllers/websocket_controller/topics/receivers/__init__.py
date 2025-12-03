from functools import wraps
from datetime import datetime
from tools.logger import *
from tools.contract_validation import validate_contract_with_error_response


def topic(name):
    """
    Decorator to register a topic handler.
    """

    def wrapper(init):
        log_info(f"Registering topic: {name}")
        return init

    return wrapper


def validate_message(contract, name, add_defaults=False):
    """
    Decorator to validate incoming messages against a contract schema.

    This decorator handles the common validation pattern:
    1. Extracts correlation_id from the message
    2. Optionally adds default values for 'action' and 'requested_at'
    3. Validates the message against the contract
    4. Returns an error response if validation fails
    5. Calls the wrapped function if validation succeeds

    Args:
        contract: The contract schema to validate against
        name: The topic name (used for action field in error responses)
        add_defaults: If True, adds default 'action' and 'requested_at' fields

    Returns:
        Decorator function
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(message, *args, **kwargs):
            correlation_id = message.get("correlation_id")

            if add_defaults:
                if "action" not in message:
                    message["action"] = name
                if "requested_at" not in message:
                    message["requested_at"] = datetime.now().isoformat()

            is_valid, error_response = validate_contract_with_error_response(
                contract, message
            )
            if not is_valid:
                error_response["action"] = name
                error_response["correlation_id"] = correlation_id
                return error_response

            return await func(message, *args, **kwargs)

        return wrapper

    return decorator
