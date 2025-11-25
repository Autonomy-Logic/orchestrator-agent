import ssl
import os
from aiohttp import ClientSession, TCPConnector
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from .logger import log_error

client_cert = os.path.expanduser("~/.mtls/client.crt")
client_key = os.path.expanduser("~/.mtls/client.key")

ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
ssl_context.load_cert_chain(certfile=client_cert, keyfile=client_key)

ssl_context.check_hostname = True
ssl_context.verify_mode = ssl.CERT_REQUIRED


def get_ssl_session():
    connector = TCPConnector(ssl=ssl_context)
    return ClientSession(connector=connector)


def _extract_agent_id() -> str:
    """
    Extract the agent ID from the client certificate CN field.
    Logs errors if extraction fails.

    Returns:
        str: Agent ID from the certificate CN field, or "UNKNOWN" if not found
    """
    try:
        with open(client_cert, "rb") as cert_file:
            cert_data = cert_file.read()
            cert = x509.load_pem_x509_certificate(cert_data, default_backend())

            for attribute in cert.subject:
                if attribute.oid == x509.oid.NameOID.COMMON_NAME:
                    return attribute.value

        log_error(f"Agent ID not found in certificate CN field: {client_cert}")
        return "UNKNOWN"
    except Exception as e:
        log_error(f"Failed to extract agent_id from {client_cert}: {e}")
        return "UNKNOWN"


_AGENT_ID = _extract_agent_id()


def get_agent_id() -> str:
    """
    Get the cached agent ID extracted from the client certificate CN field.
    The agent ID is extracted once at module load time for efficiency.

    Returns:
        str: Agent ID from the certificate CN field, or "UNKNOWN" if not found
    """
    return _AGENT_ID
