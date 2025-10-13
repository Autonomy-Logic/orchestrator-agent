from tools.logger import *

NAME = "connection_info"
SUCCESS = "connection.established"


def callback(event, _, connected_at):
    if event == "connection.established":
        log_info("Connection established successfully at " + connected_at)
    else:
        log_warning(f"Unknown event: {event}")
