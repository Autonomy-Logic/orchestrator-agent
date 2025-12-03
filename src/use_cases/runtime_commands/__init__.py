from requests import get, post, delete, put
from tools.logger import log_error
from json import JSONDecodeError


def check_instance(instance):
    if not instance.get("ip"):
        log_error("Instance without IP")
        return False
    return True


def process_response(response):
    """
    Process HTTP response and return a structured result.
    Returns a dict with status_code, headers, body, ok, and content_type.
    """
    result = {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "ok": response.ok,
        "content_type": response.headers.get("Content-Type", ""),
    }
    
    try:
        result["body"] = response.json()
    except JSONDecodeError:
        # Return text body if not JSON
        result["body"] = response.text
    
    if not response.ok:
        log_error(f"Error: {response.status_code} - {response.text}")
    
    return result


def make_request(method, ip, port, api, content):
    url = f"http://{ip}:{port}/{api}"
    try:
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
            return None
        return process_response(response)
    except Exception as e:
        log_error(f"Request failed: {e}")
        return None
