import ssl

client_cert = "client_cert.pem"
client_key = "client_key.pem"
server_ca_cert = "server_ca_cert.pem"

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.load_cert_chain(certfile=client_cert, keyfile=client_key)
ssl_context.load_verify_locations(cafile=server_ca_cert)  # CA for server certs
ssl_context.check_hostname = (
    False  # Disable hostname verification if not using proper DNS
)
