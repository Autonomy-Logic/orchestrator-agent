from tools.logger import *


class Topic:
    def __init__(self, name: str, callback: callable):
        self.__name = name
        self.__callback = callback

    def name(self) -> str:
        return self.__name

    async def callback(self, **kwargs) -> callable:
        return self.__callback(**kwargs)


TOPICS: list[Topic] = []


def register_topic(name: str, callback: callable) -> None:
    topic = Topic(name, callback)
    TOPICS.append(topic)
    log_info(f"Websocket Interface: Registered new topic: {name}")


async def handle_topic(name: str, **kwargs) -> None:
    for topic in TOPICS:
        if topic.name() == name:
            log_debug(
                f"Websocket Interface: Handling topic: {name} with args: {kwargs}"
            )
            return await topic.callback(**kwargs)
    log_warning(f"Websocket Interface: No topic found with name: {name}")
    return None
