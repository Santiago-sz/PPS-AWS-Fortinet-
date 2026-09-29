"""HTTPS API adapter. All organization authorization belongs to the server.

There is intentionally no boto3 dependency, arbitrary S3 key API, or direct
FortiGate connection here. The API contract is documented in API_CONTRACT.md.
"""

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import webbrowser


class ApiError(Exception):
    def __init__(self, message, code="connection_error", correlation_id=""):
        super().__init__(message)
        self.code, self.correlation_id = code, correlation_id


def https_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Se requiere una URL HTTPS sin credenciales incrustadas.")
    if parsed.fragment:
        raise ValueError("La URL no debe contener un fragmento.")
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward Bearer tokens or policy documents to redirect targets.
        return None


def request(url, method="GET", data=None, headers=None, timeout=30):
    https_url(url)
    req = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with build_opener(NoRedirect).open(req, timeout=timeout) as response:
            result = response.read(25 * 1024 * 1024 + 1)
            if len(result) > 25 * 1024 * 1024:
                raise ApiError("La respuesta supera el límite permitido.", "response_too_large")
            return result
    except HTTPError as exc:
        messages = {
            401: "La sesión venció. Iniciá sesión nuevamente.",
            403: "No tenés permiso para esta operación.",
            404: "El recurso no existe o no está autorizado.",
            409: "La operación está en conflicto. Actualizá el estado.",
            413: "El documento supera el tamaño permitido.",
            429: "El servicio está ocupado. Reintentá más tarde.",
        }
        correlation = exc.headers.get("X-Correlation-ID", "")[:100]
        raise ApiError(
            messages.get(exc.code, "El servicio rechazó la solicitud."), str(exc.code), correlation
        ) from None
    except (URLError, TimeoutError, OSError):
        raise ApiError(
            "No se pudo conectar con AWS. Verificá tu conexión y la URL del servicio."
        ) from None


def login(config):
    """Authorization Code + PKCE, system browser, ephemeral loopback listener.

    The access token remains in memory. The API validates it; roles are fetched
    from /api/session, never decoded from an unverified local JWT.
    """
    issuer = https_url(config["issuer"].rstrip("/"))
    discovery = json.loads(request(issuer + "/.well-known/openid-configuration"))
    if discovery.get("issuer", "").rstrip("/") != issuer:
        raise ApiError("El emisor OIDC no coincide con la configuración.", "oidc_issuer")
    auth_url = https_url(discovery["authorization_endpoint"])
    token_url = https_url(discovery["token_endpoint"])
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    state = secrets.token_urlsafe(32)
    received = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != "/callback" or query.get("state") != [state]:
                self.send_error(400)
                return
            received.update(query)
            body = b"PPS: autenticacion recibida. Podes cerrar esta ventana."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # Authorization code must not enter local logs.

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/callback"
        params = {
            "response_type": "code",
            "client_id": config["client_id"],
            "redirect_uri": redirect,
            "scope": config.get("scope", "openid profile"),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if config.get("audience"):
            params["audience"] = config["audience"]
        if not webbrowser.open(auth_url + ("&" if "?" in auth_url else "?") + urlencode(params)):
            raise ApiError("No se pudo abrir el navegador del sistema.")
        deadline = time.monotonic() + 120
        while not received and time.monotonic() < deadline:
            server.handle_request()
        if not received.get("code"):
            raise ApiError(
                "Inicio de sesión cancelado o vencido. Volvé a intentarlo.", "login_timeout"
            )
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": config["client_id"],
                "code": received["code"][0],
                "redirect_uri": redirect,
                "code_verifier": verifier,
            }
        ).encode()
        tokens = json.loads(
            request(token_url, "POST", body, {"Content-Type": "application/x-www-form-urlencoded"})
        )
    if tokens.get("token_type", "").lower() != "bearer" or not tokens.get("access_token"):
        raise ApiError("El proveedor no devolvió un access token Bearer.", "invalid_token")
    return ApiClient(config["api_url"], tokens["access_token"])


class ApiClient:
    def __init__(self, base_url, access_token):
        self.base_url = https_url(base_url.rstrip("/"))
        if urlsplit(self.base_url).query:
            raise ValueError("La URL base de API no admite query parameters.")
        self.token = access_token

    def call(self, path, method="GET", payload=None, idempotency_key=None, raw=False):
        if not path.startswith("/api/") or ".." in path or "://" in path:
            raise ValueError("Ruta de API inválida.")
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        result = request(self.base_url + path, method, data, headers)
        return result if raw else (json.loads(result) if result else {})

    def collection(self, path):
        """Follow opaque cursors without changing the origin or endpoint."""
        items, cursor, seen = [], None, set()
        for _ in range(100):
            page = self.call(
                path
                + (("&" if "?" in path else "?") + urlencode({"cursor": cursor}) if cursor else "")
            )
            items.extend(page["items"])
            cursor = page.get("next_cursor")
            if not cursor:
                return items
            if cursor in seen:
                raise ApiError("Cursor repetido en respuesta paginada.", "invalid_pagination")
            seen.add(cursor)
        raise ApiError("Demasiadas páginas. Acotá los filtros.", "pagination_limit")

    def snapshot(self):
        session = self.call("/api/session")
        if session.get("role") not in {"admin", "analyst", "reader"}:
            raise ApiError("El servicio no informó un rol reconocido.", "invalid_session")
        if not session.get("organization", {}).get("id") or not session.get("user", {}).get("id"):
            raise ApiError("La sesión no tiene organización o usuario.", "invalid_session")
        return {
            "session": session,
            "policies": self.collection("/api/policies"),
            "audits": self.collection("/api/audits"),
            "results": {},
        }

    def results(self, audit_id):
        prefix = "/api/audits/" + quote(audit_id, safe="")
        body = self.call(prefix + "/results")
        # Remote adapter returns a complete manifest; findings may be paginated.
        cursor, seen = body.get("next_cursor"), set()
        for _ in range(100):
            if not cursor:
                return body
            if cursor in seen:
                raise ApiError("Cursor repetido en resultados.", "invalid_pagination")
            seen.add(cursor)
            page = self.call(prefix + "/results?" + urlencode({"cursor": cursor}))
            if page["report"]["run_id"] != body["report"]["run_id"]:
                raise ApiError("Los resultados cambiaron durante la lectura.", "invalid_pagination")
            body["report"]["findings"].extend(page["report"]["findings"])
            cursor = page.get("next_cursor")
        raise ApiError("Demasiadas páginas de resultados.", "pagination_limit")

    def upload(self, metadata, document, key, on_created=None):
        created = self.call("/api/policies", "POST", metadata, key)
        if on_created:
            on_created(created)
        upload = created["upload"]
        # A presigned PUT receives only its own signed headers, never our token.
        if upload.get("method") != "PUT":
            raise ApiError("El servicio debe autorizar una subida PUT.", "upload_contract")
        headers = upload.get("headers", {})
        if any(k.lower() in {"authorization", "cookie", "host"} for k in headers):
            raise ApiError("Cabecera de subida no permitida.", "upload_contract")
        request(upload["url"], "PUT", document, headers, timeout=90)
        pid, vid = quote(created["policy_id"], safe=""), quote(created["version_id"], safe="")
        self.call(
            f"/api/policies/{pid}/versions/{vid}/complete-upload",
            "POST",
            {
                "upload_id": created["upload_id"],
                "sha256": metadata["sha256"],
                "size": metadata["size"],
            },
            key,
        )
        return created
