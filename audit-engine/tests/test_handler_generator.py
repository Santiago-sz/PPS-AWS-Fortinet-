"""
Tests para handler_generator.py — entrypoint S3-triggered de policy_generator.

Mockea TODOS los colaboradores (S3, el modelo vía
llm_client.generate_audit_script, lambda:InvokeFunction) — nunca se llama a
un servicio real. `extractor`/`chunker` reales no corren acá tampoco (se
mockean) porque el contrato de este handler es orquestación, no extracción
de texto — eso ya está cubierto por test_extractor.py/test_chunker.py.

Ya no existe ninguna lectura de Secrets Manager en este handler: el modelo
se alcanza vía Bedrock con la identidad IAM del rol.
"""

import json
from types import SimpleNamespace

import pytest

import extractor
import handler_generator
import knowledge_retriever
import llm_client


def _lambda_context():
    return SimpleNamespace(aws_request_id="test-request-id-123")


def _s3_event(bucket: str = "pps-policies-bucket", key: str = "policies/norma.pdf") -> dict:
    return {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                }
            }
        ]
    }


@pytest.fixture
def generator_env(monkeypatch):
    env = {
        "S3_BUCKET": "pps-reports-bucket",
        "EXECUTOR_FUNCTION_NAME": "pps-audit-executor",
        "LOG_LEVEL": "INFO",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("AUTO_EXECUTE", raising=False)
    return env


SAMPLE_CHECKS = [
    {
        "check_id": "chk-0001",
        "title": "Admin lockout",
        "clause_ref": {
            "chunk_id": "chunk-0001",
            "heading_path": ["Articulo 1"],
            "page": 1,
            "quote": "Los administradores deben tener bloqueo de cuenta.",
        },
        "endpoints": ["admins"],
        "severity": "high",
        "intent": "Verify admin lockout",
    }
]

VALID_SCRIPT = (
    "data = fgt.get('admins')\n"
    "if data:\n"
    "    report.finding('chk-0001', 'fail', 'hay admins')\n"
    "else:\n"
    "    report.finding('chk-0001', 'pass', 'ok')\n"
)

SINGLE_CHUNK = [
    {
        "chunk_id": "chunk-0001",
        "ordinal": 1,
        "heading_path": [],
        "page": 1,
        "char_span": [0, 5],
        "text": "texto",
    }
]

OK_RESULT = {"status": "ok", "script": VALID_SCRIPT, "attempts": 1, "checks": SAMPLE_CHECKS}


def _mock_lambda_only(mocker):
    """boto3.client solo debe pedirse para 'lambda' — cualquier otro servicio
    (Secrets Manager incluido) es una regresión."""
    mock_lambda = mocker.MagicMock()

    def fake_boto_client(service_name, *args, **kwargs):
        if service_name == "lambda":
            return mock_lambda
        raise AssertionError(f"unexpected boto3 client: {service_name}")

    mocker.patch("handler_generator.boto3.client", side_effect=fake_boto_client)
    return mock_lambda


def _mock_happy_collaborators(mocker, generate_result=OK_RESULT):
    mocker.patch("handler_generator.s3_io.get_policy", return_value=b"%PDF fake")
    mocker.patch(
        "handler_generator.extractor.extract",
        return_value=(
            "texto",
            [{"page": 1, "heading": None, "level": None, "char_start": 0, "char_end": 5}],
        ),
    )
    mocker.patch("handler_generator.chunker.chunk", return_value=SINGLE_CHUNK)
    mocker.patch("handler_generator.llm_client.generate_audit_script", return_value=generate_result)


def _generator_events(capsys, name="generator_result") -> list[dict]:
    lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return [ln for ln in lines if ln.get("event") == name]


class TestUploadTriggersCorrectFlow:
    @pytest.mark.parametrize(
        ("encoded_key", "decoded_key"),
        [
            ("policies/norma+de+seguridad.pdf", "policies/norma de seguridad.pdf"),
            ("policies/pol%C3%ADtica%2Bred.docx", "policies/política+red.docx"),
            ("policies/norma%2520.pdf", "policies/norma%20.pdf"),
        ],
    )
    def test_decodes_s3_key_once_for_download_and_manifest(
        self, generator_env, mocker, encoded_key, decoded_key
    ):
        _mock_lambda_only(mocker)
        _mock_happy_collaborators(mocker)
        get_policy = handler_generator.s3_io.get_policy
        mocker.patch("handler_generator.s3_io.put_script", return_value="a" * 64)
        put_manifest = mocker.patch("handler_generator.s3_io.put_manifest")

        handler_generator.lambda_handler(_s3_event(key=encoded_key), _lambda_context())

        get_policy.assert_called_once_with("pps-policies-bucket", decoded_key)
        assert put_manifest.call_args.args[2]["policy_key"] == decoded_key

    def test_happy_path_extracts_chunks_generates_writes_and_invokes_executor(
        self, generator_env, mocker, capsys
    ):
        call_order = []

        def fake_boto_client(service_name, *args, **kwargs):
            call_order.append(f"boto3.client:{service_name}")
            if service_name == "lambda":
                mock_lambda = mocker.MagicMock()
                mock_lambda.invoke.side_effect = lambda **kw: (
                    call_order.append("lambda.invoke"),
                    {"StatusCode": 202},
                )[1]
                return mock_lambda
            raise AssertionError(f"unexpected boto3 client: {service_name}")

        mocker.patch("handler_generator.boto3.client", side_effect=fake_boto_client)

        mocker.patch(
            "handler_generator.s3_io.get_policy",
            side_effect=lambda bucket, key: (call_order.append("get_policy"), b"%PDF fake")[1],
        )
        mocker.patch(
            "handler_generator.extractor.extract",
            side_effect=lambda data, ct: (
                call_order.append("extract"),
                (
                    "texto de la norma",
                    [{"page": 1, "heading": None, "level": None, "char_start": 0, "char_end": 10}],
                ),
            )[1],
        )
        mocker.patch(
            "handler_generator.chunker.chunk",
            side_effect=lambda text, metadata: (
                call_order.append("chunk"),
                [
                    {
                        "chunk_id": "chunk-0001",
                        "ordinal": 1,
                        "heading_path": ["Articulo 1"],
                        "page": 1,
                        "char_span": [0, 10],
                        "text": text,
                    }
                ],
            )[1],
        )

        def fake_generate(chunks, endpoint_catalog, *, max_attempts):
            call_order.append("generate_audit_script")
            assert "admins" in endpoint_catalog
            assert max_attempts == llm_client.MAX_GENERATION_ATTEMPTS
            return OK_RESULT

        mocker.patch(
            "handler_generator.llm_client.generate_audit_script", side_effect=fake_generate
        )

        mocker.patch(
            "handler_generator.s3_io.put_script",
            side_effect=lambda bucket, key, source: (
                call_order.append("put_script"),
                "a" * 64,
            )[1],
        )
        captured_manifest = {}

        def fake_put_manifest(bucket, key, manifest):
            call_order.append("put_manifest")
            captured_manifest.update(manifest)

        mocker.patch("handler_generator.s3_io.put_manifest", side_effect=fake_put_manifest)

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        # No Secrets Manager hop anymore: chunk -> generate directly.
        assert call_order == [
            "get_policy",
            "extract",
            "chunk",
            "generate_audit_script",
            "put_script",
            "put_manifest",
            "boto3.client:lambda",
            "lambda.invoke",
        ]

        assert result["status"] == "invoked"
        assert result["script_sha256"] == "a" * 64
        assert "run_id" in result
        assert result["manifest_key"] == f"artifacts/{result['run_id']}/manifest.json"
        assert result["script_key"] == f"artifacts/{result['run_id']}/script.py"

        # manifest records the Bedrock model id actually in effect
        assert captured_manifest["model"] == llm_client.current_model_id()

        events = _generator_events(capsys)
        assert len(events) == 1
        assert events[0]["status"] == "invoked"
        assert events[0]["run_id"] == result["run_id"]
        assert events[0]["checks_count"] == 1
        assert events[0]["map_calls"] == 1

    def test_invokes_executor_with_the_exact_pointer_contract(self, generator_env, mocker):
        """design.md Decision #2: el payload de invocación es EXACTAMENTE
        {run_id, manifest_key, script_key, script_sha256} — nada más, nada menos."""
        mock_lambda = _mock_lambda_only(mocker)
        _mock_happy_collaborators(mocker)
        mocker.patch("handler_generator.s3_io.put_script", return_value="b" * 64)
        mocker.patch("handler_generator.s3_io.put_manifest")

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        mock_lambda.invoke.assert_called_once()
        _, kwargs = mock_lambda.invoke.call_args
        assert kwargs["FunctionName"] == "pps-audit-executor"
        assert kwargs["InvocationType"] == "Event"
        payload = json.loads(kwargs["Payload"])
        assert set(payload.keys()) == {"run_id", "manifest_key", "script_key", "script_sha256"}
        assert payload["run_id"] == result["run_id"]
        assert payload["script_sha256"] == "b" * 64


class TestAutoExecuteGate:
    def test_auto_execute_false_writes_artifacts_but_does_not_invoke_executor(
        self, generator_env, monkeypatch, mocker, capsys
    ):
        monkeypatch.setenv("AUTO_EXECUTE", "false")
        # Any boto3 client creation is a failure here: no executor invoke at all.
        boto_client = mocker.patch(
            "handler_generator.boto3.client",
            side_effect=AssertionError("no boto3 client expected when AUTO_EXECUTE=false"),
        )
        _mock_happy_collaborators(mocker)
        put_script = mocker.patch("handler_generator.s3_io.put_script", return_value="c" * 64)
        put_manifest = mocker.patch("handler_generator.s3_io.put_manifest")

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        assert result["status"] == "awaiting_approval"
        assert result["script_sha256"] == "c" * 64
        assert result["manifest_key"] == f"artifacts/{result['run_id']}/manifest.json"
        assert result["script_key"] == f"artifacts/{result['run_id']}/script.py"
        put_script.assert_called_once()
        put_manifest.assert_called_once()
        boto_client.assert_not_called()

        awaiting = _generator_events(capsys, "awaiting_approval")
        assert len(awaiting) == 1
        assert awaiting[0]["run_id"] == result["run_id"]
        assert awaiting[0]["script_sha256"] == "c" * 64

    @pytest.mark.parametrize("value", ["0", "no", "False", "off", "anything-else"])
    def test_non_truthy_values_disable_auto_execute(self, generator_env, monkeypatch, value):
        monkeypatch.setenv("AUTO_EXECUTE", value)
        assert handler_generator._auto_execute_enabled() is False

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", " Yes "])
    def test_truthy_values_enable_auto_execute(self, generator_env, monkeypatch, value):
        monkeypatch.setenv("AUTO_EXECUTE", value)
        assert handler_generator._auto_execute_enabled() is True

    def test_auto_execute_defaults_to_true_when_unset(self, generator_env, mocker):
        mock_lambda = _mock_lambda_only(mocker)
        _mock_happy_collaborators(mocker)
        mocker.patch("handler_generator.s3_io.put_script", return_value="d" * 64)
        mocker.patch("handler_generator.s3_io.put_manifest")

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        assert result["status"] == "invoked"
        mock_lambda.invoke.assert_called_once()


class TestRetryExhaustedPath:
    def test_generation_failed_writes_report_and_does_not_invoke_executor(
        self, generator_env, mocker, capsys
    ):
        mock_lambda = _mock_lambda_only(mocker)
        _mock_happy_collaborators(
            mocker,
            generate_result={
                "status": "generation_failed",
                "attempts": llm_client.MAX_GENERATION_ATTEMPTS,
                "errors": [{"rule_id": "denied_node:Import", "failure_kind": "allowlist"}],
            },
        )
        put_report = mocker.patch("handler_generator.s3_io.put_report")
        put_script = mocker.patch("handler_generator.s3_io.put_script")
        put_manifest = mocker.patch("handler_generator.s3_io.put_manifest")

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        assert result["status"] == "generation_failed"
        assert result["attempts"] == llm_client.MAX_GENERATION_ATTEMPTS

        # Explicit failure report written to S3 (markdown + json)
        assert put_report.call_count == 2
        written_bodies = [call.args[2] for call in put_report.call_args_list]
        assert any("could not audit" in body.lower() for body in written_bodies)
        assert any("generation_failed" in body for body in written_bodies)

        # Never writes a script/manifest artifact, never invokes the executor
        put_script.assert_not_called()
        put_manifest.assert_not_called()
        mock_lambda.invoke.assert_not_called()

        events = _generator_events(capsys)
        assert events[0]["status"] == "generation_failed"
        assert events[0]["attempts"] == llm_client.MAX_GENERATION_ATTEMPTS


class TestNoVerifiableControlsPath:
    def test_no_verifiable_controls_writes_explicit_report_and_does_not_invoke_executor(
        self, generator_env, mocker
    ):
        mock_lambda = _mock_lambda_only(mocker)
        _mock_happy_collaborators(
            mocker, generate_result={"status": "no_verifiable_controls", "checks": []}
        )
        put_report = mocker.patch("handler_generator.s3_io.put_report")
        put_script = mocker.patch("handler_generator.s3_io.put_script")
        put_manifest = mocker.patch("handler_generator.s3_io.put_manifest")

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        assert result["status"] == "no_verifiable_controls"

        assert put_report.call_count == 2
        written_bodies = [call.args[2] for call in put_report.call_args_list]
        assert any("no_verifiable_controls" in body for body in written_bodies)

        put_script.assert_not_called()
        put_manifest.assert_not_called()
        mock_lambda.invoke.assert_not_called()


class TestModelFailurePath:
    def test_bedrock_failure_writes_could_not_audit_report(self, generator_env, mocker, capsys):
        mock_lambda = _mock_lambda_only(mocker)
        _mock_happy_collaborators(mocker)
        mocker.patch(
            "handler_generator.llm_client.generate_audit_script",
            side_effect=llm_client.ClaudeCallError("AccessDeniedException: no model access"),
        )
        put_report = mocker.patch("handler_generator.s3_io.put_report")

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        assert result["status"] == "could_not_audit"
        assert result["failure_reason"].startswith("ClaudeCallError:")
        assert "AccessDeniedException" in result["failure_reason"]
        assert put_report.call_count == 2
        mock_lambda.invoke.assert_not_called()

        events = _generator_events(capsys)
        assert events[0]["status"] == "could_not_audit"
        assert "AccessDeniedException" in events[0]["failure_reason"]


class TestExtractionFailurePath:
    def test_corrupt_document_writes_explicit_report_and_does_not_call_model(
        self, generator_env, mocker
    ):
        mock_lambda = _mock_lambda_only(mocker)
        mocker.patch("handler_generator.s3_io.get_policy", return_value=b"not a real pdf")
        mocker.patch(
            "handler_generator.extractor.extract",
            side_effect=extractor.ExtractionError("corrupt", "No se pudo leer el PDF"),
        )
        generate = mocker.patch("handler_generator.llm_client.generate_audit_script")
        put_report = mocker.patch("handler_generator.s3_io.put_report")

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        assert result["status"] == "could_not_audit"
        assert result["failure_reason"] == "extraction_error:corrupt"
        generate.assert_not_called()
        assert put_report.call_count == 2
        mock_lambda.invoke.assert_not_called()


class TestRequiredEnv:
    def test_claude_secret_arn_is_no_longer_required(self, generator_env, monkeypatch, mocker):
        monkeypatch.delenv("CLAUDE_SECRET_ARN", raising=False)
        _mock_lambda_only(mocker)
        _mock_happy_collaborators(mocker)
        mocker.patch("handler_generator.s3_io.put_script", return_value="e" * 64)
        mocker.patch("handler_generator.s3_io.put_manifest")

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        assert result["status"] == "invoked"

    def test_missing_s3_bucket_fails_fast(self, generator_env, monkeypatch):
        monkeypatch.delenv("S3_BUCKET")

        with pytest.raises(OSError, match="S3_BUCKET"):
            handler_generator.lambda_handler(_s3_event(), _lambda_context())


# ---------------------------------------------------------------------------
# Knowledge Base: deshabilitada = idéntico; habilitada = referencia + manifest
# ---------------------------------------------------------------------------

# Forma observada en la base real: URL HTTPS cuyo bucket incluye el id de cuenta.
KNOWLEDGE_SOURCE_URI = (
    "https://pps-prod-knowledge-123456789012.s3.amazonaws.com/fortinet/hardening.pdf"
)
KNOWLEDGE_BASE_BLOCK = {
    "enabled": True,
    "knowledge_base_id": "KBTEST0001",
    "max_results": 5,
    "filter": None,
    "controls_total": 1,
    "controls_with_references": 1,
    "retrievals_attempted": 1,
    "retrievals_failed": 0,
    "controls_skipped_by_call_cap": 0,
    "fragments_skipped_by_control_cap": 0,
    "fragments_dropped_by_size_cap": 0,
    "references": {
        "chk-0001": [{"source": "fortinet/hardening.pdf", "score": 0.9, "kind": "technical"}]
    },
}


def _run_and_capture_manifest(mocker, generate):
    _mock_lambda_only(mocker)
    _mock_happy_collaborators(mocker)
    mocker.patch("handler_generator.llm_client.generate_audit_script", side_effect=generate)
    mocker.patch("handler_generator.s3_io.put_script", return_value="a" * 64)
    put_manifest = mocker.patch("handler_generator.s3_io.put_manifest")
    result = handler_generator.lambda_handler(_s3_event(), _lambda_context())
    return result, put_manifest.call_args.args[2]


class TestKnowledgeBaseDisabled:
    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_generation_call_and_manifest_are_identical_to_the_previous_contract(
        self, generator_env, mocker, monkeypatch, value
    ):
        if value is None:
            monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)
        else:
            monkeypatch.setenv("KNOWLEDGE_BASE_ID", value)
        # Un valor inválido de las otras variables no debe importar si no hay base.
        monkeypatch.setenv("KNOWLEDGE_BASE_MAX_RESULTS", "no-es-un-numero")
        monkeypatch.setenv("KNOWLEDGE_BASE_FORTIOS_VERSION", "7.4")
        retrieve = mocker.patch("knowledge_retriever.retrieve")
        calls = []

        def fake_generate(*args, **kwargs):
            calls.append((args, kwargs))
            return OK_RESULT

        result, manifest = _run_and_capture_manifest(mocker, fake_generate)

        assert result["status"] == "invoked"
        assert len(calls) == 1
        assert calls[0][1] == {"max_attempts": llm_client.MAX_GENERATION_ATTEMPTS}
        assert list(manifest) == [
            "run_id",
            "policy_key",
            "policy_sha256",
            "script_key",
            "script_sha256",
            "checks",
            "attempts",
            "model",
            "generated_at",
        ]
        retrieve.assert_not_called()


class TestKnowledgeBaseEnabled:
    @pytest.fixture
    def knowledge_env(self, generator_env, monkeypatch):
        monkeypatch.setenv("KNOWLEDGE_BASE_ID", "KBTEST0001")
        monkeypatch.delenv("KNOWLEDGE_BASE_MAX_RESULTS", raising=False)
        monkeypatch.delenv("KNOWLEDGE_BASE_FORTIOS_VERSION", raising=False)

    def test_provider_queries_the_retriever_once_per_control(self, knowledge_env, mocker):
        retrieve = mocker.patch(
            "knowledge_retriever.retrieve",
            return_value=[
                knowledge_retriever.RetrievedFragment(
                    text="texto-de-referencia", source_uri=KNOWLEDGE_SOURCE_URI, score=0.9
                )
            ],
        )
        contexts = []

        def fake_generate(chunks, endpoint_catalog, *, max_attempts, reference_provider):
            contexts.append(reference_provider(SAMPLE_CHECKS))
            return {**OK_RESULT, "knowledge_base": contexts[0].manifest_block}

        result, manifest = _run_and_capture_manifest(mocker, fake_generate)

        assert result["status"] == "invoked"
        retrieve.assert_called_once()
        assert retrieve.call_args.kwargs["knowledge_base_id"] == "KBTEST0001"
        assert retrieve.call_args.kwargs["max_results"] == 5
        assert retrieve.call_args.kwargs["metadata_filter"] is None
        assert "texto-de-referencia" in contexts[0].prompt_section
        assert manifest["knowledge_base"] == KNOWLEDGE_BASE_BLOCK
        assert "texto-de-referencia" not in json.dumps(manifest)
        assert "123456789012" not in json.dumps(manifest)
        assert "123456789012" not in contexts[0].prompt_section

    def test_fortios_version_env_reaches_the_retriever_as_a_filter(
        self, knowledge_env, mocker, monkeypatch
    ):
        monkeypatch.setenv("KNOWLEDGE_BASE_FORTIOS_VERSION", "7.4")
        retrieve = mocker.patch("knowledge_retriever.retrieve", return_value=[])

        def fake_generate(chunks, endpoint_catalog, *, max_attempts, reference_provider):
            block = reference_provider(SAMPLE_CHECKS).manifest_block
            return {**OK_RESULT, "knowledge_base": block}

        _, manifest = _run_and_capture_manifest(mocker, fake_generate)

        assert retrieve.call_args.kwargs["metadata_filter"] == {
            "equals": {"key": "fortios_version", "value": "7.4"}
        }
        assert manifest["knowledge_base"]["filter"] == {"fortios_version": "7.4"}

    def test_retrieval_failure_does_not_fail_generation_and_is_recorded(
        self, knowledge_env, mocker
    ):
        mocker.patch(
            "knowledge_retriever.retrieve",
            side_effect=knowledge_retriever.KnowledgeRetrievalError("AccessDeniedException"),
        )

        def fake_generate(chunks, endpoint_catalog, *, max_attempts, reference_provider):
            context = reference_provider(SAMPLE_CHECKS)
            assert context.prompt_section == ""
            return {**OK_RESULT, "knowledge_base": context.manifest_block}

        result, manifest = _run_and_capture_manifest(mocker, fake_generate)

        assert result["status"] == "invoked"
        assert manifest["knowledge_base"]["enabled"] is True
        assert manifest["knowledge_base"]["controls_with_references"] == 0
        assert manifest["knowledge_base"]["retrievals_failed"] == 1
        assert manifest["knowledge_base"]["references"] == {}

    def test_end_to_end_reference_reaches_the_reduce_prompt_and_the_manifest(
        self, knowledge_env, mocker
    ):
        """Sin doblar llm_client: map -> Retrieve -> reduce -> manifest."""
        mocker.patch(
            "knowledge_retriever.retrieve",
            return_value=[
                knowledge_retriever.RetrievedFragment(
                    text="texto-de-referencia", source_uri=KNOWLEDGE_SOURCE_URI, score=0.9
                )
            ],
        )
        map_response = {"checks": [{k: v for k, v in SAMPLE_CHECKS[0].items() if k != "check_id"}]}
        prompts = []

        def fake_converse(system_prompt, user_prompt, *, max_tokens, stage, attempt=None):
            prompts.append((stage, system_prompt, user_prompt))
            text = json.dumps(map_response) if stage == "map" else VALID_SCRIPT
            return SimpleNamespace(text=text)

        _mock_lambda_only(mocker)
        mocker.patch("handler_generator.s3_io.get_policy", return_value=b"%PDF fake")
        mocker.patch("handler_generator.extractor.extract", return_value=("texto", []))
        mocker.patch("handler_generator.chunker.chunk", return_value=SINGLE_CHUNK)
        mocker.patch("bedrock_client.converse", side_effect=fake_converse)
        mocker.patch("handler_generator.s3_io.put_script", return_value="a" * 64)
        put_manifest = mocker.patch("handler_generator.s3_io.put_manifest")

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        assert result["status"] == "invoked"
        assert [stage for stage, _, _ in prompts] == ["map", "reduce"]
        assert "texto-de-referencia" not in prompts[0][2]
        assert "texto-de-referencia" in prompts[1][2]
        assert "--- check_id=chk-0001 ---" in prompts[1][2]
        assert prompts[1][1].endswith(llm_client.REFERENCE_SYSTEM_NOTE)
        manifest = put_manifest.call_args.args[2]
        assert manifest["knowledge_base"]["references"] == {
            "chk-0001": [{"source": "fortinet/hardening.pdf", "score": 0.9, "kind": "technical"}]
        }

    def test_generation_failure_report_is_unchanged_when_enabled(self, knowledge_env, mocker):
        _mock_lambda_only(mocker)
        _mock_happy_collaborators(
            mocker,
            generate_result={
                "status": "generation_failed",
                "attempts": 3,
                "errors": [],
                "knowledge_base": KNOWLEDGE_BASE_BLOCK,
            },
        )
        put_report = mocker.patch("handler_generator.s3_io.put_report")
        put_manifest = mocker.patch("handler_generator.s3_io.put_manifest")

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        assert result == {"status": "generation_failed", "run_id": result["run_id"], "attempts": 3}
        assert put_report.call_count == 2
        put_manifest.assert_not_called()


# ---------------------------------------------------------------------------
# Catálogo de campos (decisión 13): bloque aditivo `field_catalog` del manifest
# ---------------------------------------------------------------------------

FIELD_CATALOG_BLOCK = {
    "fortios_version": "v7.6.8",
    "unknown_field_references": 1,
    "references": [{"field": "zone", "endpoints": ["interfaces"], "line": 12}],
    "reduce_calls": 2,
}


class TestFieldCatalogBlock:
    def test_the_block_reaches_the_manifest_after_the_existing_keys(self, generator_env, mocker):
        result, manifest = _run_and_capture_manifest(
            mocker, lambda *a, **k: {**OK_RESULT, "field_catalog": FIELD_CATALOG_BLOCK}
        )

        assert result["status"] == "invoked"
        assert manifest["field_catalog"] == FIELD_CATALOG_BLOCK
        assert list(manifest)[-1] == "field_catalog"
        assert list(manifest)[:9] == [
            "run_id",
            "policy_key",
            "policy_sha256",
            "script_key",
            "script_sha256",
            "checks",
            "attempts",
            "model",
            "generated_at",
        ]

    def test_the_pointer_and_the_handler_result_do_not_change(self, generator_env, mocker):
        result, _ = _run_and_capture_manifest(
            mocker, lambda *a, **k: {**OK_RESULT, "field_catalog": FIELD_CATALOG_BLOCK}
        )

        assert set(result) == {
            "status",
            "run_id",
            "manifest_key",
            "script_key",
            "script_sha256",
            "attempts",
        }

    def test_the_terminal_event_counts_the_unknown_field_references(
        self, generator_env, mocker, capsys
    ):
        _run_and_capture_manifest(
            mocker, lambda *a, **k: {**OK_RESULT, "field_catalog": FIELD_CATALOG_BLOCK}
        )

        events = _generator_events(capsys)
        assert len(events) == 1
        assert events[0]["status"] == "invoked"
        assert events[0]["unknown_field_references"] == 1

    def test_a_result_without_the_block_keeps_the_event_and_the_manifest(
        self, generator_env, mocker, capsys
    ):
        _, manifest = _run_and_capture_manifest(mocker, lambda *a, **k: OK_RESULT)

        assert "field_catalog" not in manifest
        assert "unknown_field_references" not in _generator_events(capsys)[0]

    def test_awaiting_approval_also_reports_the_count(
        self, generator_env, monkeypatch, mocker, capsys
    ):
        monkeypatch.setenv("AUTO_EXECUTE", "false")
        _mock_happy_collaborators(
            mocker, generate_result={**OK_RESULT, "field_catalog": FIELD_CATALOG_BLOCK}
        )
        mocker.patch("handler_generator.s3_io.put_script", return_value="c" * 64)
        put_manifest = mocker.patch("handler_generator.s3_io.put_manifest")

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        assert result["status"] == "awaiting_approval"
        assert put_manifest.call_args.args[2]["field_catalog"] == FIELD_CATALOG_BLOCK
        assert _generator_events(capsys)[0]["unknown_field_references"] == 1
