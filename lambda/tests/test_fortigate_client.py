"""
Tests para fortigate_client.py.

Mockea urllib.request.urlopen — nunca se conecta a un FortiGate real.
"""

import io
import json
import urllib.error

from fortigate_client import ENDPOINTS, FortiGateClient


def _fake_response(payload: dict):
    """Context manager falso que imita lo que devuelve urlopen()."""
    body = json.dumps(payload).encode("utf-8")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return body

    return _Resp()


class TestCollectAll:
    def test_collect_all_calls_every_endpoint(self, mocker):
        """collect_all() debe llamar exactamente los 11 endpoints definidos en ENDPOINTS."""
        client = FortiGateClient(host="192.168.1.1", token="dummy-token", verify_ssl=False)

        called_paths = []

        def fake_urlopen(req, context=None, timeout=None):
            # req.full_url es la URL completa construida en _get()
            path = req.full_url.split("/api/v2/cmdb/")[1]
            called_paths.append(path)
            return _fake_response({"http_status": 200, "results": [{"path": path}]})

        mocker.patch("fortigate_client.urllib.request.urlopen", side_effect=fake_urlopen)

        result = client.collect_all()

        assert len(called_paths) == len(ENDPOINTS) == 11
        assert set(called_paths) == {path for path, _ in ENDPOINTS}
        # Cada key del dict de resultados corresponde a la etiqueta definida en ENDPOINTS,
        # y contiene la data del path correspondiente (no mezclada entre endpoints).
        assert set(result.keys()) == {key for _, key in ENDPOINTS}
        for path, key in ENDPOINTS:
            assert result[key] == [{"path": path}]

    def test_collect_all_tolerates_partial_failure(self, mocker):
        """Si algunos endpoints fallan (HTTP error o red), collect_all no debe lanzar
        excepción global — los endpoints fallidos quedan en None y el resto sigue con data."""
        client = FortiGateClient(host="192.168.1.1", token="dummy-token", verify_ssl=False)

        # Los primeros 2 endpoints (según orden de ENDPOINTS) fallan de dos formas distintas,
        # el resto responde OK.
        failing_paths = {ENDPOINTS[0][0]: "http_error", ENDPOINTS[1][0]: "url_error"}

        def fake_urlopen(req, context=None, timeout=None):
            path = req.full_url.split("/api/v2/cmdb/")[1]
            if path in failing_paths:
                if failing_paths[path] == "http_error":
                    raise urllib.error.HTTPError(
                        url=req.full_url,
                        code=401,
                        msg="Unauthorized",
                        hdrs=None,
                        fp=io.BytesIO(b""),
                    )
                raise urllib.error.URLError("Network unreachable")
            return _fake_response({"http_status": 200, "results": [{"path": path}]})

        mocker.patch("fortigate_client.urllib.request.urlopen", side_effect=fake_urlopen)

        # No debe lanzar ninguna excepción
        result = client.collect_all()

        assert len(result) == len(ENDPOINTS)
        failing_keys = {key for path, key in ENDPOINTS if path in failing_paths}
        for _path, key in ENDPOINTS:
            if key in failing_keys:
                assert result[key] is None
            else:
                assert result[key] is not None

    def test_collect_all_all_endpoints_fail(self, mocker):
        """Si TODOS los endpoints fallan, collect_all devuelve un dict con todos los
        valores en None (no lanza excepción) — handler.py es quien decide abortar."""
        client = FortiGateClient(host="192.168.1.1", token="dummy-token", verify_ssl=False)

        def fake_urlopen(req, context=None, timeout=None):
            raise urllib.error.URLError("Connection refused")

        mocker.patch("fortigate_client.urllib.request.urlopen", side_effect=fake_urlopen)

        result = client.collect_all()

        assert len(result) == len(ENDPOINTS)
        assert all(v is None for v in result.values())


class TestGet:
    def test_get_returns_results_field(self, mocker):
        client = FortiGateClient(host="192.168.1.1", token="dummy-token", verify_ssl=False)
        mocker.patch(
            "fortigate_client.urllib.request.urlopen",
            return_value=_fake_response({"http_status": 200, "results": [{"a": 1}]}),
        )
        assert client._get("system/global") == [{"a": 1}]

    def test_get_returns_none_on_http_error(self, mocker):
        client = FortiGateClient(host="192.168.1.1", token="dummy-token", verify_ssl=False)
        mocker.patch(
            "fortigate_client.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="https://192.168.1.1/api/v2/cmdb/system/global",
                code=403,
                msg="Forbidden",
                hdrs=None,
                fp=io.BytesIO(b""),
            ),
        )
        assert client._get("system/global") is None

    def test_get_returns_none_on_unexpected_exception(self, mocker):
        client = FortiGateClient(host="192.168.1.1", token="dummy-token", verify_ssl=False)
        mocker.patch(
            "fortigate_client.urllib.request.urlopen",
            side_effect=ValueError("boom"),
        )
        assert client._get("system/global") is None


class TestInit:
    def test_verify_ssl_false_disables_cert_check(self):
        import ssl

        client = FortiGateClient(host="1.2.3.4", token="t", verify_ssl=False)
        assert client.ssl_context.check_hostname is False
        assert client.ssl_context.verify_mode == ssl.CERT_NONE

    def test_headers_include_bearer_token(self):
        client = FortiGateClient(host="1.2.3.4", token="my-token", verify_ssl=True)
        assert client.headers["Authorization"] == "Bearer my-token"
