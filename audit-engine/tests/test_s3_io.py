"""
Tests para s3_io.py.

Usa moto (`@mock_aws`) para simular S3 real sin red — mismo patrón que
`test_reporter.py::TestUploadToS3`. Nunca se hace red real.
"""

import hashlib
import json

import boto3
import pytest
from moto import mock_aws

from s3_io import (
    build_manifest,
    get_manifest,
    get_policy,
    get_script,
    put_manifest,
    put_report,
    put_script,
)

BUCKET = "pps-test-bucket"


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """Credenciales dummy para que boto3/moto no intenten resolver credenciales reales."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def bucket():
    """Bucket S3 vacío, creado en el mock de moto, listo para leer/escribir."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        yield BUCKET


class TestGetPolicy:
    def test_get_policy_returns_raw_bytes(self, bucket):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.put_object(Bucket=bucket, Key="policies/norma.pdf", Body=b"%PDF-1.4 contenido")

        result = get_policy(bucket, "policies/norma.pdf")

        assert result == b"%PDF-1.4 contenido"
        assert isinstance(result, bytes)


class TestPutScript:
    def test_put_script_writes_exact_bytes_and_returns_matching_sha256(self, bucket):
        source = "def check(fgt, report):\n    report.finding('chk1', 'pass', 'ok')\n"

        script_sha256 = put_script(bucket, "artifacts/run-1/script.py", source)

        s3 = boto3.client("s3", region_name="us-east-1")
        obj = s3.get_object(Bucket=bucket, Key="artifacts/run-1/script.py")
        written_bytes = obj["Body"].read()

        assert written_bytes == source.encode("utf-8")
        assert script_sha256 == hashlib.sha256(written_bytes).hexdigest()

    def test_put_script_different_sources_produce_different_hashes(self, bucket):
        sha_a = put_script(bucket, "artifacts/run-1/a.py", "report.note('chk1', 'a')\n")
        sha_b = put_script(bucket, "artifacts/run-2/b.py", "report.note('chk1', 'b')\n")

        assert sha_a != sha_b


class TestGetScript:
    def test_get_script_returns_written_source_as_text(self, bucket):
        source = "report.note('chk1', 'revisado')\n"
        put_script(bucket, "artifacts/run-1/script.py", source)

        result = get_script(bucket, "artifacts/run-1/script.py")

        assert result == source


class TestBuildManifest:
    def test_build_manifest_assembles_all_required_fields(self):
        checks = [{"check_id": "chk-0001", "title": "Admin lockout"}]

        manifest = build_manifest(
            run_id="run-1",
            policy_key="policies/norma.pdf",
            policy_sha256="a" * 64,
            script_key="artifacts/run-1/script.py",
            script_sha256="b" * 64,
            checks=checks,
            attempts=1,
            model="claude-sonnet-4-6",
            generated_at="2026-09-10T12:00:00Z",
        )

        assert manifest["run_id"] == "run-1"
        assert manifest["checks"] == checks
        assert manifest["attempts"] == 1
        assert manifest["model"] == "claude-sonnet-4-6"
        assert manifest["generated_at"] == "2026-09-10T12:00:00Z"
        assert manifest["script_sha256"] == "b" * 64

    def _manifest(self, **extra) -> dict:
        return build_manifest(
            run_id="run-1",
            policy_key="policies/norma.pdf",
            policy_sha256="a" * 64,
            script_key="artifacts/run-1/script.py",
            script_sha256="b" * 64,
            checks=[],
            attempts=1,
            model="claude-sonnet-4-6",
            generated_at="2026-09-10T12:00:00Z",
            **extra,
        )

    def test_the_field_catalog_block_is_additive_and_optional(self):
        block = {
            "fortios_version": "v7.6.8",
            "unknown_field_references": 1,
            "references": [{"field": "zone", "endpoints": ["interfaces"], "line": 12}],
            "reduce_calls": 2,
        }

        without = self._manifest()
        with_block = self._manifest(field_catalog=block)

        assert "field_catalog" not in without
        assert with_block["field_catalog"] == block
        assert {k: v for k, v in with_block.items() if k != "field_catalog"} == without


class TestManifestRoundTrip:
    def test_put_then_get_manifest_preserves_all_fields(self, bucket):
        manifest = build_manifest(
            run_id="run-1",
            policy_key="policies/norma.pdf",
            policy_sha256="a" * 64,
            script_key="artifacts/run-1/script.py",
            script_sha256="b" * 64,
            checks=[{"check_id": "chk-0001", "title": "Admin lockout"}],
            attempts=2,
            model="claude-sonnet-4-6",
            generated_at="2026-09-10T12:00:00Z",
        )

        put_manifest(bucket, "artifacts/run-1/manifest.json", manifest)
        result = get_manifest(bucket, "artifacts/run-1/manifest.json")

        assert result == manifest

    def test_script_sha256_in_manifest_matches_actual_written_script_bytes(self, bucket):
        """Prueba de integridad end-to-end: el hash guardado en el manifest debe
        coincidir con sha256(bytes reales del script en S3) — esto es lo que
        permite al executor (Fase 8) verificar integridad antes de exec()."""
        source = "report.finding('chk-0001', 'fail', 'admins sin MFA')\n"
        script_sha256 = put_script(bucket, "artifacts/run-1/script.py", source)

        manifest = build_manifest(
            run_id="run-1",
            policy_key="policies/norma.pdf",
            policy_sha256="a" * 64,
            script_key="artifacts/run-1/script.py",
            script_sha256=script_sha256,
            checks=[{"check_id": "chk-0001", "title": "Admin MFA"}],
            attempts=1,
            model="claude-sonnet-4-6",
            generated_at="2026-09-10T12:00:00Z",
        )
        put_manifest(bucket, "artifacts/run-1/manifest.json", manifest)

        fetched_manifest = get_manifest(bucket, "artifacts/run-1/manifest.json")
        fetched_script_bytes = get_script(bucket, "artifacts/run-1/script.py").encode("utf-8")
        recomputed_sha256 = hashlib.sha256(fetched_script_bytes).hexdigest()

        assert fetched_manifest["script_sha256"] == recomputed_sha256
        assert fetched_manifest["script_sha256"] == script_sha256


class TestPutReport:
    def test_put_report_writes_markdown_with_correct_content_type(self, bucket):
        put_report(
            bucket,
            "reports/run-1/report.md",
            "# Reporte\n\nOK",
            content_type="text/markdown; charset=utf-8",
        )

        s3 = boto3.client("s3", region_name="us-east-1")
        obj = s3.get_object(Bucket=bucket, Key="reports/run-1/report.md")

        assert obj["Body"].read().decode("utf-8") == "# Reporte\n\nOK"
        assert obj["ContentType"] == "text/markdown; charset=utf-8"

    def test_put_report_writes_json_with_correct_content_type(self, bucket):
        payload = json.dumps({"status": "generation_failed"})
        put_report(
            bucket,
            "reports/run-1/report.json",
            payload,
            content_type="application/json; charset=utf-8",
        )

        s3 = boto3.client("s3", region_name="us-east-1")
        obj = s3.get_object(Bucket=bucket, Key="reports/run-1/report.json")

        assert json.loads(obj["Body"].read().decode("utf-8")) == {"status": "generation_failed"}
        assert obj["ContentType"] == "application/json; charset=utf-8"


class TestBuildManifestKnowledgeBase:
    BASE = {
        "run_id": "run-1",
        "policy_key": "policies/norma.pdf",
        "policy_sha256": "a" * 64,
        "script_key": "artifacts/run-1/script.py",
        "script_sha256": "b" * 64,
        "checks": [
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
        ],
        "attempts": 1,
        "model": "m",
        "generated_at": "2026-09-10T12:00:00Z",
    }

    def test_manifest_without_knowledge_base_is_byte_identical_to_the_previous_one(self):
        """Hash calculado sobre el commit e86bbc1, antes de agregar el bloque."""
        for manifest in (
            build_manifest(**self.BASE),
            build_manifest(**self.BASE, knowledge_base=None),
        ):
            encoded = json.dumps(manifest, ensure_ascii=False)
            assert hashlib.sha256(encoded.encode("utf-8")).hexdigest() == (
                "bc7c3c9f57231eb37475570136b4f80fbb35c91f4237b1925c83ed939d6623db"
            )
            assert "knowledge_base" not in manifest

    def test_knowledge_base_block_is_additive(self):
        block = {
            "enabled": True,
            "controls_with_references": 1,
            "retrievals_failed": 0,
            "references": {"chk-0001": [{"source": "fortinet/a.pdf", "score": 0.9}]},
        }

        manifest = build_manifest(**self.BASE, knowledge_base=block)

        assert manifest["knowledge_base"] == block
        without_block = {k: v for k, v in manifest.items() if k != "knowledge_base"}
        assert without_block == build_manifest(**self.BASE)
