import ssl
import os

client_cert = os.path.expanduser("~/.mtls/client.crt")
client_key = os.path.expanduser("~/.mtls/client.key")
server_ca_cert = os.path.expanduser("~/.mtls/ca.crt")

ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=server_ca_cert)
ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
ssl_context.load_cert_chain(certfile=client_cert, keyfile=client_key)

# While in test
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_REQUIRED
