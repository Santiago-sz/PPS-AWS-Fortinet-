"""
Test de integración generator -> executor (tasks.md 8.5).

Corre `handler_generator.lambda_handler` de punta a punta con un backend de
S3 real (`moto`), el modelo/lambda:InvokeFunction/FortiGate/SNS mockeados,
y verifica que el `manifest.json` + `script.py` efectivamente escritos en
S3 son consumidos por `handler_executor.lambda_handler` SIN NINGÚN cambio —
el mismo contrato que design.md Decision #2 promete: el puntero
`{run_id, manifest_key, script_key, script_sha256}` que produce el
generador es exactamente lo que el executor necesita, y los bytes que lee
son los mismos que el generador escribió (integridad end-to-end).

Nunca se llama a AWS real: moto (`@mock_aws`) simula S3, y el modelo
(Bedrock)/FortiGate/SNS/lambda:InvokeFunction se mockean explícitamente.
El generador ya no toca Secrets Manager (el modelo se alcanza vía IAM).
"""

import json

import boto3
import pytest
from moto import mock_aws

import handler_executor
import handler_generator

POLICIES_BUCKET = "pps-policies-bucket"
REPORTS_BUCKET = "pps-reports-bucket"

VALID_SCRIPT = (
    "data = fgt.get('admins')\n"
    "if data:\n"
    "    report.finding('chk-0001', 'fail', 'hay admins configurados')\n"
    "else:\n"
    "    report.finding('chk-0001', 'pass', 'no hay admins configurados')\n"
)

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
        "remediation": {
            "summary": "Habilitar bloqueo de cuenta para administradores.",
            "steps": ["System > Settings > Administration Settings"],
            "fortigate_cli": "config system global\n    set admin-lockout-threshold 3\nend",
        },
    }
]


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def s3_buckets():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=POLICIES_BUCKET)
        s3.create_bucket(Bucket=REPORTS_BUCKET)
        s3.put_object(Bucket=POLICIES_BUCKET, Key="policies/norma.pdf", Body=b"%PDF fake content")
        yield


@pytest.fixture
def generator_env(monkeypatch, s3_buckets):
    env = {
        "S3_BUCKET": REPORTS_BUCKET,
        "EXECUTOR_FUNCTION_NAME": "pps-audit-executor",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("AUTO_EXECUTE", raising=False)
    return env


@pytest.fixture
def executor_env(monkeypatch, s3_buckets):
    env = {
        "FORTIGATE_HOST": "192.168.1.1",
        "FORTIGATE_SECRET_ARN": (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:fortigate-token"
        ),
        "S3_BUCKET": REPORTS_BUCKET,
        "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:pps-notifications",
        "FORTIGATE_VERIFY_SSL": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


def _generator_event():
    return {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": POLICIES_BUCKET},
                    "object": {"key": "policies/norma.pdf"},
                }
            }
        ]
    }


def _mock_generator_side(mocker):
    """Mock only the model + the async invoke; let "s3" fall through to the
    real boto3.client so moto's S3 mock intercepts it. Secrets Manager must
    NOT be requested anymore by the generator."""
    real_boto_client = boto3.client
    mock_lambda = mocker.MagicMock()

    def fake_boto_client(svc, *args, **kwargs):
        if svc == "lambda":
            return mock_lambda
        if svc == "secretsmanager":
            raise AssertionError("generator must not read Secrets Manager anymore")
        return real_boto_client(svc, *args, **kwargs)

    mocker.patch("handler_generator.boto3.client", side_effect=fake_boto_client)
    mocker.patch(
        "handler_generator.extractor.extract",
        return_value=(
            "Los administradores deben tener bloqueo de cuenta.",
            [{"page": 1, "heading": None, "level": None, "char_start": 0, "char_end": 50}],
        ),
    )
    mocker.patch(
        "handler_generator.chunker.chunk",
        return_value=[
            {
                "chunk_id": "chunk-0001",
                "ordinal": 1,
                "heading_path": ["Articulo 1"],
                "page": 1,
                "char_span": [0, 50],
                "text": "Los administradores deben tener bloqueo de cuenta.",
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
    return mock_lambda


def _mock_executor_side(mocker, fgt_get_return=None):
    real_boto_client = boto3.client
    mock_sm = mocker.MagicMock()
    mock_sm.get_secret_value.return_value = {"SecretString": "dummy-fortigate-token"}

    def fake_executor_boto_client(svc, *args, **kwargs):
        if svc == "secretsmanager":
            return mock_sm
        return real_boto_client(svc, *args, **kwargs)

    mocker.patch("handler_executor.boto3.client", side_effect=fake_executor_boto_client)

    if fgt_get_return is None:
        fgt_class = mocker.patch("handler_executor.FortiGateClient")
    else:
        mock_fgt_instance = mocker.MagicMock()
        mock_fgt_instance.get.return_value = fgt_get_return
        fgt_class = mocker.patch("handler_executor.FortiGateClient", return_value=mock_fgt_instance)

    publish_to_sns = mocker.patch("handler_executor.reporter.publish_to_sns", return_value=True)
    return fgt_class, publish_to_sns


class TestGeneratorOutputFlowsUnchangedIntoExecutor:
    def test_manifest_and_script_written_by_generator_are_consumed_verbatim_by_executor(
        self, generator_env, executor_env, mocker
    ):
        _mock_generator_side(mocker)

        generator_result = handler_generator.lambda_handler(_generator_event(), context=None)

        assert generator_result["status"] == "invoked"

        # ── Simulate the real async invoke: build the exact executor event ──
        invoke_event = {
            "run_id": generator_result["run_id"],
            "manifest_key": generator_result["manifest_key"],
            "script_key": generator_result["script_key"],
            "script_sha256": generator_result["script_sha256"],
        }

        _, publish_to_sns = _mock_executor_side(mocker, fgt_get_return=[{"name": "admin"}])

        executor_result = handler_executor.lambda_handler(invoke_event, context=None)

        # The script the generator wrote is consumed byte-for-byte, unchanged.
        assert executor_result["status"] == "completed"
        assert executor_result["findings_count"] == 1

        # Real S3 round-trip proves the manifest/script are exactly what the
        # generator wrote — no transformation happened in between.
        s3 = boto3.client("s3", region_name="us-east-1")
        stored_manifest = json.loads(
            s3.get_object(Bucket=REPORTS_BUCKET, Key=generator_result["manifest_key"])["Body"]
            .read()
            .decode("utf-8")
        )
        stored_script = (
            s3.get_object(Bucket=REPORTS_BUCKET, Key=generator_result["script_key"])["Body"]
            .read()
            .decode("utf-8")
        )
        assert stored_script == VALID_SCRIPT
        assert stored_manifest["script_sha256"] == generator_result["script_sha256"]
        assert stored_manifest["checks"] == SAMPLE_CHECKS
        assert stored_manifest["model"] == "us.anthropic.claude-sonnet-4-6"

        # The report the executor delivered actually landed in S3, at the keys
        # the local API bridge discovers (reports/{run_id}/report.json + .md).
        run_id = generator_result["run_id"]
        report_md = (
            s3.get_object(Bucket=REPORTS_BUCKET, Key=f"reports/{run_id}/report.md")["Body"]
            .read()
            .decode("utf-8")
        )
        assert "chk-0001" in report_md
        assert "## Remediaciones propuestas" in report_md
        assert "set admin-lockout-threshold 3" in report_md

        report_json = json.loads(
            s3.get_object(Bucket=REPORTS_BUCKET, Key=f"reports/{run_id}/report.json")["Body"]
            .read()
            .decode("utf-8")
        )
        assert report_json["run_id"] == run_id
        assert report_json["status"] == "completed"
        assert report_json["remediation_count"] == 1
        finding = report_json["findings"][0]
        assert finding["status"] == "fail"
        assert finding["remediation"] == SAMPLE_CHECKS[0]["remediation"]
        publish_to_sns.assert_called_once()

    def test_tampered_script_between_generator_and_executor_is_rejected(
        self, generator_env, executor_env, mocker
    ):
        """Defensa en profundidad: si algo reescribe el script en S3 DESPUÉS
        de que el generador lo firmó, el executor lo rechaza por integridad
        ANTES de siquiera parsear el AST -- nunca ejecuta bytes no confiables."""
        _mock_generator_side(mocker)

        generator_result = handler_generator.lambda_handler(_generator_event(), context=None)

        # An attacker (or a bug) overwrites the script in S3 after the fact.
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.put_object(
            Bucket=REPORTS_BUCKET,
            Key=generator_result["script_key"],
            Body=b"report.finding('chk-0001', 'pass', 'tampered')\n",
        )

        invoke_event = {
            "run_id": generator_result["run_id"],
            "manifest_key": generator_result["manifest_key"],
            "script_key": generator_result["script_key"],
            "script_sha256": generator_result["script_sha256"],  # stale pointer
        }

        fgt_class, publish_to_sns = _mock_executor_side(mocker)

        executor_result = handler_executor.lambda_handler(invoke_event, context=None)

        assert executor_result["status"] == "could_not_audit"
        assert executor_result["failure_reason"] == "integrity_check_failed"
        fgt_class.assert_not_called()
        publish_to_sns.assert_called_once()

    def test_auto_execute_false_leaves_signed_artifacts_in_s3_without_invoking(
        self, generator_env, monkeypatch, mocker
    ):
        monkeypatch.setenv("AUTO_EXECUTE", "false")
        mock_lambda = _mock_generator_side(mocker)

        generator_result = handler_generator.lambda_handler(_generator_event(), context=None)

        assert generator_result["status"] == "awaiting_approval"
        mock_lambda.invoke.assert_not_called()

        # Artifacts exist and the pointer is already valid for a manual invoke.
        s3 = boto3.client("s3", region_name="us-east-1")
        stored_manifest = json.loads(
            s3.get_object(Bucket=REPORTS_BUCKET, Key=generator_result["manifest_key"])["Body"]
            .read()
            .decode("utf-8")
        )
        assert stored_manifest["script_sha256"] == generator_result["script_sha256"]
        assert set(generator_result) >= {"run_id", "manifest_key", "script_key", "script_sha256"}
