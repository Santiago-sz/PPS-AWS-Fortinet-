"""
Tests para handler_generator.py — entrypoint S3-triggered de policy_generator.

Mockea TODOS los colaboradores (S3, Secrets Manager, Claude vía
llm_client.generate_audit_script, lambda:InvokeFunction) — nunca se llama a
un servicio real. `extractor`/`chunker` reales no corren acá tampoco (se
mockean) porque el contrato de este handler es orquestación, no extracción
de texto — eso ya está cubierto por test_extractor.py/test_chunker.py.
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
        "CLAUDE_SECRET_ARN": (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:claude-api-key"
        ),
        "S3_BUCKET": "pps-reports-bucket",
        "EXECUTOR_FUNCTION_NAME": "pps-audit-executor",
        "LOG_LEVEL": "INFO",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture
def mock_secrets_manager(mocker):
    mock_sm = mocker.MagicMock()
    mock_sm.get_secret_value.return_value = {"SecretString": "sk-ant-dummy"}
    return mock_sm


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


class TestUploadTriggersCorrectFlow:
    def test_happy_path_extracts_chunks_generates_writes_and_invokes_executor(
        self, generator_env, mocker, mock_secrets_manager
    ):
        call_order = []

        def fake_boto_client(service_name, *args, **kwargs):
            call_order.append(f"boto3.client:{service_name}")
            if service_name == "secretsmanager":
                return mock_secrets_manager
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

        def fake_generate(chunks, endpoint_catalog, claude_api_key, max_attempts):
            call_order.append("generate_audit_script")
            assert claude_api_key == "sk-ant-dummy"
            assert "admins" in endpoint_catalog
            return {"status": "ok", "script": VALID_SCRIPT, "attempts": 1, "checks": SAMPLE_CHECKS}

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
        mocker.patch(
            "handler_generator.s3_io.put_manifest",
            side_effect=lambda bucket, key, manifest: call_order.append("put_manifest"),
        )

        result = handler_generator.lambda_handler(_s3_event(), _lambda_context())

        assert call_order == [
            "get_policy",
            "extract",
            "chunk",
            "boto3.client:secretsmanager",
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

    def test_invokes_executor_with_the_exact_pointer_contract(
        self, generator_env, mocker, mock_secrets_manager
    ):
        """design.md Decision #2: el payload de invocación es EXACTAMENTE
        {run_id, manifest_key, script_key, script_sha256} — nada más, nada menos."""
        mock_lambda = mocker.MagicMock()

        def fake_boto_client(service_name, *args, **kwargs):
            if service_name == "secretsmanager":
                return mock_secrets_manager
            if service_name == "lambda":
                return mock_lambda
            raise AssertionError(f"unexpected boto3 client: {service_name}")

        mocker.patch("handler_generator.boto3.client", side_effect=fake_boto_client)
        mocker.patch("handler_generator.s3_io.get_policy", return_value=b"%PDF fake")
        mocker.patch(
            "handler_generator.extractor.extract",
            return_value=(
                "texto",
                [{"page": 1, "heading": None, "level": None, "char_start": 0, "char_end": 5}],
            ),
        )
        mocker.patch(
            "handler_generator.chunker.chunk",
            return_value=[
                {
                    "chunk_id": "chunk-0001",
                    "ordinal": 1,
                    "heading_path": [],
                    "page": 1,
                    "char_span": [0, 5],
                    "text": "texto",
                }
            ],
        )
        mocker.patch(
            "handler_generator.llm_client.generate_audit_script",
            return_value={
                "status": "ok",
                "script": VALID_SCRIPT,
                "attempts": 1,
                "checks": SAMPLE_CHECKS,
            },
        )
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


class TestRetryExhaustedPath:
    def test_generation_failed_writes_report_and_does_not_invoke_executor(
        self, generator_env, mocker, mock_secrets_manager
    ):
        mock_lambda = mocker.MagicMock()

        def fake_boto_client(service_name, *args, **kwargs):
            if service_name == "secretsmanager":
                return mock_secrets_manager
            if service_name == "lambda":
                return mock_lambda
            raise AssertionError(f"unexpected boto3 client: {service_name}")

        mocker.patch("handler_generator.boto3.client", side_effect=fake_boto_client)
        mocker.patch("handler_generator.s3_io.get_policy", return_value=b"%PDF fake")
        mocker.patch(
            "handler_generator.extractor.extract",
            return_value=(
                "texto",
                [{"page": 1, "heading": None, "level": None, "char_start": 0, "char_end": 5}],
            ),
        )
        mocker.patch(
            "handler_generator.chunker.chunk",
            return_value=[
                {
                    "chunk_id": "chunk-0001",
                    "ordinal": 1,
                    "heading_path": [],
                    "page": 1,
                    "char_span": [0, 5],
                    "text": "texto",
                }
            ],
        )
        mocker.patch(
            "handler_generator.llm_client.generate_audit_script",
            return_value={
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


class TestNoVerifiableControlsPath:
    def test_no_verifiable_controls_writes_explicit_report_and_does_not_invoke_executor(
        self, generator_env, mocker, mock_secrets_manager
    ):
        mock_lambda = mocker.MagicMock()

        def fake_boto_client(service_name, *args, **kwargs):
            if service_name == "secretsmanager":
                return mock_secrets_manager
            if service_name == "lambda":
                return mock_lambda
            raise AssertionError(f"unexpected boto3 client: {service_name}")

        mocker.patch("handler_generator.boto3.client", side_effect=fake_boto_client)
        mocker.patch("handler_generator.s3_io.get_policy", return_value=b"%PDF fake")
        mocker.patch(
            "handler_generator.extractor.extract",
            return_value=(
                "texto sin controles",
                [{"page": 1, "heading": None, "level": None, "char_start": 0, "char_end": 5}],
            ),
        )
        mocker.patch(
            "handler_generator.chunker.chunk",
            return_value=[
                {
                    "chunk_id": "chunk-0001",
                    "ordinal": 1,
                    "heading_path": [],
                    "page": 1,
                    "char_span": [0, 5],
                    "text": "texto sin controles",
                }
            ],
        )
        mocker.patch(
            "handler_generator.llm_client.generate_audit_script",
            return_value={"status": "no_verifiable_controls", "checks": []},
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


class TestExtractionFailurePath:
    def test_corrupt_document_writes_explicit_report_and_does_not_call_claude(
        self, generator_env, mocker, mock_secrets_manager
    ):
        mock_lambda = mocker.MagicMock()

        def fake_boto_client(service_name, *args, **kwargs):
            if service_name == "secretsmanager":
                return mock_secrets_manager
            if service_name == "lambda":
                return mock_lambda
            raise AssertionError(f"unexpected boto3 client: {service_name}")

        mocker.patch("handler_generator.boto3.client", side_effect=fake_boto_client)
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
