import base64
from . import make_request


def execute(instance, command):
    method = command.get("method")
    api = command.get("api")
    headers = command.get("headers", {}) or {}
    ip = instance.get("ip")
    port = command.get("port", 8080)
    content_type = headers.get("Content-Type", "application/json")

    content = {"headers": headers}

    # Handle file uploads
    files = command.get("files")
    if files:
        requests_files = {}
        for field_name, file_info in files.items():
            content_base64 = file_info.get("content_base64")
            if not content_base64:
                continue
            raw_content = base64.b64decode(content_base64)
            filename = file_info.get("filename") or field_name
            mime_type = file_info.get("content_type") or "application/octet-stream"
            requests_files[field_name] = (filename, raw_content, mime_type)
        
        if requests_files:
            content["files"] = requests_files
            # Allow additional form fields via "data" when uploading files
            data = command.get("data")
            if data:
                content["data"] = data
    else:
        if content_type == "application/json":
            content["json"] = command.get("data", {})
        else:
            content["data"] = command.get("data", {})

    return make_request(method, ip, port, api, content)
