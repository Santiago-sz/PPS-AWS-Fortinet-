"""
Tests para knowledge_retriever.py — recuperación sobre una Knowledge Base
administrada de Amazon Bedrock (`bedrock-agent-runtime.retrieve`).

El cliente boto3 se reemplaza por un MagicMock: nunca se llama a AWS. Se
verifican la configuración por entorno (deshabilitado por defecto), la forma
exacta de la request, el mapeo de `retrievalResults`, la validación de la
consulta, el mapeo de errores y que el evento `kb_retrieve` no exponga la
consulta ni el texto recuperado.
"""

import dataclasses
import json

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

import knowledge_retriever
from knowledge_retriever import (
    DEFAULT_MAX_RESULTS,
    KNOWLEDGE_BASE_ID_ENV,
    KNOWLEDGE_BASE_MAX_RESULTS_ENV,
    MAX_QUERY_CHARS,
    KnowledgeRetrievalError,
    RetrievalConfig,
    RetrievedFragment,
    build_request,
    load_config,
    retrieve,
)

KB_ID = "KBTEST0001"
QUERY = "consulta-confidencial-sobre-acceso-administrativo"
FRAGMENT_TEXT = "texto-recuperado-que-no-debe-registrarse"


def _retrieve_response(*results: dict) -> dict:
    return {"retrievalResults": list(results)}


def _result(text: str, *, uri: str | None = None, score: float | None = None) -> dict:
    result: dict = {"content": {"type": "TEXT", "text": text}}
    if uri is not None:
        result["location"] = {"type": "S3", "s3Location": {"uri": uri}}
    if score is not None:
        result["score"] = score
    return result


def _events(capsys) -> list[dict]:
    lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return [ln for ln in lines if ln.get("event") == "kb_retrieve"]


@pytest.fixture(autouse=True)
def _reset_cached_client():
    knowledge_retriever.reset_client()
    yield
    knowledge_retriever.reset_client()


class TestLoadConfig:
    def test_env_names_match_the_terraform_contract(self):
        assert KNOWLEDGE_BASE_ID_ENV == "KNOWLEDGE_BASE_ID"
        assert KNOWLEDGE_BASE_MAX_RESULTS_ENV == "KNOWLEDGE_BASE_MAX_RESULTS"

    def test_missing_id_means_retrieval_is_disabled(self, monkeypatch):
        monkeypatch.delenv(KNOWLEDGE_BASE_ID_ENV, raising=False)
        monkeypatch.delenv(KNOWLEDGE_BASE_MAX_RESULTS_ENV, raising=False)

        config = load_config()

        assert isinstance(config, RetrievalConfig)
        assert config.enabled is False
        assert config.knowledge_base_id == ""
        assert config.max_results == DEFAULT_MAX_RESULTS == 5

    @pytest.mark.parametrize("value", ["", "   "])
    def test_blank_id_means_retrieval_is_disabled(self, monkeypatch, value):
        monkeypatch.setenv(KNOWLEDGE_BASE_ID_ENV, value)

        assert load_config().enabled is False

    def test_id_enables_retrieval_and_max_results_is_read(self, monkeypatch):
        monkeypatch.setenv(KNOWLEDGE_BASE_ID_ENV, f"  {KB_ID} ")
        monkeypatch.setenv(KNOWLEDGE_BASE_MAX_RESULTS_ENV, "8")

        config = load_config()

        assert config.enabled is True
        assert config.knowledge_base_id == KB_ID
        assert config.max_results == 8

    def test_blank_max_results_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(KNOWLEDGE_BASE_ID_ENV, KB_ID)
        monkeypatch.setenv(KNOWLEDGE_BASE_MAX_RESULTS_ENV, "  ")

        assert load_config().max_results == DEFAULT_MAX_RESULTS

    @pytest.mark.parametrize("value", ["abc", "0", "-1", "101", "2.5"])
    def test_invalid_max_results_fails_explicitly(self, monkeypatch, value):
        monkeypatch.setenv(KNOWLEDGE_BASE_ID_ENV, KB_ID)
        monkeypatch.setenv(KNOWLEDGE_BASE_MAX_RESULTS_ENV, value)

        with pytest.raises(ValueError) as exc:
            load_config()

        assert KNOWLEDGE_BASE_MAX_RESULTS_ENV in str(exc.value)


class TestBuildRequest:
    def test_request_shape_matches_retrieve_contract(self):
        assert build_request(QUERY, knowledge_base_id=KB_ID, max_results=7) == {
            "knowledgeBaseId": KB_ID,
            "retrievalQuery": {"text": QUERY},
            "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 7}},
        }


class TestRetrieve:
    def test_maps_results_to_fragments(self, mocker):
        client = mocker.MagicMock()
        client.retrieve.return_value = _retrieve_response(
            _result("fragmento uno", uri="s3://bucket/doc-a.pdf", score=0.91),
            _result("fragmento dos"),
        )

        fragments = retrieve(QUERY, knowledge_base_id=KB_ID, max_results=4, client=client)

        assert fragments == [
            RetrievedFragment(text="fragmento uno", source_uri="s3://bucket/doc-a.pdf", score=0.91),
            RetrievedFragment(text="fragmento dos", source_uri=None, score=None),
        ]
        client.retrieve.assert_called_once_with(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": QUERY},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 4}},
        )

    def test_fragment_is_immutable(self):
        fragment = RetrievedFragment(text="t", source_uri=None, score=None)

        with pytest.raises(dataclasses.FrozenInstanceError):
            fragment.text = "otro"

    def test_empty_result_list_returns_no_fragments(self, mocker):
        client = mocker.MagicMock()
        client.retrieve.return_value = _retrieve_response()

        assert retrieve(QUERY, knowledge_base_id=KB_ID, max_results=5, client=client) == []

    def test_results_without_text_are_skipped(self, mocker):
        client = mocker.MagicMock()
        client.retrieve.return_value = _retrieve_response(
            {"content": {"type": "IMAGE", "byteContent": "data:image/png;base64,AAAA"}},
            _result("con texto", score=0.5),
        )

        fragments = retrieve(QUERY, knowledge_base_id=KB_ID, max_results=5, client=client)

        assert [f.text for f in fragments] == ["con texto"]

    def test_uses_module_client_factory_when_client_not_given(self, mocker):
        client = mocker.MagicMock()
        client.retrieve.return_value = _retrieve_response(_result("ok"))
        get_client = mocker.patch("knowledge_retriever.get_client", return_value=client)

        fragments = retrieve(QUERY, knowledge_base_id=KB_ID, max_results=5)

        get_client.assert_called_once()
        assert [f.text for f in fragments] == ["ok"]

    @pytest.mark.parametrize("query", ["", "   ", "\n\t "])
    def test_blank_query_is_rejected_without_calling_the_service(self, mocker, query):
        client = mocker.MagicMock()

        with pytest.raises(ValueError):
            retrieve(query, knowledge_base_id=KB_ID, max_results=5, client=client)

        client.retrieve.assert_not_called()

    def test_query_at_the_api_limit_is_accepted(self, mocker):
        client = mocker.MagicMock()
        client.retrieve.return_value = _retrieve_response()
        query = "a" * MAX_QUERY_CHARS

        retrieve(query, knowledge_base_id=KB_ID, max_results=5, client=client)

        assert client.retrieve.call_args.kwargs["retrievalQuery"] == {"text": query}

    def test_query_over_the_api_limit_is_rejected_not_clipped(self, mocker):
        client = mocker.MagicMock()
        query = "secreto" + "a" * MAX_QUERY_CHARS

        with pytest.raises(ValueError) as exc:
            retrieve(query, knowledge_base_id=KB_ID, max_results=5, client=client)

        client.retrieve.assert_not_called()
        assert "secreto" not in str(exc.value)
        assert str(MAX_QUERY_CHARS) in str(exc.value)

    def test_max_query_chars_matches_the_service_model(self):
        # botocore: bedrock-agent-runtime/2023-07-26, shape
        # KnowledgeBaseQueryTextString (max 20000).
        assert MAX_QUERY_CHARS == 20000

    @pytest.mark.parametrize("knowledge_base_id", ["", "  "])
    def test_blank_knowledge_base_id_is_rejected(self, mocker, knowledge_base_id):
        client = mocker.MagicMock()

        with pytest.raises(ValueError):
            retrieve(QUERY, knowledge_base_id=knowledge_base_id, max_results=5, client=client)

        client.retrieve.assert_not_called()

    @pytest.mark.parametrize("max_results", [0, -3, 101])
    def test_max_results_outside_the_api_range_is_rejected(self, mocker, max_results):
        client = mocker.MagicMock()

        with pytest.raises(ValueError):
            retrieve(QUERY, knowledge_base_id=KB_ID, max_results=max_results, client=client)

        client.retrieve.assert_not_called()


class TestRetrieveErrors:
    def test_client_error_is_wrapped_with_the_error_code_only(self, mocker):
        client = mocker.MagicMock()
        client.retrieve.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDeniedException",
                    "Message": f"not authorized for {QUERY}",
                }
            },
            "Retrieve",
        )

        with pytest.raises(KnowledgeRetrievalError) as exc:
            retrieve(QUERY, knowledge_base_id=KB_ID, max_results=5, client=client)

        assert "AccessDeniedException" in str(exc.value)
        assert QUERY not in str(exc.value)
        assert "not authorized" not in str(exc.value)

    def test_botocore_error_is_wrapped_with_the_error_type_only(self, mocker):
        client = mocker.MagicMock()
        client.retrieve.side_effect = EndpointConnectionError(endpoint_url="https://kb.invalid")

        with pytest.raises(KnowledgeRetrievalError) as exc:
            retrieve(QUERY, knowledge_base_id=KB_ID, max_results=5, client=client)

        assert "EndpointConnectionError" in str(exc.value)
        assert "kb.invalid" not in str(exc.value)

    @pytest.mark.parametrize(
        "response",
        [
            {},
            {"retrievalResults": None},
            {"retrievalResults": [{"location": {"type": "S3"}}]},
            {"retrievalResults": ["no-es-un-objeto"]},
        ],
    )
    def test_malformed_response_is_wrapped_without_leaking_content(self, mocker, response):
        client = mocker.MagicMock()
        client.retrieve.return_value = response

        with pytest.raises(KnowledgeRetrievalError) as exc:
            retrieve(QUERY, knowledge_base_id=KB_ID, max_results=5, client=client)

        assert "unexpected response shape" in str(exc.value)
        assert "no-es-un-objeto" not in str(exc.value)


class TestObservability:
    def test_successful_call_emits_one_event_without_query_or_text(self, mocker, capsys):
        client = mocker.MagicMock()
        client.retrieve.return_value = _retrieve_response(
            _result(FRAGMENT_TEXT, uri="s3://bucket/doc.pdf", score=0.7),
            _result(FRAGMENT_TEXT + "-2"),
        )

        retrieve(QUERY, knowledge_base_id=KB_ID, max_results=6, client=client)

        output = capsys.readouterr().out
        assert QUERY not in output
        assert FRAGMENT_TEXT not in output
        events = [
            json.loads(ln)
            for ln in output.splitlines()
            if ln.strip() and json.loads(ln).get("event") == "kb_retrieve"
        ]
        assert len(events) == 1
        event = events[0]
        assert event["knowledge_base_id"] == KB_ID
        assert event["max_results"] == 6
        assert event["results"] == 2
        assert event["status"] == "ok"
        assert event["latency_ms"] >= 0
        assert "ts" in event
        assert "error" not in event

    def test_failed_call_emits_one_event_with_error_code_only(self, mocker, capsys):
        client = mocker.MagicMock()
        client.retrieve.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": f"slow down {QUERY}"}},
            "Retrieve",
        )

        with pytest.raises(KnowledgeRetrievalError):
            retrieve(QUERY, knowledge_base_id=KB_ID, max_results=5, client=client)

        output = capsys.readouterr().out
        assert QUERY not in output
        events = [
            json.loads(ln)
            for ln in output.splitlines()
            if ln.strip() and json.loads(ln).get("event") == "kb_retrieve"
        ]
        assert len(events) == 1
        assert events[0]["status"] == "error"
        assert events[0]["error"] == "ThrottlingException"
        assert events[0]["results"] == 0
        assert events[0]["knowledge_base_id"] == KB_ID

    def test_malformed_response_emits_one_error_event(self, mocker, capsys):
        client = mocker.MagicMock()
        client.retrieve.return_value = {}

        with pytest.raises(KnowledgeRetrievalError):
            retrieve(QUERY, knowledge_base_id=KB_ID, max_results=5, client=client)

        events = _events(capsys)
        assert len(events) == 1
        assert events[0]["status"] == "error"

    def test_rejected_query_emits_no_event(self, mocker, capsys):
        with pytest.raises(ValueError):
            retrieve(" ", knowledge_base_id=KB_ID, max_results=5, client=mocker.MagicMock())

        assert _events(capsys) == []

    def test_errors_do_not_leak_query_into_standard_logging(self, mocker, caplog):
        client = mocker.MagicMock()
        client.retrieve.side_effect = ClientError(
            {"Error": {"Code": "ValidationException", "Message": f"bad query {QUERY}"}},
            "Retrieve",
        )

        with caplog.at_level("DEBUG"), pytest.raises(KnowledgeRetrievalError):
            retrieve(QUERY, knowledge_base_id=KB_ID, max_results=5, client=client)

        assert QUERY not in caplog.text


class TestGetClient:
    def test_client_is_created_lazily_and_cached(self, mocker):
        fake = mocker.MagicMock()
        boto_client = mocker.patch("knowledge_retriever.boto3.client", return_value=fake)

        first = knowledge_retriever.get_client()
        second = knowledge_retriever.get_client()

        assert first is fake and second is fake
        boto_client.assert_called_once()
        args, kwargs = boto_client.call_args
        assert args == ("bedrock-agent-runtime",)
        assert kwargs["config"].retries == {"max_attempts": 5, "mode": "adaptive"}
        assert kwargs["config"].read_timeout == 30

    def test_importing_the_module_does_not_create_a_client(self, mocker):
        boto_client = mocker.patch("knowledge_retriever.boto3.client")

        load_config()

        boto_client.assert_not_called()
