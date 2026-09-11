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

import reporter
from reporter import (
    build_markdown_report,
    build_policy_report_json,
    build_policy_report_markdown,
    build_policy_sns_message,
    build_sns_message,
    deliver_policy_report,
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


# ─── Policy-agnostic reporting (Phase 7) ────────────────────────────────────
#
# The functions above (build_markdown_report / build_sns_message) stay
# hardcoded to NIST CSF 2.0 on purpose -- they back the legacy path gated by
# `enable_legacy_nist_schedule` (design.md Decision #9) and MUST keep
# passing unmodified. The functions below are ADDITIONAL and framework
# agnostic: they render from `Finding`/`RunManifest` (design.md Interfaces),
# never from a NIST-shaped `analysis` dict.

# A completely non-NIST policy: an internal access-control/network-hardening
# normativa with its own check ids and clause structure
# (design.md ClauseRef = {"chunk_id","heading_path","page","quote"}).
TRACEABLE_FINDINGS = [
    {
        "check_id": "chk-mfa",
        "clause_ref": {
            "chunk_id": "c1",
            "heading_path": ["4. Access Control", "4.2 MFA"],
            "page": 7,
            "quote": "MFA is mandatory for all administrative access.",
        },
        "status": "fail",
        "evidence": "No se detectó MFA habilitado en los usuarios admin.",
        "endpoints_used": ["admins"],
        "traceable": True,
    },
    {
        "check_id": "chk-dns",
        "clause_ref": {
            "chunk_id": "c2",
            "heading_path": ["6. Network Hardening"],
            "page": 12,
            "quote": "DNS servers must be internally managed.",
        },
        "status": "pass",
        "evidence": "DNS primario configurado internamente.",
        "endpoints_used": ["dns"],
        "traceable": True,
    },
]

# `clause_ref` is None + `traceable=False` — the shape `ReportCapability`
# produces when `check_id` isn't in the manifest (test_toolkit.py).
UNTRACEABLE_FINDING = {
    "check_id": "chk-ghost",
    "clause_ref": None,
    "status": "indeterminate",
    "evidence": "check_id no encontrado en el manifest",
    "endpoints_used": [],
    "traceable": False,
}

# Defensive edge case: toolkit marked it traceable, but the clause_ref
# itself is malformed (missing "quote") -- the reporter must not trust
# `traceable=True` blindly; it must validate the clause_ref shape itself.
INVALID_CLAUSE_FINDING = {
    "check_id": "chk-broken",
    "clause_ref": {"page": 3},
    "status": "pass",
    "evidence": "evidencia sin cita utilizable",
    "endpoints_used": [],
    "traceable": True,
}


class TestBuildPolicyReportMarkdown:
    def test_non_nist_policy_renders_findings_and_clause_citations(self):
        md = build_policy_report_markdown(
            findings=TRACEABLE_FINDINGS,
            notes=[],
            status="completed",
            run_id="run-abc",
            policy_key="policies/internal-access-control.pdf",
            timestamp="2025-02-01T00:00:00Z",
        )

        assert "chk-mfa" in md
        assert "MFA is mandatory for all administrative access." in md
        assert "chk-dns" in md
        assert "DNS servers must be internally managed." in md
        assert "completed" in md
        assert "NIST" not in md

    def test_untraceable_finding_is_flagged_not_silently_included(self):
        md = build_policy_report_markdown(
            findings=[UNTRACEABLE_FINDING],
            notes=[],
            status="completed",
            run_id="run-abc",
            policy_key="policies/internal-access-control.pdf",
            timestamp="2025-02-01T00:00:00Z",
        )

        assert "chk-ghost" in md
        # Must be visibly flagged, never rendered as if it had a real citation.
        assert "no trazable" in md.lower()
        assert "p. " not in md  # no fabricated page reference

    def test_invalid_clause_ref_missing_quote_is_flagged_untraceable(self):
        # Even though the input finding says traceable=True, the clause_ref
        # itself is incomplete -- the reporter must catch this independently.
        md = build_policy_report_markdown(
            findings=[INVALID_CLAUSE_FINDING],
            notes=[],
            status="completed",
            run_id="run-abc",
            policy_key="policies/internal-access-control.pdf",
            timestamp="2025-02-01T00:00:00Z",
        )

        assert "chk-broken" in md
        assert "no trazable" in md.lower()

    def test_could_not_audit_status_visibly_distinguished_from_success(self):
        md = build_policy_report_markdown(
            findings=[],
            notes=[],
            status="could_not_audit",
            run_id="run-failed",
            policy_key="policies/broken.pdf",
            timestamp="2025-02-01T00:00:00Z",
            failure_reason="generation_failed",
        )

        assert "could not audit" in md
        assert "generation_failed" in md
        assert "completed" not in md
        # could_not_audit never had any findings to begin with -- there is no
        # table to show, so it must NOT render one.
        assert "## Hallazgos" not in md


class TestBuildPolicyReportMarkdownTruncated:
    """spec.md 'Script exceeds wall-clock cutoff': partial findings collected
    before a sandbox budget cutoff MUST be preserved and reported -- but
    truncated MUST look neither like a clean `completed` report nor like a
    `could_not_audit` report with no findings table at all."""

    def test_truncated_shows_warning_header_and_still_renders_findings_table(self):
        md = build_policy_report_markdown(
            findings=TRACEABLE_FINDINGS,
            notes=[
                {
                    "check_id": "_sandbox",
                    "message": "execution terminated early: wall_clock_exceeded",
                }
            ],
            status="truncated",
            run_id="run-cutoff",
            policy_key="policies/internal-access-control.pdf",
            timestamp="2025-02-01T00:00:00Z",
            failure_reason="wall_clock_exceeded",
        )

        # Impossible-to-miss warning, at the same visual emphasis level as
        # could_not_audit's header (same leading "⚠️" marker).
        assert "⚠️" in md.splitlines()[0]
        assert "TRUNCAD" in md.upper()
        assert "wall_clock_exceeded" in md

        # Unlike could_not_audit, the partial findings that WERE collected
        # must still show up in a real findings table.
        assert "## Hallazgos" in md
        assert "chk-mfa" in md
        assert "MFA is mandatory for all administrative access." in md
        assert "chk-dns" in md

    def test_truncated_is_not_confused_with_clean_completed_report(self):
        md = build_policy_report_markdown(
            findings=TRACEABLE_FINDINGS,
            notes=[],
            status="truncated",
            run_id="run-cutoff",
            policy_key="policies/internal-access-control.pdf",
            timestamp="2025-02-01T00:00:00Z",
            failure_reason="call_count_exceeded",
        )

        # The clean-success header/status line must never appear here.
        assert "✅ Reporte de Auditoría de Política" not in md
        assert "**Status:** completed" not in md

    def test_truncated_with_zero_findings_still_shows_warning_not_could_not_audit_wording(self):
        md = build_policy_report_markdown(
            findings=[],
            notes=[
                {
                    "check_id": "_sandbox",
                    "message": "execution terminated early: call_count_exceeded",
                }
            ],
            status="truncated",
            run_id="run-cutoff",
            policy_key="policies/internal-access-control.pdf",
            timestamp="2025-02-01T00:00:00Z",
            failure_reason="call_count_exceeded",
        )

        assert "TRUNCAD" in md.upper()
        assert "could not audit" not in md


class TestBuildPolicyReportJson:
    def test_completed_report_includes_status_and_findings(self):
        report = build_policy_report_json(
            findings=TRACEABLE_FINDINGS,
            notes=[],
            status="completed",
            run_id="run-abc",
            policy_key="policies/internal-access-control.pdf",
            timestamp="2025-02-01T00:00:00Z",
        )

        assert report["status"] == "completed"
        assert report["run_id"] == "run-abc"
        assert len(report["findings"]) == 2
        assert report["findings"][0]["traceable"] is True
        assert report["findings"][0]["clause_ref"]["quote"] == (
            "MFA is mandatory for all administrative access."
        )

    def test_invalid_clause_ref_marked_untraceable_even_if_input_said_true(self):
        report = build_policy_report_json(
            findings=[INVALID_CLAUSE_FINDING],
            notes=[],
            status="completed",
            run_id="run-abc",
            policy_key="policies/internal-access-control.pdf",
            timestamp="2025-02-01T00:00:00Z",
        )

        assert report["findings"][0]["traceable"] is False

    def test_could_not_audit_status_is_distinct_value_with_failure_reason(self):
        report = build_policy_report_json(
            findings=[],
            notes=[],
            status="could_not_audit",
            run_id="run-failed",
            policy_key="policies/broken.pdf",
            timestamp="2025-02-01T00:00:00Z",
            failure_reason="no_verifiable_controls",
        )

        assert report["status"] == "could_not_audit"
        assert report["status"] != "completed"
        assert report["failure_reason"] == "no_verifiable_controls"

    def test_truncated_status_is_distinct_value_with_top_level_truncated_flag(self):
        """The truncation signal MUST live in an easy-to-check top-level field
        for an automated consumer -- not buried in `notes`."""
        report = build_policy_report_json(
            findings=TRACEABLE_FINDINGS,
            notes=[
                {
                    "check_id": "_sandbox",
                    "message": "execution terminated early: wall_clock_exceeded",
                }
            ],
            status="truncated",
            run_id="run-cutoff",
            policy_key="policies/internal-access-control.pdf",
            timestamp="2025-02-01T00:00:00Z",
            failure_reason="wall_clock_exceeded",
        )

        assert report["status"] == "truncated"
        assert report["status"] != "completed"
        assert report["status"] != "could_not_audit"
        assert report["failure_reason"] == "wall_clock_exceeded"
        # Findings collected before the cutoff are preserved, unlike could_not_audit.
        assert len(report["findings"]) == 2
        # Top-level, unambiguous boolean signal -- a consumer that only checks
        # `report["truncated"]` (without special-casing the exact status
        # string) still gets the correct answer.
        assert report["truncated"] is True

    def test_completed_and_could_not_audit_have_truncated_false(self):
        completed = build_policy_report_json(
            findings=[],
            notes=[],
            status="completed",
            run_id="run-ok",
            policy_key="policies/x.pdf",
            timestamp="2025-02-01T00:00:00Z",
        )
        failed = build_policy_report_json(
            findings=[],
            notes=[],
            status="could_not_audit",
            run_id="run-failed",
            policy_key="policies/x.pdf",
            timestamp="2025-02-01T00:00:00Z",
            failure_reason="generation_failed",
        )

        assert completed["truncated"] is False
        assert failed["truncated"] is False


class TestBuildPolicySnsMessage:
    def test_completed_message_mentions_run_and_report_key(self):
        msg = build_policy_sns_message(
            status="completed",
            run_id="run-abc",
            findings=TRACEABLE_FINDINGS,
            s3_key="reports/run-abc/report.md",
        )

        assert "run-abc" in msg
        assert "reports/run-abc/report.md" in msg

    def test_could_not_audit_message_visibly_distinguished(self):
        msg = build_policy_sns_message(
            status="could_not_audit",
            run_id="run-failed",
            findings=[],
            s3_key="reports/run-failed/report.md",
            failure_reason="generation_failed",
        )

        assert "could not audit" in msg
        assert "generation_failed" in msg

    def test_truncated_message_visibly_distinguished_from_completed_and_could_not_audit(self):
        msg = build_policy_sns_message(
            status="truncated",
            run_id="run-cutoff",
            findings=TRACEABLE_FINDINGS,
            s3_key="reports/run-cutoff/report.md",
            failure_reason="wall_clock_exceeded",
        )

        assert "run-cutoff" in msg
        assert "wall_clock_exceeded" in msg
        assert "TRUNCAD" in msg.upper()
        assert "could not audit" not in msg
        assert "✅" not in msg


class TestDeliverPolicyReport:
    @mock_aws
    def test_completed_path_uploads_to_s3_and_publishes_sns(self):
        bucket = "pps-reports-bucket"
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=bucket)
        sns = boto3.client("sns", region_name="us-east-1")
        topic_arn = sns.create_topic(Name="pps-notifications")["TopicArn"]

        result = deliver_policy_report(
            bucket=bucket,
            topic_arn=topic_arn,
            run_id="run-abc",
            policy_key="policies/internal-access-control.pdf",
            findings=TRACEABLE_FINDINGS,
            notes=[],
            status="completed",
            timestamp="2025-02-01T00:00:00Z",
        )

        assert result["status"] == "completed"
        assert result["sns_published"] is True
        assert result["uploaded"]["markdown"] == "reports/run-abc/report.md"

        obj = s3.get_object(Bucket=bucket, Key="reports/run-abc/report.md")
        body = obj["Body"].read().decode("utf-8")
        assert "chk-mfa" in body
        assert "completed" in body

    @mock_aws
    def test_could_not_audit_path_still_uploads_and_publishes(self):
        bucket = "pps-reports-bucket"
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=bucket)
        sns = boto3.client("sns", region_name="us-east-1")
        topic_arn = sns.create_topic(Name="pps-notifications")["TopicArn"]

        result = deliver_policy_report(
            bucket=bucket,
            topic_arn=topic_arn,
            run_id="run-failed",
            policy_key="policies/broken.pdf",
            findings=[],
            notes=[],
            status="could_not_audit",
            timestamp="2025-02-01T00:00:00Z",
            failure_reason="generation_failed",
        )

        assert result["status"] == "could_not_audit"
        assert result["sns_published"] is True

        obj = s3.get_object(Bucket=bucket, Key="reports/run-failed/report.md")
        body = obj["Body"].read().decode("utf-8")
        assert "could not audit" in body

    @mock_aws
    def test_truncated_path_uploads_findings_table_and_publishes_distinct_subject(self, mocker):
        bucket = "pps-reports-bucket"
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=bucket)
        sns = boto3.client("sns", region_name="us-east-1")
        topic_arn = sns.create_topic(Name="pps-notifications")["TopicArn"]

        publish_spy = mocker.spy(reporter, "publish_to_sns")

        result = deliver_policy_report(
            bucket=bucket,
            topic_arn=topic_arn,
            run_id="run-cutoff",
            policy_key="policies/internal-access-control.pdf",
            findings=TRACEABLE_FINDINGS,
            notes=[
                {
                    "check_id": "_sandbox",
                    "message": "execution terminated early: wall_clock_exceeded",
                }
            ],
            status="truncated",
            timestamp="2025-02-01T00:00:00Z",
            failure_reason="wall_clock_exceeded",
        )

        assert result["status"] == "truncated"
        assert result["sns_published"] is True

        obj = s3.get_object(Bucket=bucket, Key="reports/run-cutoff/report.md")
        body = obj["Body"].read().decode("utf-8")
        assert "chk-mfa" in body
        assert "TRUNCAD" in body.upper()
        assert "could not audit" not in body

        json_obj = s3.get_object(Bucket=bucket, Key="reports/run-cutoff/analysis.json")
        parsed = json.loads(json_obj["Body"].read().decode("utf-8"))
        assert parsed["status"] == "truncated"
        assert parsed["truncated"] is True

        # The SNS subject/message must not read as a silent success.
        publish_kwargs = publish_spy.call_args.kwargs
        assert "TRUNCAT" in publish_kwargs["subject"].upper()
        assert "completed" not in publish_kwargs["subject"]
