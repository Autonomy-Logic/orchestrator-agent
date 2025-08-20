import json
from quart import Quart, websocket, send_file

CLIENT_TIMEOUT = 10

app = Quart(__name__)

CLIENTS = {}
TOPICS = []


# ---------------- HTTP ROUTES ----------------
@app.route("/root", methods=["GET"])
async def root():
    return await send_file("index.html")


@app.route("/create_container/<client_id>", methods=["GET"])
async def create_container(client_id):
    if client_id in CLIENTS:
        message = json.dumps({
            "topic": "create_new_runtime",
            "payload": {
                "container_image": "hello-world",
                "container_name": "hw-test-container"
            }
        })
        ws = CLIENTS[client_id]
        await ws.send(message)
        return f"Request to create container sent for client {client_id}."
    else:
        return f"No active connection for client {client_id}.", 404


# ---------------- TOPICS ----------------
class Topic:
    def __init__(self, name: str, callback: callable):
        self._name = name
        self._callback = callback

    def name(self) -> str:
        return self._name

    async def callback(self, **kwargs):
        return await self._callback(**kwargs)


def register_topic(name: str, callback: callable) -> None:
    topic = Topic(name, callback)
    TOPICS.append(topic)
    print(f"TLS Interface: Registered new topic: {name}")


async def handle_topic(name: str, **kwargs):
    for topic in TOPICS:
        if topic.name() == name:
            print(f"TLS Interface: Handling topic: {name} with args: {kwargs}")
            return await topic.callback(**kwargs)
    print(f"TLS Interface: No topic found with name: {name}")
    return None


# ---------------- WEBSOCKET ----------------
async def handle_heartbeat(ws, client_id, **kwargs):
    CLIENTS[client_id] = ws
    print(f"Heartbeat received:\n{json.dumps(kwargs, indent=2)}")


@app.websocket("/")
async def ws_handler():
    ws = websocket._get_current_object()
    try:
        while True:
            message = await ws.receive()
            try:
                message_data = json.loads(message)
                topic_name = message_data.get("topic")
                payload = message_data.get("payload", {})

                if topic_name == "heartbeat":
                    if "id" in payload:
                        await handle_heartbeat(ws, payload["id"], **payload)
                    else:
                        print(f"Skipping unidentified heartbeat message: {message}")
                else:
                    print(f"Received message for topic: {topic_name}.")
                    await handle_topic(topic_name, **payload)

            except json.JSONDecodeError as e:
                print(f"Failed to decode message. Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred. Error: {e}")

    except Exception as e:
        print(f"WebSocket closed: {e}")


# ---------------- INIT ----------------
async def dummy_callback(**kwargs):
    print("This server can only publish to this topic", kwargs)


def init():
    print("Initializing TLS Controller...")
    register_topic("create_new_runtime", dummy_callback)
    print("TLS Controller initialized successfully.")


# ---------------- MAIN ----------------
if __name__ == "__main__":
    init()
    app.run(host="0.0.0.0", port=7676, debug=True)
