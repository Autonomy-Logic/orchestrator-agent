from requests import get, post, delete, put
from tools.logger import log_error, log_info
from json import JSONDecodeError
import urllib3

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def check_instance(instance):
    if not instance.get("ip"):
        log_error("Instance without IP")
        return False
    return True


def process_response(response):
    """
    Process HTTP response and return a structured response object.
    Returns status code, headers, and body (as JSON if possible, otherwise text).
    """
    result = {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "ok": response.ok
    }
    
    # Try to parse response body as JSON, fall back to text
    try:
        result["body"] = response.json()
        result["content_type"] = "application/json"
    except JSONDecodeError:
        result["body"] = response.text
        result["content_type"] = "text/plain"
    
    return result


def make_request(method, ip, port, api, content):
    """
    Make an HTTP request to the specified endpoint.
    
    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        ip: Target IP address
        port: Target port
        api: API endpoint path
        content: Dictionary containing headers, json, data, etc.
    
    Returns:
        Dictionary with status_code, headers, body, ok, and content_type
    """
    # Construct URL - handle both http and https
    protocol = "https" if port == 8443 else "http"
    # Remove leading slash from api if present to avoid double slashes
    api_path = api.lstrip('/')
    url = f"{protocol}://{ip}:{port}/{api_path}"
    
    log_info(f"Making {method} request to {url}")
    
    try:
        # For HTTPS requests, disable SSL verification (self-signed certs)
        if protocol == "https":
            content["verify"] = False
        
        if method == "GET":
            response = get(url, **content)
        elif method == "POST":
            response = post(url, **content)
        elif method == "DELETE":
            response = delete(url, **content)
        elif method == "PUT":
            response = put(url, **content)
        else:
            log_error(f"Unsupported HTTP method: {method}")
            return {
                "status_code": 400,
                "headers": {},
                "body": {"error": f"Unsupported HTTP method: {method}"},
                "ok": False,
                "content_type": "application/json"
            }
        
        return process_response(response)
    except Exception as e:
        log_error(f"Request failed: {e}")
        return {
            "status_code": 500,
            "headers": {},
            "body": {"error": str(e)},
            "ok": False,
            "content_type": "application/json"
        }
