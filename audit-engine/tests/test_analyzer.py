"""
Tests para analyzer.py.

Mockea el cliente `bedrock-runtime` (via `bedrock_client.get_client`) —
nunca se llama a Amazon Bedrock real.
"""

import json

from botocore.exceptions import ClientError

import bedrock_client
from analyzer import MAX_DATA_CHARS, MAX_OUTPUT_TOKENS, SYSTEM_PROMPT, _build_user_prompt, analyze
from tests.conftest import bedrock_converse_response, bedrock_json_response


def _mock_bedrock(mocker, response=None, side_effect=None):
    client = mocker.MagicMock()
    if side_effect is not None:
        client.converse.side_effect = side_effect
    else:
        client.converse.return_value = response
    mocker.patch("bedrock_client.get_client", return_value=client)
    return client


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
    def test_analyze_builds_correct_request_and_parses_response(
        self, mocker, sample_fortigate_data, sample_device_info, sample_claude_analysis
    ):
        client = _mock_bedrock(mocker, response=bedrock_json_response(sample_claude_analysis))

        result = analyze(fortigate_data=sample_fortigate_data, device_info=sample_device_info)

        # Request armada correctamente (Converse)
        client.converse.assert_called_once()
        request = client.converse.call_args.kwargs
        assert request["modelId"] == bedrock_client.resolve_model_id()
        assert request["inferenceConfig"] == {"maxTokens": MAX_OUTPUT_TOKENS}
        assert request["system"][0] == {"text": SYSTEM_PROMPT}
        assert {"cachePoint": {"type": "default"}} in request["system"]
        assert sample_device_info["host"] in request["messages"][0]["content"][0]["text"]

        # Respuesta parseada correctamente
        assert result == sample_claude_analysis

    def test_analyze_honours_bedrock_model_id_env(
        self, mocker, monkeypatch, sample_fortigate_data, sample_device_info, sample_claude_analysis
    ):
        monkeypatch.setenv("BEDROCK_MODEL_ID", "eu.anthropic.claude-sonnet-4-6")
        client = _mock_bedrock(mocker, response=bedrock_json_response(sample_claude_analysis))

        analyze(fortigate_data=sample_fortigate_data, device_info=sample_device_info)

        assert client.converse.call_args.kwargs["modelId"] == "eu.anthropic.claude-sonnet-4-6"

    def test_analyze_returns_error_dict_on_bedrock_error(
        self, mocker, sample_fortigate_data, sample_device_info
    ):
        _mock_bedrock(
            mocker,
            side_effect=ClientError(
                {"Error": {"Code": "ThrottlingException", "Message": "overloaded"}},
                "Converse",
            ),
        )

        result = analyze(fortigate_data=sample_fortigate_data, device_info=sample_device_info)

        assert result["error"] == "bedrock_error"
        assert "ThrottlingException" in result["detail"]
        assert "overloaded" in result["detail"]

    def test_analyze_returns_error_dict_on_invalid_json_response(
        self, mocker, sample_fortigate_data, sample_device_info
    ):
        """El modelo respondió texto que no es JSON válido -> analyze no debe crashear,
        debe devolver un dict de error con el texto crudo."""
        raw_text = "Lo siento, no puedo generar el análisis ahora mismo."
        _mock_bedrock(mocker, response=bedrock_converse_response(raw_text))

        result = analyze(fortigate_data=sample_fortigate_data, device_info=sample_device_info)

        assert result["error"] == "json_parse_error"
        assert result["raw"] == raw_text

    def test_analyze_returns_error_dict_on_unexpected_exception(
        self, mocker, sample_fortigate_data, sample_device_info
    ):
        mocker.patch("bedrock_client.get_client", side_effect=RuntimeError("network down"))

        result = analyze(fortigate_data=sample_fortigate_data, device_info=sample_device_info)

        assert result["error"] == "unexpected"
        assert "network down" in result["detail"]
