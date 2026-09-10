"""
Tests para reporter.py.

- build_markdown_report / build_sns_message / generate_s3_key_prefix: puras,
  sin I/O — se testean directamente.
- upload_to_s3: se testea con moto (mock completo de S3, sin red real).
- publish_to_sns: se testea con unittest.mock (más simple que moto para un
  solo método con parámetros a verificar).
"""

import json

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from reporter import (
    build_markdown_report,
    build_sns_message,
    generate_s3_key_prefix,
    publish_to_sns,
    upload_to_s3,
)


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """Credenciales dummy para que boto3/moto no intenten resolver credenciales reales."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


class TestBuildMarkdownReport:
    def test_happy_path_contains_expected_sections(
        self, sample_claude_analysis, sample_device_info
    ):
        md = build_markdown_report(
            analysis=sample_claude_analysis,
            device_info=sample_device_info,
            timestamp="2025-01-15T10:30:00Z",
        )

        assert "# 🟠 Reporte de Postura de Seguridad — NIST CSF 2.0" in md
        assert "## 📋 Resumen Ejecutivo" in md
        assert "## 🚨 Problemas Críticos" in md
        assert "## ⚡ Quick Wins" in md
        assert "## 📊 Scores por Función NIST CSF 2.0" in md
        assert "## 🔍 Análisis Detallado por Función" in md
        for fn_name in sample_claude_analysis["functions"]:
            assert fn_name in md

    def test_error_analysis_produces_error_report(self, sample_device_info):
        analysis = {"error": "HTTP 529", "detail": "Overloaded"}
        md = build_markdown_report(analysis, sample_device_info, "2025-01-15T10:30:00Z")

        assert "⚠️ Error en el Análisis PPS" in md
        assert "HTTP 529" in md
        assert "Overloaded" in md
        # No debe intentar acceder a "functions" ni romper con KeyError
        assert "functions" not in md.lower() or "## 📊" not in md

    def test_missing_optional_fields_use_placeholders(self, sample_device_info):
        analysis = {"overall_score": 3.0, "functions": {}}
        md = build_markdown_report(analysis, sample_device_info, "2025-01-15T10:30:00Z")
        assert "Sin resumen disponible." in md


class TestBuildSnsMessage:
    def test_happy_path(self, sample_claude_analysis, sample_device_info):
        msg = build_sns_message(
            analysis=sample_claude_analysis,
            device_info=sample_device_info,
            timestamp="2025-01-15T10:30:00Z",
            s3_key="reports/192-168-1-1/2025-01-15/T103000/report.md",
        )
        assert "PPS Security Assessment" in msg
        assert "3.2/5.0" in msg
        assert "🚨 Problemas críticos (1):" in msg
        assert "reports/192-168-1-1/2025-01-15/T103000/report.md" in msg

    def test_truncates_critical_issues_to_three(self, sample_device_info):
        analysis = {
            "overall_score": 2.0,
            "functions": {},
            "critical_issues": [f"issue {i}" for i in range(5)],
        }
        msg = build_sns_message(analysis, sample_device_info, "ts", "s3key")
        assert "issue 0" in msg and "issue 1" in msg and "issue 2" in msg
        assert "issue 3" not in msg
        assert "... y 2 más" in msg

    def test_error_analysis_produces_error_message(self, sample_device_info):
        analysis = {"error": "fortigate_unreachable", "detail": "0/11 endpoints"}
        msg = build_sns_message(analysis, sample_device_info, "ts", "s3key")
        assert "⚠️ ERROR en PPS Assessment" in msg
        assert "fortigate_unreachable" in msg


class TestGenerateS3KeyPrefix:
    def test_sanitizes_host_and_splits_date_time(self):
        prefix = generate_s3_key_prefix(host="192.168.1.1", timestamp="2025-01-15T10:30:45Z")
        assert prefix == "reports/192-168-1-1/2025-01-15/T103045"

    def test_fallback_on_unparseable_timestamp(self):
        # Timestamp con formato inesperado -> no debe lanzar excepción
        prefix = generate_s3_key_prefix(host="1.2.3.4", timestamp="not-a-real-timestamp")
        assert prefix.startswith("reports/1-2-3-4/")


class TestUploadToS3:
    @mock_aws
    def test_uploads_both_files_with_correct_params(self):
        bucket = "pps-reports-bucket"
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=bucket)

        result = upload_to_s3(
            bucket=bucket,
            s3_key_prefix="reports/192-168-1-1/2025-01-15/T103000",
            markdown_report="# Reporte",
            analysis={"overall_score": 3.0},
            timestamp="2025-01-15T10:30:00Z",
        )

        assert result == {
            "markdown": "reports/192-168-1-1/2025-01-15/T103000/report.md",
            "json": "reports/192-168-1-1/2025-01-15/T103000/analysis.json",
        }

        md_obj = s3.get_object(Bucket=bucket, Key=result["markdown"])
        assert md_obj["Body"].read().decode("utf-8") == "# Reporte"
        assert md_obj["ContentType"] == "text/markdown; charset=utf-8"

        json_obj = s3.get_object(Bucket=bucket, Key=result["json"])
        assert json.loads(json_obj["Body"].read().decode("utf-8")) == {"overall_score": 3.0}

    @mock_aws
    def test_bucket_does_not_exist_returns_partial_or_empty_dict(self):
        """Si el bucket no existe, put_object lanza ClientError — upload_to_s3
        debe capturarlo y devolver un dict sin esa clave, nunca crashear."""
        result = upload_to_s3(
            bucket="bucket-que-no-existe",
            s3_key_prefix="reports/x",
            markdown_report="# Reporte",
            analysis={},
            timestamp="2025-01-15T10:30:00Z",
        )
        assert result == {}


class TestPublishToSns:
    def test_publish_success(self, mocker):
        mock_sns = mocker.MagicMock()
        mock_sns.publish.return_value = {"MessageId": "abc-123"}
        mocker.patch("reporter.boto3.client", return_value=mock_sns)

        ok = publish_to_sns(
            topic_arn="arn:aws:sns:us-east-1:123456789012:pps-notifications",
            message="🚨 critical stuff",
            subject="PPS Assessment",
        )

        assert ok is True
        mock_sns.publish.assert_called_once_with(
            TopicArn="arn:aws:sns:us-east-1:123456789012:pps-notifications",
            Message="🚨 critical stuff",
            Subject="PPS Assessment",
            MessageAttributes={"severity": {"DataType": "String", "StringValue": "critical"}},
        )

    def test_publish_marks_severity_info_when_no_emoji(self, mocker):
        mock_sns = mocker.MagicMock()
        mock_sns.publish.return_value = {"MessageId": "abc-123"}
        mocker.patch("reporter.boto3.client", return_value=mock_sns)

        publish_to_sns(topic_arn="arn:...", message="all good", subject="PPS Assessment")

        assert (
            mock_sns.publish.call_args.kwargs["MessageAttributes"]["severity"]["StringValue"]
            == "info"
        )

    def test_publish_failure_returns_false(self, mocker):
        mock_sns = mocker.MagicMock()
        mock_sns.publish.side_effect = ClientError(
            {"Error": {"Code": "NotFound", "Message": "Topic not found"}}, "Publish"
        )
        mocker.patch("reporter.boto3.client", return_value=mock_sns)

        ok = publish_to_sns(topic_arn="arn:bad", message="msg", subject="subj")

        assert ok is False
