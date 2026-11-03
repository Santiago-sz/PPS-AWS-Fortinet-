import json

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from moto import mock_aws
from pps_api.aws_bridge import Bridge
from test_api import metadata, pair, upload


@pytest.fixture
def bridge(service):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        for bucket in ("pps-test-policies", "pps-test-reports"):
            s3.create_bucket(Bucket=bucket)
        yield Bridge(service, s3, "pps-test-policies", "pps-test-reports")


def test_dispatch_only_confirmed_and_sync_real_artifacts(bridge, document):
    service = bridge.service
    service.create_policy(metadata(document), "unconfirmed")
    assert bridge.dispatch() == 0
    created, _ = upload(service, document)
    assert bridge.dispatch() == 1
    assert bridge.dispatch() == 0
    key = f"policies/{created['audit_id']}.docx"
    assert bridge.s3.get_object(Bucket=bridge.policies_bucket, Key=key)["Body"].read() == document
    manifest, report = pair(document, policy_key=key)
    for path, value in (
        ("artifacts/run123/manifest.json", manifest),
        ("reports/run123/report.json", report),
    ):
        bridge.s3.put_object(
            Bucket=bridge.reports_bucket, Key=path, Body=json.dumps(value).encode()
        )
    assert bridge.sync() == 1
    assert bridge.sync() == 0
    assert service.audit(created["audit_id"])["run_id"] == "run123"
    assert [e["phase"] for e in service.audit(created["audit_id"])["events"]] == [
        "recibido",
        "recibido",
        "finalizado",
    ]


def test_generation_failure_without_manifest(bridge, document):
    created, _ = upload(bridge.service, document)
    bridge.dispatch()
    _, report = pair(document, policy_key=f"policies/{created['audit_id']}.docx")
    report.update(status="could_not_audit", findings=[], failure_reason="generation_failed")
    bridge.s3.put_object(
        Bucket=bridge.reports_bucket,
        Key="reports/run123/report.json",
        Body=json.dumps(report).encode(),
    )
    assert bridge.sync() == 1
    result = bridge.service.audit(created["audit_id"], results=True)
    assert result["manifest"]["checks"] == []
    assert result["report"]["status"] == "could_not_audit"


def test_ambiguous_put_not_retried(bridge, document, monkeypatch):
    upload(bridge.service, document)
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise EndpointConnectionError(endpoint_url="https://example.invalid")

    monkeypatch.setattr(bridge.s3, "put_object", fail)
    with pytest.raises(EndpointConnectionError):
        bridge.dispatch()
    assert bridge.dispatch() == 0
    assert len(calls) == 1


def test_duplicate_pipeline_runs_require_reconciliation(bridge, document):
    created, _ = upload(bridge.service, document)
    bridge.dispatch()
    for run_id in ("one", "two"):
        _, report = pair(document, run_id=run_id, policy_key=f"policies/{created['audit_id']}.docx")
        bridge.s3.put_object(
            Bucket=bridge.reports_bucket,
            Key=f"reports/{run_id}/report.json",
            Body=json.dumps(report).encode(),
        )
    assert bridge.sync() == 0
    audit = bridge.service.audit(created["audit_id"])
    assert audit["run_id"] is None
    assert "múltiples" in audit["events"][-1]["message"]
