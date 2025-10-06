from . import make_request


def execute(instance, command):
    method = command.get("method")
    api = command.get("api")
    headers = command.get("headers", {})
    ip = instance.get("ip")
    content_type = headers.get("content_type", "application/json")

    content = {"headers": headers}

    if content_type == "application/json":
        content["json"] = command.get("data", {})
    else:
        content["data"] = command.get("data", {})

    return make_request(method, ip, 8080, api, content)
