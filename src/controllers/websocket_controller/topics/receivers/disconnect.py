from tools.logger import *
from . import topic

NAME = "disconnect"


@topic(NAME)
def init(client):
    """
    Handle the 'disconnect' topic to log connection ending.
    """

    @client.on(NAME)
    async def callback():
        log_info("Connection ended by the server.")
