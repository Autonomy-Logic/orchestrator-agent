from tools.ssl import ssl_context
from tools.logger import *
import websockets
from .topics import (
    handle_topic,
    register_topic,
    create_new_runtime,
    run_command,
    connection_info,
)
import json
import asyncio
from datetime import datetime


async def send_heartbeat(websocket, ping_interval=5):
    """
    Send a heartbeat message at a regular interval.
    """
    while True:
        await asyncio.sleep(ping_interval)

        heartbeat_message = json.dumps(
            {
                "topic": "heartbeat",
                "payload": {
                    ### Fixed ID for testing purposes
                    "id": "AHYBFN762KMN",
                    "cpu_usage": 0.5,  # Example CPU usage
                    "memory_usage": 256,  # Example memory usage in MB
                    "disk_usage": 1024,  # Example disk usage in MB
                    "timestamp": datetime.now().isoformat(),  # Current timestamp
                },
            }
        )
        try:
            await websocket.send(heartbeat_message)
        except websockets.exceptions.ConnectionClosed:
            break


async def receive_messages(websocket: websockets.ClientConnection):
    while True:
        try:
            message = await websocket.recv()
            message_data = json.loads(message)
            topic_name = message_data.get("topic")
            payload = message_data.get("payload", {})
            log_info(f"Received message for topic: {topic_name}.")
            await handle_topic(topic_name, **payload)
        except websockets.exceptions.ConnectionClosed:
            log_error("Connection closed while receiving messages.")
            break
        except json.JSONDecodeError as e:
            log_error(f"Failed to decode message. Error: {e}")
        except Exception as e:
            log_error(f"An unexpected error occurred. Error: {e}")


async def handler(websocket):
    send_task = asyncio.create_task(send_heartbeat(websocket))
    receive_task = asyncio.create_task(receive_messages(websocket))
    try:
        await asyncio.gather(receive_task)
    except Exception as e:
        send_task.cancel()
        receive_task.cancel()
        log_error(f"An error occurred in the handler: {e}")


async def main(host: str = "localhost", port: int = 7676):
    async with websockets.connect(
        f"wss://{host}:{port}/ws", ssl=ssl_context
    ) as websocket:
        websocket.start_keepalive()
        await handler(websocket)


def init():
    """
    Initialize the Websocket controller by registering necessary topics.
    """
    log_info("Initializing Websocket Controller...")

    # Register any topics or perform any setup needed for the Websocket controller
    register_topic(connection_info.NAME, connection_info.callback)
    register_topic(create_new_runtime.NAME, create_new_runtime.callback)
    register_topic(run_command.NAME, run_command.callback)

    log_info("Websocket Controller initialized successfully.")
