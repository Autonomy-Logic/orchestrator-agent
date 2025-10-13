from requests import get, post, delete, put
from tools.logger import log_error


def check_instance(instance):
    if not instance.get("ip"):
        log_error("Instance without IP")
        return False
    return True


def process_response(response):
    if not response.ok:
        log_error(f"Error: {response.status_code} - {response.text}")
        return None
    try:
        return response.json()
    except ValueError:
        log_error("Response is not in JSON format")
        return None


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
