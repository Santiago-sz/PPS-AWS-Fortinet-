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
