import ssl
import os
from aiohttp import ClientSession, TCPConnector

client_cert = os.path.expanduser("~/.mtls/client.crt")
client_key = os.path.expanduser("~/.mtls/client.key")
server_ca_cert = os.path.expanduser("~/.mtls/ca.crt")

ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=server_ca_cert)
ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
ssl_context.load_cert_chain(certfile=client_cert, keyfile=client_key)

ssl_context.check_hostname = True
ssl_context.verify_mode = ssl.CERT_REQUIRED


def get_ssl_session():
    connector = TCPConnector(ssl=ssl_context)
    return ClientSession(connector=connector)
