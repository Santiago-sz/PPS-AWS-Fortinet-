"""
Tests para handler.py — el orquestador.

Mockea los 3 módulos colaboradores (fortigate_client, analyzer, reporter)
y boto3 (Secrets Manager) — nunca llama a servicios reales.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from botocore.exceptions import ClientError

import handler

LAMBDA_TF_PATH = Path(__file__).resolve().parents[2] / "terraform" / "lambda.tf"


def _lambda_context():
    return SimpleNamespace(aws_request_id="test-request-id-123")


class TestRequiredEnvVars:
    def test_missing_env_var_fails_fast_with_clear_error(self, monkeypatch, mocker):
        """Si falta una env var requerida, debe devolver 500 sin intentar
        tocar Secrets Manager, FortiGate, Claude ni S3/SNS."""
        # No seteamos ninguna env var requerida.
        for var in (
            "FORTIGATE_HOST",
            "FORTIGATE_SECRET_ARN",
            "CLAUDE_SECRET_ARN",
            "S3_BUCKET",
            "SNS_TOPIC_ARN",
        ):
            monkeypatch.delenv(var, raising=False)

        spy_boto_client = mocker.patch("handler.boto3.client")
        spy_fgt_client = mocker.patch("handler.FortiGateClient")
        spy_analyze = mocker.patch("handler.analyze")

        result = handler.lambda_handler({}, _lambda_context())

        assert result["statusCode"] == 500
        assert result["error"] == "missing_env_vars"
        assert "FORTIGATE_HOST" in result["detail"]
        spy_boto_client.assert_not_called()
        spy_fgt_client.assert_not_called()
        spy_analyze.assert_not_called()

    def test_missing_only_one_env_var_still_fails(self, required_env, monkeypatch, mocker):
        monkeypatch.delenv("S3_BUCKET", raising=False)
        mocker.patch("handler.boto3.client")

        result = handler.lambda_handler({}, _lambda_context())

        assert result["statusCode"] == 500
        assert result["error"] == "missing_env_vars"
        assert "S3_BUCKET" in result["detail"]


class TestHappyPathOrchestration:
    def test_orchestrates_full_flow_in_order(
        self,
        required_env,
        mocker,
        sample_fortigate_data,
        sample_claude_analysis,
    ):
        call_order = []

        # ── Secrets Manager ──
        mock_sm = mocker.MagicMock()
        mock_sm.get_secret_value.side_effect = lambda SecretId: {
            "SecretString": f"secret-for-{SecretId}"
        }
        mocker.patch("handler.boto3.client", return_value=mock_sm)

        # ── FortiGate ──
        mock_fgt_instance = mocker.MagicMock()
        mock_fgt_instance.collect_all.side_effect = lambda: (
            call_order.append("collect_all"),
            sample_fortigate_data,
        )[1]
        mock_fgt_class = mocker.patch("handler.FortiGateClient", return_value=mock_fgt_instance)

        # ── Analyzer ──
        def fake_analyze(**kwargs):
            call_order.append("analyze")
            return sample_claude_analysis

        mocker.patch("handler.analyze", side_effect=fake_analyze)

        # ── Reporter ──
        def fake_build_md(**kwargs):
            call_order.append("build_markdown_report")
            return "# Reporte"

        def fake_upload(**kwargs):
            call_order.append("upload_to_s3")
            return {"markdown": "reports/x/report.md", "json": "reports/x/analysis.json"}

        def fake_build_sns(**kwargs):
            call_order.append("build_sns_message")
            return "sns body"

        def fake_publish(**kwargs):
            call_order.append("publish_to_sns")
            return True

        mocker.patch("handler.build_markdown_report", side_effect=fake_build_md)
        mocker.patch("handler.generate_s3_key_prefix", return_value="reports/x")
        mocker.patch("handler.upload_to_s3", side_effect=fake_upload)
        mocker.patch("handler.build_sns_message", side_effect=fake_build_sns)
        mocker.patch("handler.publish_to_sns", side_effect=fake_publish)

        result = handler.lambda_handler({}, _lambda_context())

        # Orden de orquestación: FortiGate -> Claude -> reporte -> S3 -> SNS
        assert call_order == [
            "collect_all",
            "analyze",
            "build_markdown_report",
            "upload_to_s3",
            "build_sns_message",
            "publish_to_sns",
        ]

        # FortiGateClient se instanció con las credenciales correctas
        mock_fgt_class.assert_called_once_with(
            host=required_env["FORTIGATE_HOST"],
            token=f"secret-for-{required_env['FORTIGATE_SECRET_ARN']}",
            verify_ssl=False,  # FORTIGATE_VERIFY_SSL="false" en el fixture
        )

        assert result["statusCode"] == 200
        assert result["analysis_ok"] is True
        assert result["sns_published"] is True
        assert result["overall_score"] == sample_claude_analysis["overall_score"]
        assert result["endpoints_collected"] == sum(
            1 for v in sample_fortigate_data.values() if v is not None
        )


class TestPartialFailures:
    def test_fortigate_completely_unreachable_returns_503_without_calling_claude(
        self, required_env, mocker
    ):
        mock_sm = mocker.MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": "dummy-secret"}
        mocker.patch("handler.boto3.client", return_value=mock_sm)

        all_none_data = {
            "system_global": None,
            "interfaces": None,
            "admins": None,
            "dns": None,
            "firewall_policies": None,
            "vpn_ipsec": None,
            "vpn_ssl": None,
            "local_users": None,
            "ips_sensors": None,
            "av_profiles": None,
            "webfilter_profiles": None,
        }
        mock_fgt_instance = mocker.MagicMock()
        mock_fgt_instance.collect_all.return_value = all_none_data
        mocker.patch("handler.FortiGateClient", return_value=mock_fgt_instance)

        mock_analyze = mocker.patch("handler.analyze")

        result = handler.lambda_handler({}, _lambda_context())

        assert result["statusCode"] == 503
        assert result["error"] == "fortigate_unreachable"
        mock_analyze.assert_not_called()

    def test_secrets_manager_failure_returns_500_without_calling_fortigate(
        self, required_env, mocker
    ):
        mock_sm = mocker.MagicMock()
        mock_sm.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
            "GetSecretValue",
        )
        mocker.patch("handler.boto3.client", return_value=mock_sm)
        mock_fgt_class = mocker.patch("handler.FortiGateClient")

        result = handler.lambda_handler({}, _lambda_context())

        assert result["statusCode"] == 500
        assert result["error"] == "secrets_error"
        mock_fgt_class.assert_not_called()

    def test_claude_analysis_error_still_generates_and_uploads_report(
        self, required_env, mocker, sample_fortigate_data
    ):
        """Si Claude devuelve un dict con 'error', el handler NO debe abortar:
        genera igual un reporte de error y lo sube a S3/SNS (207 Multi-Status)."""
        mock_sm = mocker.MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": "dummy-secret"}
        mocker.patch("handler.boto3.client", return_value=mock_sm)

        mock_fgt_instance = mocker.MagicMock()
        mock_fgt_instance.collect_all.return_value = sample_fortigate_data
        mocker.patch("handler.FortiGateClient", return_value=mock_fgt_instance)

        mocker.patch(
            "handler.analyze", return_value={"error": "json_parse_error", "raw": "not json"}
        )
        mock_build_md = mocker.patch("handler.build_markdown_report", return_value="# Error")
        mocker.patch("handler.generate_s3_key_prefix", return_value="reports/x")
        mocker.patch(
            "handler.upload_to_s3",
            return_value={"markdown": "reports/x/report.md", "json": "reports/x/analysis.json"},
        )
        mocker.patch("handler.build_sns_message", return_value="sns body")
        mocker.patch("handler.publish_to_sns", return_value=True)

        result = handler.lambda_handler({}, _lambda_context())

        assert result["statusCode"] == 207
        assert result["analysis_ok"] is False
        assert result["overall_score"] is None
        mock_build_md.assert_called_once()


class TestTerraformEnvVarsMatchHandler:
    """Pre-existing defect (design.md): lambda.tf injected REPORTS_BUCKET but
    handler.py reads S3_BUCKET via _get_required_env(), and lambda.tf never set
    FORTIGATE_HOST at all. Local tests never caught this because required_env
    sets env vars directly, bypassing Terraform entirely — only a real deploy
    would fail. This test reads the actual lambda.tf environment block so the
    IaC/code contract is verified in CI, not just at runtime in AWS."""

    @staticmethod
    def _read_environment_block() -> str:
        tf_text = LAMBDA_TF_PATH.read_text(encoding="utf-8")
        match = re.search(
            r'resource\s+"aws_lambda_function"\s+"assessor"\s*\{(.*?)\n\}\n',
            tf_text,
            re.DOTALL,
        )
        assert match, "Could not find aws_lambda_function.assessor block in lambda.tf"
        assessor_block = match.group(1)
        env_match = re.search(r"variables\s*=\s*\{(.*?)\n\s*\}\n", assessor_block, re.DOTALL)
        assert env_match, "No environment { variables = {...} } block found for assessor lambda"
        return env_match.group(1)

    def test_assessor_lambda_supplies_every_env_var_handler_requires(self):
        env_block = self._read_environment_block()

        required_names = {
            "FORTIGATE_HOST",
            "FORTIGATE_SECRET_ARN",
            "CLAUDE_SECRET_ARN",
            "S3_BUCKET",
            "SNS_TOPIC_ARN",
        }
        missing = {
            name for name in required_names if not re.search(rf"\b{name}\b\s*=", env_block)
        }
        assert not missing, (
            f"lambda.tf environment.variables is missing {sorted(missing)}, but "
            f"handler.py's _get_required_env() requires them — real deploy would "
            f"fail with statusCode 500/missing_env_vars"
        )

    def test_assessor_lambda_does_not_reintroduce_reports_bucket_mismatch(self):
        env_block = self._read_environment_block()

        assert not re.search(r"\bREPORTS_BUCKET\b\s*=", env_block), (
            "lambda.tf sets 'REPORTS_BUCKET' but handler.py reads os.environ['S3_BUCKET'] "
            "— rename the Terraform env var key to S3_BUCKET to match handler.py"
        )
