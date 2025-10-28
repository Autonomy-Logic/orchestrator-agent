from tools.logger import *


def topic(name):
    """
    Decorator to register a topic handler.
    """

    def wrapper(init):
        log_info(f"Registering topic: {name}")
        return init

    return wrapper
