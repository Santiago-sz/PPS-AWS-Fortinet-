import json

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from moto import mock_aws
from pps_api.aws_bridge import Bridge
from pps_api.service import Error
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


class FakeLambda:
    def __init__(self):
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"StatusCode": 202}


def put_json(bridge, key, value):
    bridge.s3.put_object(Bucket=bridge.reports_bucket, Key=key, Body=json.dumps(value).encode())


def test_list_pending_and_approve_invoke_executor_once(bridge, document):
    manifest, report = pair(document, run_id="pending1")
    manifest["script_key"] = "artifacts/pending1/script.py"
    manifest["script_sha256"] = "ab" * 32
    put_json(bridge, "artifacts/pending1/manifest.json", manifest)
    done_manifest, done_report = pair(document, run_id="done2")
    done_manifest.update(script_key="artifacts/done2/script.py", script_sha256="cd" * 32)
    put_json(bridge, "artifacts/done2/manifest.json", done_manifest)
    put_json(bridge, "reports/done2/report.json", done_report)
    assert bridge.list_pending() == ["pending1"]
    executor = FakeLambda()
    assert bridge.approve("pending1", "pps-executor", executor) == 202
    assert executor.calls == [
        {
            "FunctionName": "pps-executor",
            "InvocationType": "Event",
            "Payload": json.dumps(
                {
                    "run_id": "pending1",
                    "manifest_key": "artifacts/pending1/manifest.json",
                    "script_key": "artifacts/pending1/script.py",
                    "script_sha256": "ab" * 32,
                }
            ).encode(),
        }
    ]
    with pytest.raises(Error) as reported:
        bridge.approve("done2", "pps-executor", executor)
    assert reported.value.code == "run_already_reported"
    with pytest.raises(Error) as missing:
        bridge.approve("absent3", "pps-executor", executor)
    assert missing.value.status == 404
    with pytest.raises(Error, match="invalid pipeline run id"):
        bridge.approve("../etc", "pps-executor", executor)
    assert len(executor.calls) == 1


def test_approve_rejects_manifest_without_signed_script(bridge, document):
    manifest, _ = pair(document, run_id="unsigned")
    manifest["script_sha256"] = "not-a-hash"
    put_json(bridge, "artifacts/unsigned/manifest.json", manifest)
    executor = FakeLambda()
    with pytest.raises(Error) as error:
        bridge.approve("unsigned", "pps-executor", executor)
    assert error.value.status == 422
    manifest["script_sha256"] = "cd" * 32
    manifest["script_key"] = "artifacts/other/script.py"
    put_json(bridge, "artifacts/unsigned/manifest.json", manifest)
    with pytest.raises(Error, match="manifest without script key"):
        bridge.approve("unsigned", "pps-executor", executor)
    assert executor.calls == []


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
