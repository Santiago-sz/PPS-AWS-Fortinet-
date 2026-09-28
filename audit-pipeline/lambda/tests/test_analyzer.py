"""
Tests para analyzer.py.

Mockea la llamada HTTP a la API de Claude (urllib.request.urlopen) —
nunca se llama a la API real de Anthropic.
"""

import json
import urllib.error

from analyzer import CLAUDE_MODEL, MAX_DATA_CHARS, _build_user_prompt, analyze
from tests.conftest import claude_http_response_body


def _fake_response(body: bytes):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return body

    return _Resp()


class TestBuildUserPrompt:
    def test_includes_host_and_serialized_data(self, sample_fortigate_data, sample_device_info):
        prompt = _build_user_prompt(sample_fortigate_data, sample_device_info)

        assert sample_device_info["host"] in prompt
        assert "system_global" in prompt
        assert "FGT-LAB" in prompt  # viene de sample_fortigate_data

    def test_uses_default_host_when_missing(self, sample_fortigate_data):
        prompt = _build_user_prompt(sample_fortigate_data, {})
        assert "desconocido" in prompt

    def test_truncates_when_data_exceeds_max_chars(self):
        """Comportamiento ACTUAL documentado tal cual está implementado:
        si el JSON serializado supera MAX_DATA_CHARS, se trunca en silencio
        (corte duro de string, sin JSON válido) y se agrega un sufijo de aviso.
        Este test documenta ese comportamiento, no lo corrige."""
        huge_data = {"firewall_policies": [{"policyid": i, "note": "x" * 200} for i in range(1000)]}
        device_info = {"host": "192.168.1.1"}

        full_json_len = len(json.dumps(huge_data, indent=2, default=str))
        assert full_json_len > MAX_DATA_CHARS  # precondición: el fixture realmente excede el límite

        prompt = _build_user_prompt(huge_data, device_info)

        assert "... [truncado por límite de tokens]" in prompt
        # El bloque de datos truncado mide exactamente MAX_DATA_CHARS caracteres
        # (más el sufijo de aviso) — confirma que el corte es un slice duro
        # de string y no un truncado JSON-aware.
        data_section = prompt.split("CONFIGURACIÓN DEL DISPOSITIVO:\n", 1)[1]
        truncated_body = data_section.split("\n... [truncado por límite de tokens]")[0]
        assert len(truncated_body) == MAX_DATA_CHARS

    def test_does_not_truncate_when_data_within_limit(
        self, sample_fortigate_data, sample_device_info
    ):
        prompt = _build_user_prompt(sample_fortigate_data, sample_device_info)
        assert "truncado" not in prompt


class TestAnalyze:
    def test_analyze_builds_correct_payload_and_parses_response(
        self, mocker, sample_fortigate_data, sample_device_info, sample_claude_analysis
    ):
        captured_request = {}

        def fake_urlopen(req, timeout=None):
            captured_request["url"] = req.full_url
            captured_request["headers"] = req.headers
            captured_request["body"] = json.loads(req.data.decode("utf-8"))
            return _fake_response(claude_http_response_body(sample_claude_analysis))

        mocker.patch("analyzer.urllib.request.urlopen", side_effect=fake_urlopen)

        result = analyze(
            fortigate_data=sample_fortigate_data,
            device_info=sample_device_info,
            claude_api_key="sk-ant-dummy",
        )

        # Request armado correctamente
        assert captured_request["url"] == "https://api.anthropic.com/v1/messages"
        assert captured_request["headers"]["X-api-key"] == "sk-ant-dummy"
        body = captured_request["body"]
        assert body["model"] == CLAUDE_MODEL
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert sample_device_info["host"] in body["messages"][0]["content"]

        # Respuesta parseada correctamente
        assert result == sample_claude_analysis

    def test_analyze_returns_error_dict_on_http_error(
        self, mocker, sample_fortigate_data, sample_device_info
    ):
        import io

        mocker.patch(
            "analyzer.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="https://api.anthropic.com/v1/messages",
                code=529,
                msg="Overloaded",
                hdrs=None,
                fp=io.BytesIO(b'{"error": "overloaded"}'),
            ),
        )

        result = analyze(
            fortigate_data=sample_fortigate_data,
            device_info=sample_device_info,
            claude_api_key="sk-ant-dummy",
        )

        assert result["error"] == "HTTP 529"
        assert "overloaded" in result["detail"]

    def test_analyze_returns_error_dict_on_invalid_json_response(
        self, mocker, sample_fortigate_data, sample_device_info
    ):
        """Claude respondió texto que no es JSON válido -> analyze no debe crashear,
        debe devolver un dict de error con el texto crudo."""
        raw_text = "Lo siento, no puedo generar el análisis ahora mismo."
        payload = {
            "content": [{"type": "text", "text": raw_text}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        mocker.patch(
            "analyzer.urllib.request.urlopen",
            side_effect=lambda req, timeout=None: _fake_response(payload_bytes),
        )

        result = analyze(
            fortigate_data=sample_fortigate_data,
            device_info=sample_device_info,
            claude_api_key="sk-ant-dummy",
        )

        assert result["error"] == "json_parse_error"
        assert result["raw"] == raw_text

    def test_analyze_returns_error_dict_on_unexpected_exception(
        self, mocker, sample_fortigate_data, sample_device_info
    ):
        mocker.patch("analyzer.urllib.request.urlopen", side_effect=RuntimeError("network down"))

        result = analyze(
            fortigate_data=sample_fortigate_data,
            device_info=sample_device_info,
            claude_api_key="sk-ant-dummy",
        )

        assert result["error"] == "unexpected"
        assert "network down" in result["detail"]
