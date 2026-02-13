import os
import sys
import tempfile
import ssl as stdlib_ssl
from unittest.mock import patch, MagicMock
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
import datetime


def _create_test_cert_and_key(cn="test-agent-123"):
    """Create a self-signed test certificate and key, returning temp file paths."""
    key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256(), default_backend())
    )

    cert_file = tempfile.NamedTemporaryFile(suffix=".crt", delete=False)
    cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
    cert_file.close()

    key_file = tempfile.NamedTemporaryFile(suffix=".key", delete=False)
    key_file.write(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    key_file.close()

    return cert_file.name, key_file.name


def _import_ssl_module(cert_path, key_path):
    """Import tools.ssl with patched cert/key paths, returning the module.

    tools/ssl.py runs ssl_context.load_cert_chain() at module level using paths
    resolved via os.path.expanduser. We must patch expanduser BEFORE the import
    so the module picks up our temp cert/key files.
    """
    # Evict cached module so re-import re-executes module-level code
    for mod_name in list(sys.modules):
        if mod_name == "tools.ssl" or mod_name.startswith("tools.ssl."):
            del sys.modules[mod_name]

    original_expanduser = os.path.expanduser

    def fake_expanduser(path):
        if path == "~/.mtls/client.crt":
            return cert_path
        if path == "~/.mtls/client.key":
            return key_path
        return original_expanduser(path)

    with patch("os.path.expanduser", side_effect=fake_expanduser):
        import tools.ssl as ssl_module
        return ssl_module


class TestExtractAgentId:
    def test_extracts_cn(self):
        """Extracts CN from certificate."""
        cert_path, key_path = _create_test_cert_and_key("my-agent-id")
        try:
            ssl_mod = _import_ssl_module(cert_path, key_path)
            result = ssl_mod._extract_agent_id()
            assert result == "my-agent-id"
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_missing_cert_returns_unknown(self):
        """Missing cert file returns 'UNKNOWN'."""
        cert_path, key_path = _create_test_cert_and_key("dummy")
        try:
            ssl_mod = _import_ssl_module(cert_path, key_path)
            # Now test _extract_agent_id with a bad path
            with patch.object(ssl_mod, "client_cert", "/nonexistent/cert.pem"):
                result = ssl_mod._extract_agent_id()
            assert result == "UNKNOWN"
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_get_agent_id_returns_string(self):
        """get_agent_id returns a string (cached at module load)."""
        cert_path, key_path = _create_test_cert_and_key("cached-agent")
        try:
            ssl_mod = _import_ssl_module(cert_path, key_path)
            result = ssl_mod.get_agent_id()
            assert isinstance(result, str)
            assert result == "cached-agent"
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_cert_without_cn_returns_unknown(self):
        """Lines 56-57: cert with no CN attribute returns 'UNKNOWN'."""
        # Create a cert with only ORGANIZATION_NAME, no CN
        key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TestOrg"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256(), default_backend())
        )

        cert_file = tempfile.NamedTemporaryFile(suffix=".crt", delete=False)
        cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
        cert_file.close()

        key_file = tempfile.NamedTemporaryFile(suffix=".key", delete=False)
        key_file.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
        key_file.close()

        try:
            ssl_mod = _import_ssl_module(cert_file.name, key_file.name)
            # Point client_cert at the no-CN cert
            with patch.object(ssl_mod, "client_cert", cert_file.name):
                result = ssl_mod._extract_agent_id()
            assert result == "UNKNOWN"
        finally:
            os.unlink(cert_file.name)
            os.unlink(key_file.name)

    def test_get_ssl_session(self):
        """get_ssl_session returns a ClientSession."""
        import asyncio

        cert_path, key_path = _create_test_cert_and_key("session-test")
        try:
            ssl_mod = _import_ssl_module(cert_path, key_path)

            async def _test():
                session = ssl_mod.get_ssl_session()
                assert session is not None
                await session.close()

            asyncio.get_event_loop().run_until_complete(_test())
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)
