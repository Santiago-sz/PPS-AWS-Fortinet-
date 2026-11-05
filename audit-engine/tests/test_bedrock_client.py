"""
Tests para bedrock_client.py — transporte Converse sobre Amazon Bedrock.

El cliente boto3 se reemplaza por un MagicMock: nunca se llama a AWS. Se
verifica la forma exacta de la request (modelId, cachePoint, maxTokens
explicito), el parseo de la respuesta/usage y el mapeo de errores.
"""

import json

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

import bedrock_client
from bedrock_client import (
    DEFAULT_MODEL_ID,
    BedrockCallError,
    ConverseResult,
    build_request,
    converse,
    resolve_model_id,
)
from tests.conftest import bedrock_converse_response


@pytest.fixture(autouse=True)
def _reset_cached_client():
    bedrock_client.reset_client()
    yield
    bedrock_client.reset_client()


class TestResolveModelId:
    def test_defaults_to_cross_region_inference_profile(self, monkeypatch):
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        assert resolve_model_id() == DEFAULT_MODEL_ID
        assert DEFAULT_MODEL_ID == "us.anthropic.claude-sonnet-4-6"

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_MODEL_ID", "eu.anthropic.claude-sonnet-4-6")
        assert resolve_model_id() == "eu.anthropic.claude-sonnet-4-6"

    def test_blank_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_MODEL_ID", "   ")
        assert resolve_model_id() == DEFAULT_MODEL_ID


class TestBuildRequest:
    def test_request_shape_matches_converse_contract(self):
        req = build_request("SYS", "USER", max_tokens=1234, model_id="m-1")

        assert req["modelId"] == "m-1"
        assert req["system"] == [{"text": "SYS"}, {"cachePoint": {"type": "default"}}]
        assert req["messages"] == [{"role": "user", "content": [{"text": "USER"}]}]
        # maxTokens is ALWAYS explicit
        assert req["inferenceConfig"] == {"maxTokens": 1234}


class TestConverse:
    def test_parses_text_usage_and_metrics(self, mocker, capsys):
        client = mocker.MagicMock()
        client.converse.return_value = bedrock_converse_response(
            "hola",
            input_tokens=100,
            output_tokens=20,
            cache_read=60,
            cache_write=40,
            latency_ms=321,
            stop_reason="end_turn",
        )

        result = converse("SYS", "USER", max_tokens=50, model_id="m-1", client=client, stage="map")

        assert isinstance(result, ConverseResult)
        assert result.text == "hola"
        assert result.input_tokens == 100
        assert result.output_tokens == 20
        assert result.cache_read_tokens == 60
        assert result.cache_write_tokens == 40
        assert result.latency_ms == 321
        assert result.model_id == "m-1"
        assert result.stop_reason == "end_turn"

        _, kwargs = client.converse.call_args
        assert kwargs["modelId"] == "m-1"
        assert kwargs["inferenceConfig"] == {"maxTokens": 50}
        assert {"cachePoint": {"type": "default"}} in kwargs["system"]

        # one structured llm_call event + three EMF metrics per call
        lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        events = [ln for ln in lines if ln.get("event") == "llm_call"]
        assert len(events) == 1
        assert events[0]["stage"] == "map"
        assert events[0]["input_tokens"] == 100
        assert events[0]["output_tokens"] == 20
        assert events[0]["cache_read_tokens"] == 60
        assert events[0]["stop_reason"] == "end_turn"
        metric_names = sorted(
            ln["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"] for ln in lines if "_aws" in ln
        )
        assert metric_names == ["LlmInputTokens", "LlmLatencyMs", "LlmOutputTokens"]

    def test_concatenates_multiple_text_blocks(self, mocker):
        client = mocker.MagicMock()
        response = bedrock_converse_response("a")
        response["output"]["message"]["content"].append({"text": "b"})
        client.converse.return_value = response

        result = converse("S", "U", max_tokens=10, model_id="m", client=client)

        assert result.text == "ab"

    def test_uses_module_client_factory_and_resolved_model_when_not_given(
        self, mocker, monkeypatch
    ):
        monkeypatch.setenv("BEDROCK_MODEL_ID", "custom.model")
        client = mocker.MagicMock()
        client.converse.return_value = bedrock_converse_response("ok")
        get_client = mocker.patch("bedrock_client.get_client", return_value=client)

        result = converse("S", "U", max_tokens=10)

        get_client.assert_called_once()
        assert client.converse.call_args.kwargs["modelId"] == "custom.model"
        assert result.model_id == "custom.model"

    def test_measures_latency_when_metrics_missing(self, mocker):
        client = mocker.MagicMock()
        response = bedrock_converse_response("ok")
        del response["metrics"]
        client.converse.return_value = response

        result = converse("S", "U", max_tokens=10, model_id="m", client=client)

        assert result.latency_ms >= 0

    def test_client_error_maps_to_bedrock_call_error_with_code(self, mocker):
        client = mocker.MagicMock()
        client.converse.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Too many requests"}},
            "Converse",
        )

        with pytest.raises(BedrockCallError) as exc:
            converse("S", "U", max_tokens=10, model_id="m", client=client)

        assert "ThrottlingException: Too many requests" in str(exc.value)

    def test_botocore_error_maps_to_network_sdk_error(self, mocker):
        client = mocker.MagicMock()
        client.converse.side_effect = EndpointConnectionError(endpoint_url="https://bedrock")

        with pytest.raises(BedrockCallError) as exc:
            converse("S", "U", max_tokens=10, model_id="m", client=client)

        assert "network/sdk error" in str(exc.value)

    def test_malformed_response_maps_to_unexpected_shape(self, mocker):
        client = mocker.MagicMock()
        client.converse.return_value = {"output": {}}

        with pytest.raises(BedrockCallError) as exc:
            converse("S", "U", max_tokens=10, model_id="m", client=client)

        assert "unexpected response shape" in str(exc.value)

    def test_response_without_text_blocks_is_rejected(self, mocker):
        client = mocker.MagicMock()
        client.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": [{"toolUse": {}}]}},
            "usage": {"inputTokens": 1, "outputTokens": 1},
        }

        with pytest.raises(BedrockCallError) as exc:
            converse("S", "U", max_tokens=10, model_id="m", client=client)

        assert "no text blocks" in str(exc.value)

    def test_failed_call_still_emits_one_llm_call_event_with_error(self, mocker, capsys):
        client = mocker.MagicMock()
        client.converse.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "no model access"}},
            "Converse",
        )

        with pytest.raises(BedrockCallError):
            converse("S", "U", max_tokens=10, model_id="m", client=client, stage="reduce")

        lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        events = [ln for ln in lines if ln.get("event") == "llm_call"]
        assert len(events) == 1
        assert events[0]["stage"] == "reduce"
        assert "AccessDeniedException" in events[0]["error"]


class TestGetClient:
    def test_client_is_created_lazily_and_cached(self, mocker):
        fake = mocker.MagicMock()
        boto_client = mocker.patch("bedrock_client.boto3.client", return_value=fake)

        first = bedrock_client.get_client()
        second = bedrock_client.get_client()

        assert first is fake and second is fake
        boto_client.assert_called_once()
        args, kwargs = boto_client.call_args
        assert args == ("bedrock-runtime",)
        assert kwargs["config"].retries == {"max_attempts": 5, "mode": "adaptive"}
        assert kwargs["config"].read_timeout == 120
