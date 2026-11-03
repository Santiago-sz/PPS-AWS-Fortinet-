"""Loopback-only HTTP adapter. Never expose this development server publicly."""

import json
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .service import MAX_UPLOAD, Error, require


def create_server(service, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Upload URLs contain temporary credentials.

        def handle_request(self):
            correlation = uuid.uuid4().hex
            try:
                self.connection.settimeout(30)
                host = f"127.0.0.1:{self.server.server_port}"
                require(self.headers.get("Host") == host, "invalid_host", 403)
                require(not self.headers.get("Origin"), "browser_requests_disabled", 403)
                require(not self.headers.get("Transfer-Encoding"), "unsupported_transfer_encoding")
                parsed = urlsplit(self.path)
                require(not parsed.scheme and not parsed.netloc, "invalid_path")
                query = parse_qs(parsed.query)
                length = self.headers.get("Content-Length", "0")
                require(length.isascii() and length.isdigit(), "invalid_content_length")
                length = int(length)
                limit = MAX_UPLOAD if self.command == "PUT" else 64 * 1024
                require(length <= limit, "request_too_large", 413)
                data = self.rfile.read(length)
                require(len(data) == length, "incomplete_body")
                payload = None
                if self.command == "POST":
                    require(
                        self.headers.get_content_type() == "application/json", "json_required", 415
                    )
                    try:
                        payload = json.loads(data)
                    except (ValueError, UnicodeError):
                        raise Error(400, "invalid_json", "JSON inválido") from None
                    require(isinstance(payload, dict), "json_object_required")
                status, body, mime = self.route(parsed.path, query, payload, data, host)
            except Error as exc:
                status, body, mime = (
                    exc.status,
                    {"code": exc.code, "message": str(exc), "correlation_id": correlation},
                    "application/json",
                )
            except TimeoutError:
                status, body, mime = (
                    408,
                    {"code": "request_timeout", "correlation_id": correlation},
                    "application/json",
                )
            except Exception:
                status, body, mime = (
                    500,
                    {
                        "code": "internal_error",
                        "message": "Error interno del servicio.",
                        "correlation_id": correlation,
                    },
                    "application/json",
                )
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Correlation-ID", correlation)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
            except (TimeoutError, BrokenPipeError, ConnectionResetError):
                pass

        def route(self, path, query, payload, data, host):
            method, key = self.command, self.headers.get("Idempotency-Key")
            if method == "GET":
                if path == "/api/session":
                    return 200, service.session(), "application/json"
                if path in {"/api/policies", "/api/audits"}:
                    return (
                        200,
                        service.collection(path.rsplit("/", 1)[1], query.get("cursor", [None])[0]),
                        "application/json",
                    )
                match = re.fullmatch(r"/api/policies/([^/]+)", path)
                if match:
                    return 200, service.policy(match[1]), "application/json"
                match = re.fullmatch(r"/api/policies/([^/]+)/versions/([^/]+)/document", path)
                if match:
                    body, mime = service.document(match[1], match[2])
                    return 200, body, mime
                match = re.fullmatch(r"/api/audits/([^/]+)(/results|/export)?", path)
                if match:
                    if match[2] == "/export":
                        body, mime = service.export(match[1], query.get("format", ["json"])[0])
                        return 200, body, mime
                    return (
                        200,
                        service.audit(match[1], results=match[2] == "/results"),
                        "application/json",
                    )
            if method == "POST":
                if path == "/api/policies":
                    created = service.create_policy(payload, key)
                    created["upload"]["url"] = "http://" + host + created["upload"]["url"]
                    return 201, created, "application/json"
                if path == "/api/audits":
                    return 202, service.reaudit(payload, key), "application/json"
                match = re.fullmatch(
                    r"/api/policies/([^/]+)/versions/([^/]+)/complete-upload", path
                )
                if match:
                    return (
                        202,
                        service.complete(match[1], match[2], payload, key),
                        "application/json",
                    )
            if method == "PUT":
                match = re.fullmatch(r"/uploads/([^/]+)", path)
                if match:
                    service.put_upload(
                        match[1], query.get("token", [""])[0], data, self.headers.get_content_type()
                    )
                    return 200, {}, "application/json"
            raise Error(404, "not_found", "Ruta no disponible")

        do_GET = handle_request
        do_POST = handle_request
        do_PUT = handle_request
        do_PATCH = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
