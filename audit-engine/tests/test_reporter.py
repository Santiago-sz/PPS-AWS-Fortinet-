"""
Tests para reporter.py.

- build_markdown_report / build_sns_message / generate_s3_key_prefix: puras,
  sin I/O — se testean directamente.
- upload_to_s3: se testea con moto (mock completo de S3, sin red real).
- publish_to_sns: se testea con unittest.mock (más simple que moto para un
  solo método con parámetros a verificar).
"""

import hashlib
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


REMEDIATION = {
    "summary": "Habilitar MFA para todas las cuentas administrativas.",
    "steps": ["System > Administrators > editar admin", "Activar two-factor authentication"],
    "fortigate_cli": (
        "config system admin\n    edit admin\n        set two-factor fortitoken\n    next\nend"
    ),
}

FAIL_WITH_REMEDIATION = {**TRACEABLE_FINDINGS[0], "remediation": REMEDIATION}
PASS_WITH_REMEDIATION = {**TRACEABLE_FINDINGS[1], "remediation": REMEDIATION}
INDETERMINATE_WITH_REMEDIATION = {
    **UNTRACEABLE_FINDING,
    "remediation": {"summary": "Revisar manualmente la configuracion DNS.", "steps": []},
}
EMPTY_REMEDIATION = {"summary": None, "steps": [], "fortigate_cli": None}


class TestRemediationSectionMarkdown:
    def _render(self, findings):
        return build_policy_report_markdown(
            findings=findings,
            notes=[],
            status="completed",
            run_id="run-rem",
            policy_key="policies/internal-access-control.pdf",
            timestamp="2025-02-01T00:00:00Z",
        )

    def test_fail_finding_renders_summary_steps_and_fenced_cli_with_disclaimer(self):
        md = self._render([FAIL_WITH_REMEDIATION])

        assert "## Remediaciones propuestas" in md
        assert reporter.REMEDIATION_DISCLAIMER in md
        assert "### `chk-mfa` (fail)" in md
        assert REMEDIATION["summary"] in md
        assert "1. System > Administrators > editar admin" in md
        assert "2. Activar two-factor authentication" in md
        # fenced CLI block, explicitly marked as not executed
        assert "NO ejecutada" in md
        assert "```\nconfig system admin\n" in md
        assert "set two-factor fortitoken" in md
        assert "\nend\n```" in md

    def test_pass_finding_with_remediation_is_not_listed(self):
        md = self._render([PASS_WITH_REMEDIATION])

        assert "## Remediaciones propuestas" not in md
        assert "set two-factor fortitoken" not in md

    def test_indeterminate_finding_listed_only_when_it_has_a_proposal(self):
        with_proposal = self._render([INDETERMINATE_WITH_REMEDIATION])
        assert "## Remediaciones propuestas" in with_proposal
        assert "### `chk-ghost` (indeterminate)" in with_proposal
        assert "Revisar manualmente la configuracion DNS." in with_proposal

        without_proposal = self._render([{**UNTRACEABLE_FINDING, "remediation": EMPTY_REMEDIATION}])
        assert "## Remediaciones propuestas" not in without_proposal

    def test_fail_finding_without_proposal_is_listed_with_explicit_placeholder(self):
        md = self._render([TRACEABLE_FINDINGS[0]])  # fail, no remediation key at all

        assert "### `chk-mfa` (fail)" in md
        assert "Sin propuesta de remediacion disponible" in md

    def test_section_comes_after_findings_table(self):
        md = self._render([FAIL_WITH_REMEDIATION])

        assert md.index("## Hallazgos") < md.index("## Remediaciones propuestas")

    def test_could_not_audit_never_renders_remediations(self):
        md = build_policy_report_markdown(
            findings=[],
            notes=[],
            status="could_not_audit",
            run_id="run-failed",
            policy_key="policies/broken.pdf",
            timestamp="2025-02-01T00:00:00Z",
            failure_reason="generation_failed",
        )
        assert "Remediaciones" not in md


class TestRemediationInJson:
    def test_remediation_always_present_and_count_only_counts_real_proposals(self):
        report = build_policy_report_json(
            findings=[
                FAIL_WITH_REMEDIATION,
                TRACEABLE_FINDINGS[1],  # no remediation key
                {**UNTRACEABLE_FINDING, "remediation": EMPTY_REMEDIATION},
            ],
            notes=[],
            status="completed",
            run_id="run-rem",
            policy_key="policies/x.pdf",
            timestamp="2025-02-01T00:00:00Z",
        )

        assert report["findings"][0]["remediation"] == REMEDIATION
        assert report["findings"][1]["remediation"] is None
        assert report["findings"][2]["remediation"] == EMPTY_REMEDIATION
        assert report["remediation_count"] == 1

    def test_count_remediations_helper(self):
        assert reporter.count_remediations([]) == 0
        assert reporter.count_remediations([FAIL_WITH_REMEDIATION, PASS_WITH_REMEDIATION]) == 2
        assert reporter.count_remediations([{"remediation": "not a dict"}]) == 0
        assert reporter.count_remediations([{"remediation": {"steps": ["x"]}}]) == 1

    def test_remediation_key_names_survive_the_api_sanitizer_pattern(self):
        """The local API drops keys matching script|code|password|secret|token|
        api_key|authorization|private_key. The proposal must use none of them."""
        import re

        pattern = re.compile(
            r"^(?:script(?:_.*)?|code)$|password|passwd|secret|token|api.?key|authorization|"
            r"private.?key",
            re.I,
        )
        for key in ("remediation", *REMEDIATION.keys()):
            assert not pattern.search(key), key


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
        assert result["uploaded"] == {
            "markdown": "reports/run-abc/report.md",
            "json": "reports/run-abc/report.json",
        }

        obj = s3.get_object(Bucket=bucket, Key="reports/run-abc/report.md")
        body = obj["Body"].read().decode("utf-8")
        assert "chk-mfa" in body
        assert "completed" in body

        json_obj = s3.get_object(Bucket=bucket, Key="reports/run-abc/report.json")
        assert json_obj["ContentType"] == "application/json; charset=utf-8"
        parsed = json.loads(json_obj["Body"].read().decode("utf-8"))
        assert parsed["run_id"] == "run-abc"
        assert parsed["policy_key"] == "policies/internal-access-control.pdf"
        # legacy analysis.json must NOT appear on the policy path
        listed = s3.list_objects_v2(Bucket=bucket, Prefix="reports/run-abc/")
        assert {o["Key"] for o in listed["Contents"]} == {
            "reports/run-abc/report.md",
            "reports/run-abc/report.json",
        }

    @mock_aws
    def test_missing_bucket_does_not_raise_and_still_publishes_sns(self, mocker):
        publish = mocker.patch("reporter.publish_to_sns", return_value=True)

        result = deliver_policy_report(
            bucket="bucket-que-no-existe",
            topic_arn="arn:aws:sns:us-east-1:123456789012:pps-notifications",
            run_id="run-nobucket",
            policy_key="policies/x.pdf",
            findings=[],
            notes=[],
            status="could_not_audit",
            timestamp="2025-02-01T00:00:00Z",
            failure_reason="generation_failed",
        )

        assert result["uploaded"] == {}
        publish.assert_called_once()

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

        # Policy path writes report.json (the key the local API bridge discovers),
        # never the legacy analysis.json.
        assert result["uploaded"]["json"] == "reports/run-cutoff/report.json"
        json_obj = s3.get_object(Bucket=bucket, Key="reports/run-cutoff/report.json")
        parsed = json.loads(json_obj["Body"].read().decode("utf-8"))
        assert parsed["status"] == "truncated"
        assert parsed["truncated"] is True
        assert "remediation_count" in parsed

        # The SNS subject/message must not read as a silent success.
        publish_kwargs = publish_spy.call_args.kwargs
        assert "TRUNCAT" in publish_kwargs["subject"].upper()
        assert "completed" not in publish_kwargs["subject"]


# ---------------------------------------------------------------------------
# Documentos de referencia por hallazgo (reporte policy-agnostic)
# ---------------------------------------------------------------------------

GOLDEN_FINDING = {
    "check_id": "chk-0001",
    "clause_ref": {
        "chunk_id": "chunk-0001",
        "heading_path": ["Articulo 1"],
        "page": 1,
        "quote": "Los administradores deben tener bloqueo de cuenta.",
    },
    "status": "fail",
    "evidence": "e",
    "endpoints_used": ["admins"],
    "traceable": True,
    "remediation": None,
}
GOLDEN_ARGS = ("completed", "run-1", "policies/norma.pdf", "2026-09-10T12:00:00Z")


def _with_references(finding: dict, references: list[dict]) -> dict:
    return {**finding, "references": references}


class TestPolicyReportWithoutReferencesIsByteIdentical:
    """Hashes calculados sobre el commit e86bbc1: un hallazgo sin la clave
    `references` (manifest sin el bloque) produce el reporte de siempre."""

    def test_markdown_is_unchanged(self):
        markdown = build_policy_report_markdown([GOLDEN_FINDING], [], *GOLDEN_ARGS)

        assert hashlib.sha256(markdown.encode("utf-8")).hexdigest() == (
            "e2d002d798beffaf0f89ae4d3170a939456ecf5e24e3a10e30fcc01ffc64a8f3"
        )
        assert "Documentación de referencia" not in markdown

    def test_json_is_unchanged(self):
        payload = build_policy_report_json([GOLDEN_FINDING], [], *GOLDEN_ARGS)
        encoded = json.dumps(payload, ensure_ascii=False)

        assert hashlib.sha256(encoded.encode("utf-8")).hexdigest() == (
            "27b1242249b28e9e077e4416b14c2ec57dbf2ac497eefe329eda8306ca2bf983"
        )
        assert "references" not in payload["findings"][0]


class TestReferencesInPolicyReport:
    REFERENCES = [
        {"source": "fortinet/hardening.pdf", "score": 0.91},
        {"source": "fortinet/hardening.pdf", "score": 0.4},
        {"source": "fortinet/cli-reference.pdf", "score": None},
        {"source": None, "score": 0.2},
    ]

    def test_json_keeps_the_references_of_each_finding(self):
        findings = [
            _with_references(GOLDEN_FINDING, self.REFERENCES),
            _with_references({**GOLDEN_FINDING, "check_id": "chk-0002"}, []),
        ]

        payload = build_policy_report_json(findings, [], *GOLDEN_ARGS)

        assert payload["findings"][0]["references"] == self.REFERENCES
        assert payload["findings"][1]["references"] == []

    def test_markdown_lists_reference_documents_per_finding(self):
        findings = [
            _with_references(GOLDEN_FINDING, self.REFERENCES),
            _with_references({**GOLDEN_FINDING, "check_id": "chk-0002"}, []),
        ]

        markdown = build_policy_report_markdown(findings, [], *GOLDEN_ARGS)

        assert "## Documentación de referencia" in markdown
        normative = self._section(markdown, "## Documentación de referencia")
        line_1 = next(ln for ln in normative.splitlines() if ln.startswith("- `chk-0001`"))
        # Un origen ausente no se puede clasificar como técnico: queda acá.
        assert "origen no informado" in line_1
        line_2 = next(ln for ln in normative.splitlines() if ln.startswith("- `chk-0002`"))
        assert "sin documentos de referencia" in line_2

        # Los documentos del fabricante son técnicos y van en su propia sección.
        technical = self._section(markdown, "## Referencias técnicas (no normativas)")
        tech_1 = next(ln for ln in technical.splitlines() if ln.startswith("- `chk-0001`"))
        # Un documento repetido se lista una vez, con su mejor puntaje.
        assert tech_1.count("fortinet/hardening.pdf") == 1
        assert "`fortinet/hardening.pdf` (puntaje 0.91)" in tech_1
        assert "`fortinet/cli-reference.pdf`" in tech_1
        assert "fortinet/" not in normative

    @staticmethod
    def _section(markdown: str, heading: str) -> str:
        """Texto de una sección, hasta el próximo encabezado de nivel 2."""
        return markdown.split(heading + "\n", 1)[1].split("\n## ", 1)[0]

    MIXED = [
        {"source": "nist/SP800-53r5.pdf", "score": 0.82},
        {"source": "propio/campos-fortios-7.6.8.md", "score": 0.95},
        {"source": "fortinet/hardening.pdf", "score": 0.6},
        {"source": "argentina/Disp-1-2022.pdf", "score": 0.5},
    ]

    def test_technical_sources_are_listed_apart_from_normative_ones(self):
        markdown = build_policy_report_markdown(
            [_with_references(GOLDEN_FINDING, self.MIXED)], [], *GOLDEN_ARGS
        )

        normative = self._section(markdown, "## Documentación de referencia")
        technical = self._section(markdown, "## Referencias técnicas (no normativas)")

        assert "`nist/SP800-53r5.pdf` (puntaje 0.82)" in normative
        assert "`argentina/Disp-1-2022.pdf` (puntaje 0.50)" in normative
        assert "propio/" not in normative
        assert "fortinet/" not in normative
        assert "`propio/campos-fortios-7.6.8.md` (puntaje 0.95)" in technical
        assert "`fortinet/hardening.pdf` (puntaje 0.60)" in technical
        assert "nist/" not in technical
        assert "argentina/" not in technical
        assert markdown.index("## Documentación de referencia") < markdown.index(
            "## Referencias técnicas (no normativas)"
        )

    def test_the_technical_section_says_it_is_not_normative(self):
        markdown = build_policy_report_markdown(
            [_with_references(GOLDEN_FINDING, self.MIXED)], [], *GOLDEN_ARGS
        )

        technical = self._section(markdown, "## Referencias técnicas (no normativas)")

        assert "no son normativa" in technical
        assert "fabricante" in technical

    def test_a_finding_with_only_technical_sources_says_so_in_the_normative_list(self):
        references = [{"source": "propio/nota.md", "score": 0.9}]

        markdown = build_policy_report_markdown(
            [_with_references(GOLDEN_FINDING, references)], [], *GOLDEN_ARGS
        )

        normative = self._section(markdown, "## Documentación de referencia")
        line = next(ln for ln in normative.splitlines() if ln.startswith("- `chk-0001`"))
        assert "sin documentos normativos" in line
        assert "propio/nota.md" not in normative

    def test_there_is_no_technical_section_without_technical_sources(self):
        references = [{"source": "nist/SP800-53r5.pdf", "score": 0.82}]

        markdown = build_policy_report_markdown(
            [_with_references(GOLDEN_FINDING, references)], [], *GOLDEN_ARGS
        )

        assert "## Documentación de referencia" in markdown
        assert "Referencias técnicas" not in markdown

    def test_a_kind_field_in_the_reference_is_tolerated_and_the_prefix_decides(self):
        # El reporte clasifica por la clave del documento, así que funciona
        # igual con referencias que traen `kind` y con las que no.
        references = [
            {"source": "propio/nota.md", "score": 0.9, "kind": "normative"},
            {"source": "nist/norma.pdf", "score": 0.8, "kind": "technical"},
        ]

        markdown = build_policy_report_markdown(
            [_with_references(GOLDEN_FINDING, references)], [], *GOLDEN_ARGS
        )

        assert "propio/nota.md" in self._section(
            markdown, "## Referencias técnicas (no normativas)"
        )
        assert "nist/norma.pdf" in self._section(markdown, "## Documentación de referencia")

    def test_markdown_states_references_do_not_change_the_result(self):
        markdown = build_policy_report_markdown(
            [_with_references(GOLDEN_FINDING, self.REFERENCES)], [], *GOLDEN_ARGS
        )

        assert "material de consulta" in markdown

    def test_markdown_neutralizes_backticks_in_a_source(self):
        references = [{"source": "fortinet/a`b.pdf", "score": 0.5}]

        markdown = build_policy_report_markdown(
            [_with_references(GOLDEN_FINDING, references)], [], *GOLDEN_ARGS
        )

        assert "`fortinet/a'b.pdf`" in markdown

    def test_truncated_report_also_shows_references(self):
        markdown = build_policy_report_markdown(
            [_with_references(GOLDEN_FINDING, self.REFERENCES)],
            [],
            "truncated",
            "run-1",
            "policies/norma.pdf",
            "2026-09-10T12:00:00Z",
            "wall_clock",
        )

        assert "## Documentación de referencia" in markdown


# ---------------------------------------------------------------------------
# Hallazgos degradados por datos no disponibles (decisión 12)
# ---------------------------------------------------------------------------

DEGRADED_FINDING = {
    **GOLDEN_FINDING,
    "check_id": "chk-0002",
    "status": "indeterminate",
    "evidence": "total_admins=0",
    "reported_status": "pass",
    "data_gaps": [{"endpoint": "admins", "kind": "empty_not_possible"}],
    "status_reason": "Datos no disponibles: el endpoint `admins` devolvió una respuesta vacía.",
}


class TestDataGapsInPolicyReport:
    def test_markdown_explains_why_the_finding_is_indeterminate(self):
        markdown = build_policy_report_markdown(
            [GOLDEN_FINDING, DEGRADED_FINDING], [], *GOLDEN_ARGS
        )

        assert "## Datos no disponibles" in markdown
        section = markdown.split("## Datos no disponibles")[1].split("\n## ")[0]
        line = next(ln for ln in section.splitlines() if ln.startswith("- `chk-0002`"))
        assert "`pass`" in line
        assert "`admins`" in line
        assert "chk-0001" not in section

    def test_markdown_table_shows_the_degraded_status_not_the_reported_one(self):
        markdown = build_policy_report_markdown([DEGRADED_FINDING], [], *GOLDEN_ARGS)

        row = next(ln for ln in markdown.splitlines() if ln.startswith("| `chk-0002`"))
        assert "| indeterminate |" in row

    def test_report_without_gaps_has_no_such_section(self):
        markdown = build_policy_report_markdown([GOLDEN_FINDING], [], *GOLDEN_ARGS)

        assert "Datos no disponibles" not in markdown

    def test_json_keeps_the_additive_keys(self):
        payload = build_policy_report_json([DEGRADED_FINDING], [], *GOLDEN_ARGS)

        finding = payload["findings"][0]
        assert finding["status"] == "indeterminate"
        assert finding["reported_status"] == "pass"
        assert finding["data_gaps"] == [{"endpoint": "admins", "kind": "empty_not_possible"}]
        assert "admins" in finding["status_reason"]

    def test_sns_message_counts_findings_degraded_by_missing_data(self):
        message = build_policy_sns_message(
            "completed", "run-1", [GOLDEN_FINDING, DEGRADED_FINDING], "reports/run-1/report.md"
        )

        assert "1 hallazgo(s) indeterminado(s) por datos no disponibles" in message

    def test_sns_message_without_gaps_is_unchanged(self):
        message = build_policy_sns_message(
            "completed", "run-1", [GOLDEN_FINDING], "reports/run-1/report.md"
        )

        assert "datos no disponibles" not in message
