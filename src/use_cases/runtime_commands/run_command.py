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
    files = command.get("files")
    if files:
        content["files"] = files
    
    return make_request(method, ip, port, api, content)
