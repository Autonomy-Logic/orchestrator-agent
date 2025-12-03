import base64
from . import make_request


def execute(instance, command):
    """
    Execute an HTTP command on a runtime instance.

    Args:
        instance: Dictionary containing instance info (ip, name)
        command: Dictionary containing:
            - method: HTTP method (GET, POST, PUT, DELETE)
            - api: API endpoint path
            - port (optional): Target port (defaults to 8443 for openplc-runtime)
            - headers (optional): HTTP headers
            - data (optional): Request body data
            - params (optional): Query parameters

    Returns:
        Dictionary with status_code, headers, body, ok, and content_type
    """
    method = command.get("method")
    api = command.get("api")
    port = command.get("port", 8443)  # Default to 8443 for openplc-runtime
    headers = command.get("headers", {})
    ip = instance.get("ip")

    # Build content dictionary for requests library
    content = {}

    # Add headers if provided
    if headers:
        content["headers"] = headers

    # Add query parameters if provided
    params = command.get("params")
    if params:
        content["params"] = params

    # Add request body data if provided
    data = command.get("data")
    if data:
        content_type = headers.get("Content-Type", "application/json")
        if content_type == "application/json":
            content["json"] = data
        else:
            content["data"] = data

    # Add files if provided (for multipart/form-data uploads)
    # Supports two formats:
    # 1. Base64-encoded dict: { field: { filename, content_base64, content_type } }
    #    Used by openplc-web for uploading ZIP files through JSON
    # 2. Already-formatted tuple: { field: (filename, bytes, mime_type) }
    #    For callers that already have files in requests-compatible format
    files = command.get("files")
    if files:
        processed_files = {}
        for field_name, file_info in files.items():
            # Case 1: Base64-encoded dict from openplc-web
            if isinstance(file_info, dict) and "content_base64" in file_info:
                content_base64 = file_info.get("content_base64")
                if not content_base64:
                    continue
                raw_content = base64.b64decode(content_base64)
                filename = file_info.get("filename") or field_name
                mime_type = file_info.get("content_type") or "application/octet-stream"
                processed_files[field_name] = (filename, raw_content, mime_type)
            else:
                # Case 2: Already in requests-compatible format (tuple or file-like)
                processed_files[field_name] = file_info

        if processed_files:
            content["files"] = processed_files

    return make_request(method, ip, port, api, content)
