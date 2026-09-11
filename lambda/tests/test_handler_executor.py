"""
Tests para handler_executor.py — entrypoint async de audit_executor.

Mockea S3 (`s3_io`), Secrets Manager, `reporter.deliver_policy_report` y
`FortiGateClient`. Ejercita `script_validator.validate()` y `sandbox.execute()`
REALES (no mockeados) en la mayoría de los tests, porque el contrato central
de este handler —re-validación independiente + ejecución bajo sandbox— es
exactamente lo que hay que probar de punta a punta, no solo que se llamen.
"""

import hashlib
from types import SimpleNamespace

import pytest

import handler_executor
import sandbox


def _lambda_context():
    return SimpleNamespace(aws_request_id="test-request-id-456")


def _invoke_event(run_id="run-1", manifest_key=None, script_key=None, script_sha256=None):
    return {
        "run_id": run_id,
        "manifest_key": manifest_key or f"artifacts/{run_id}/manifest.json",
        "script_key": script_key or f"artifacts/{run_id}/script.py",
        "script_sha256": script_sha256,
    }


VALID_SCRIPT = (
    "data = fgt.get('admins')\n"
    "if data:\n"
    "    report.finding('chk-0001', 'fail', 'hay admins configurados')\n"
    "else:\n"
    "    report.finding('chk-0001', 'pass', 'no hay admins configurados')\n"
)

VALID_MANIFEST = {
    "run_id": "run-1",
    "policy_key": "policies/norma.pdf",
    "policy_sha256": "a" * 64,
    "script_key": "artifacts/run-1/script.py",
    "checks": [
        {
            "check_id": "chk-0001",
            "title": "Admin lockout",
            "clause_ref": {
                "chunk_id": "chunk-0001",
                "heading_path": ["Art 1"],
                "page": 1,
                "quote": "...",
            },
            "endpoints": ["admins"],
            "severity": "high",
            "intent": "verify",
        }
    ],
    "attempts": 1,
    "model": "claude-sonnet-4-6",
    "generated_at": "2026-09-10T12:00:00Z",
}


def _valid_script_sha256() -> str:
    return hashlib.sha256(VALID_SCRIPT.encode("utf-8")).hexdigest()


@pytest.fixture
def executor_env(monkeypatch):
    env = {
        "FORTIGATE_HOST": "192.168.1.1",
        "FORTIGATE_SECRET_ARN": (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:fortigate-token"
        ),
        "S3_BUCKET": "pps-reports-bucket",
        "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:pps-notifications",
        "FORTIGATE_VERIFY_SSL": "false",
        "LOG_LEVEL": "INFO",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture
def mock_secrets_manager(mocker):
    mock_sm = mocker.MagicMock()
    mock_sm.get_secret_value.return_value = {"SecretString": "dummy-fortigate-token"}
    mocker.patch("handler_executor.boto3.client", return_value=mock_sm)
    return mock_sm


class TestSuccessfulRevalidationExecutesAndReports:
    def test_passing_revalidation_executes_script_and_delivers_completed_report(
        self, executor_env, mocker, mock_secrets_manager
    ):
        script_sha256 = _valid_script_sha256()
        manifest = {**VALID_MANIFEST, "script_sha256": script_sha256}

        mocker.patch("handler_executor.s3_io.get_manifest", return_value=manifest)
        mocker.patch("handler_executor.s3_io.get_script", return_value=VALID_SCRIPT)

        mock_fgt_instance = mocker.MagicMock()
        mock_fgt_instance.get.return_value = [{"name": "admin"}]
        mocker.patch("handler_executor.FortiGateClient", return_value=mock_fgt_instance)

        deliver = mocker.patch(
            "handler_executor.reporter.deliver_policy_report",
            return_value={
                "uploaded": {"markdown": "reports/run-1/report.md"},
                "sns_published": True,
            },
        )

        result = handler_executor.lambda_handler(
            _invoke_event(script_sha256=script_sha256), _lambda_context()
        )

        assert result["status"] == "completed"
        assert result["findings_count"] == 1

        deliver.assert_called_once()
        _, kwargs = deliver.call_args
        assert kwargs["status"] == "completed"
        assert kwargs["failure_reason"] is None
        assert len(kwargs["findings"]) == 1
        assert kwargs["findings"][0]["check_id"] == "chk-0001"
        assert kwargs["findings"][0]["status"] == "fail"


class TestFailingRevalidationDoesNotExecute:
    def test_ast_disallowed_node_never_executes_and_writes_explicit_failure(
        self, executor_env, mocker, mock_secrets_manager
    ):
        malicious_script = "import os\nreport.finding('chk-0001', 'fail', 'x')\n"
        script_sha256 = hashlib.sha256(malicious_script.encode("utf-8")).hexdigest()
        manifest = {**VALID_MANIFEST, "script_sha256": script_sha256}

        mocker.patch("handler_executor.s3_io.get_manifest", return_value=manifest)
        mocker.patch("handler_executor.s3_io.get_script", return_value=malicious_script)

        fgt_class = mocker.patch("handler_executor.FortiGateClient")
        sandbox_execute = mocker.patch("handler_executor.sandbox.execute")

        deliver = mocker.patch(
            "handler_executor.reporter.deliver_policy_report",
            return_value={"uploaded": {}, "sns_published": True},
        )

        result = handler_executor.lambda_handler(
            _invoke_event(script_sha256=script_sha256), _lambda_context()
        )

        assert result["status"] == "could_not_audit"
        assert "revalidation_failed" in result["failure_reason"]
        assert "denied_node:Import" in result["failure_reason"]

        # Never executes, never even instantiates a FortiGate client
        sandbox_execute.assert_not_called()
        fgt_class.assert_not_called()

        deliver.assert_called_once()
        _, kwargs = deliver.call_args
        assert kwargs["status"] == "could_not_audit"
        assert "revalidation_failed" in kwargs["failure_reason"]

    def test_integrity_mismatch_never_reaches_ast_parse_and_is_rejected_first(
        self, executor_env, mocker, mock_secrets_manager
    ):
        """script_sha256 no coincide con el manifest -> se rechaza ANTES de
        validar el AST — defensa en profundidad contra un script mutado en S3."""
        tampered_script = "report.finding('chk-0001', 'fail', 'tampered')\n"
        manifest = {**VALID_MANIFEST, "script_sha256": "f" * 64}  # deliberately wrong

        mocker.patch("handler_executor.s3_io.get_manifest", return_value=manifest)
        mocker.patch("handler_executor.s3_io.get_script", return_value=tampered_script)

        validate_spy = mocker.patch("handler_executor.script_validator.validate")
        sandbox_execute = mocker.patch("handler_executor.sandbox.execute")

        deliver = mocker.patch(
            "handler_executor.reporter.deliver_policy_report",
            return_value={"uploaded": {}, "sns_published": True},
        )

        result = handler_executor.lambda_handler(
            _invoke_event(script_sha256="f" * 64), _lambda_context()
        )

        assert result["status"] == "could_not_audit"
        assert result["failure_reason"] == "integrity_check_failed"

        # Neither validation nor execution ever ran
        validate_spy.assert_not_called()
        sandbox_execute.assert_not_called()

        deliver.assert_called_once()
        _, kwargs = deliver.call_args
        assert kwargs["failure_reason"] == "integrity_check_failed"


class TestPartialFortiGateEndpointFailureTolerance:
    def test_one_unreachable_endpoint_does_not_block_findings_from_others(
        self, executor_env, mocker, mock_secrets_manager
    ):
        """spec.md 'Partial FortiGate Endpoint Failure Tolerance': un endpoint
        inalcanzable (get() -> None, como hace fortigate_client.get() ante un
        error de red real) no debe frenar el resto de la auditoría."""
        script = (
            "admins = fgt.get('admins')\n"
            "dns = fgt.get('dns')\n"
            "if admins:\n"
            "    report.finding('chk-0001', 'fail', 'hay admins')\n"
            "else:\n"
            "    report.finding('chk-0001', 'pass', 'sin admins')\n"
            "if dns is None:\n"
            "    report.note('chk-0002', 'endpoint dns inalcanzable')\n"
            "else:\n"
            "    report.finding('chk-0002', 'pass', 'dns ok')\n"
        )
        script_sha256 = hashlib.sha256(script.encode("utf-8")).hexdigest()
        manifest = {
            **VALID_MANIFEST,
            "script_sha256": script_sha256,
            "checks": [
                {
                    "check_id": "chk-0001",
                    "title": "Admins",
                    "clause_ref": {"page": 1, "quote": "x"},
                },
                {"check_id": "chk-0002", "title": "DNS", "clause_ref": {"page": 2, "quote": "y"}},
            ],
        }

        mocker.patch("handler_executor.s3_io.get_manifest", return_value=manifest)
        mocker.patch("handler_executor.s3_io.get_script", return_value=script)

        # Simulates fortigate_client.get(): "admins" reachable, "dns" unreachable
        # (real FortiGateClient.get() returns None on network failure, never raises).
        mock_fgt_instance = mocker.MagicMock()

        def fake_get(endpoint_key):
            return None if endpoint_key == "dns" else [{"name": "admin"}]

        mock_fgt_instance.get.side_effect = fake_get
        mocker.patch("handler_executor.FortiGateClient", return_value=mock_fgt_instance)

        deliver = mocker.patch(
            "handler_executor.reporter.deliver_policy_report",
            return_value={"uploaded": {}, "sns_published": True},
        )

        result = handler_executor.lambda_handler(
            _invoke_event(script_sha256=script_sha256), _lambda_context()
        )

        assert result["status"] == "completed"

        _, kwargs = deliver.call_args
        findings = kwargs["findings"]
        notes = kwargs["notes"]

        # Reachable endpoint produced a real finding
        assert any(f["check_id"] == "chk-0001" and f["status"] == "fail" for f in findings)
        # Unreachable endpoint recorded explicitly, audit continued anyway
        assert any(n["check_id"] == "chk-0002" for n in notes)
        assert not any(f["check_id"] == "chk-0002" for f in findings)


class TestSandboxBudgetExceededDuringExecution:
    def test_budget_exceeded_preserves_partial_findings_and_still_delivers_report(
        self, executor_env, mocker, mock_secrets_manager
    ):
        script = (
            "report.finding('chk-0001', 'pass', 'evidencia 1')\n"
            "report.finding('chk-0001', 'pass', 'evidencia 2')\n"
        )
        script_sha256 = hashlib.sha256(script.encode("utf-8")).hexdigest()
        manifest = {**VALID_MANIFEST, "script_sha256": script_sha256}

        mocker.patch("handler_executor.s3_io.get_manifest", return_value=manifest)
        mocker.patch("handler_executor.s3_io.get_script", return_value=script)
        mocker.patch("handler_executor.FortiGateClient")

        partial_findings = [{"check_id": "chk-0001", "status": "pass", "evidence": "evidencia 1"}]
        mocker.patch(
            "handler_executor.sandbox.execute",
            side_effect=sandbox.SandboxBudgetExceeded(
                "wall_clock_exceeded", "budget blown", partial_findings, []
            ),
        )

        deliver = mocker.patch(
            "handler_executor.reporter.deliver_policy_report",
            return_value={"uploaded": {}, "sns_published": True},
        )

        result = handler_executor.lambda_handler(
            _invoke_event(script_sha256=script_sha256), _lambda_context()
        )

        assert result["status"] == "completed"
        assert result["budget_exceeded"] == "wall_clock_exceeded"
        assert result["findings_count"] == 1

        _, kwargs = deliver.call_args
        assert kwargs["status"] == "completed"
        assert kwargs["findings"] == partial_findings
        assert any(n["check_id"] == "_sandbox" for n in kwargs["notes"])
