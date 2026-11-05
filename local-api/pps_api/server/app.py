"""Servidor local con HTTPS configurable, limitado a loopback."""

import ssl
from http.server import ThreadingHTTPServer

from .routes import create_handler


def create_server(service, port=8765, *, tls_cert=None, tls_key=None):
    if bool(tls_cert) != bool(tls_key):
        raise ValueError("HTTPS requiere certificado y clave privada.")
    context = None
    if tls_cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(tls_cert, tls_key)
    scheme = "https" if context else "http"
    server = ThreadingHTTPServer(("127.0.0.1", port), create_handler(service, scheme))
    server.daemon_threads = True
    server.scheme = scheme
    if context:
        try:
            server.socket = context.wrap_socket(server.socket, server_side=True)
        except Exception:
            server.server_close()
            raise
    return server
