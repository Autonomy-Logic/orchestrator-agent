import ssl
import os
from aiohttp import ClientSession, TCPConnector
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from .logger import log_error

client_cert = os.path.expanduser("~/.mtls/client.crt")
client_key = os.path.expanduser("~/.mtls/client.key")

_ssl_context = None
_agent_id = None


def _get_ssl_context():
    """Lazily create and cache the SSL context."""
    global _ssl_context
    if _ssl_context is None:
        _ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        _ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        _ssl_context.load_cert_chain(certfile=client_cert, keyfile=client_key)
        _ssl_context.check_hostname = True
        _ssl_context.verify_mode = ssl.CERT_REQUIRED
    return _ssl_context


def get_ssl_session(ttl_dns_cache: int = 30):
    """
    Create a new SSL-enabled aiohttp ClientSession.

    Args:
        ttl_dns_cache: DNS cache TTL in seconds. Lower values help with
                      network changes but increase DNS lookups. Default 30s.

    Returns:
        ClientSession configured with mTLS and DNS caching
    """
    connector = TCPConnector(
        ssl=_get_ssl_context(),
        ttl_dns_cache=ttl_dns_cache,
        use_dns_cache=True,
        force_close=True,  # Don't reuse connections (helps after network change)
    )
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


def get_agent_id() -> str:
    """
    Get the cached agent ID extracted from the client certificate CN field.
    The agent ID is extracted lazily on first access and cached.

    Returns:
        str: Agent ID from the certificate CN field, or "UNKNOWN" if not found
    """
    global _agent_id
    if _agent_id is None:
        _agent_id = _extract_agent_id()
    return _agent_id
