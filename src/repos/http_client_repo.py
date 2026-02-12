from json import JSONDecodeError

import urllib3
from requests import get, post, delete, put

from repos.interfaces import HTTPClientRepoInterface
from tools.logger import log_error, log_info

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class HTTPClientRepo(HTTPClientRepoInterface):
    """HTTP client adapter for making requests to runtime containers."""

    def make_request(
        self, method: str, ip: str, port: int, api: str, content: dict
    ) -> dict:
        # Construct URL - handle both http and https
        protocol = "https" if port == 8443 else "http"
        # Remove leading slash from api if present to avoid double slashes
        api_path = api.lstrip("/")
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
                    "content_type": "application/json",
                }

            return self._process_response(response)
        except Exception as e:
            log_error(f"Request failed: {e}")
            return {
                "status_code": 500,
                "headers": {},
                "body": {"error": str(e)},
                "ok": False,
                "content_type": "application/json",
            }

    def _process_response(self, response) -> dict:
        """Process HTTP response into a structured dict."""
        result = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "ok": response.ok,
        }

        try:
            result["body"] = response.json()
            result["content_type"] = "application/json"
        except JSONDecodeError:
            result["body"] = response.text
            result["content_type"] = "text/plain"

        return result
