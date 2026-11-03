import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import pytest
from pps_api.server import create_server
from pps_api.service import MIMES, Error, Service
from pps_desktop.api import ApiClient, ApiError
from pps_desktop.domain import normalize


def metadata(document):
    return {
        "name": "Política de prueba",
        "version_label": "1",
        "scope": "Laboratorio",
        "description": "",
        "device_id": "fgt_local",
        "extension": "docx",
        "mime_type": MIMES["docx"],
        "size": len(document),
        "sha256": hashlib.sha256(document).hexdigest(),
    }


@pytest.fixture
def connected(service):
    server = create_server(service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = ApiClient(f"http://127.0.0.1:{server.server_port}", "", development=True)
    yield service, client
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def upload(service, document, key="upload-key"):
    meta = metadata(document)
    created = service.create_policy(meta, key)
    token = parse_qs(urlsplit(created["upload"]["url"]).query)["token"][0]
    service.put_upload(created["upload_id"], token, document, meta["mime_type"])
    payload = {"upload_id": created["upload_id"], "sha256": meta["sha256"], "size": meta["size"]}
    service.complete(created["policy_id"], created["version_id"], payload, key)
    return created, payload


def pair(document, run_id="run123", policy_key="policies/local.docx"):
    manifest = {
        "run_id": run_id,
        "policy_key": policy_key,
        "policy_sha256": hashlib.sha256(document).hexdigest(),
        "script_key": "private/script.py",
        "script_sha256": "private",
        "checks": [{"check_id": "C1", "title": "Control"}],
    }
    report = {
        "run_id": run_id,
        "policy_key": policy_key,
        "status": "completed",
        "timestamp": "2026-10-20T12:00:00Z",
        "truncated": False,
        "notes": [],
        "findings": [{"check_id": "C1", "status": "pass", "evidence": "correcto"}],
    }
    return manifest, report


def test_desktop_http_roundtrip_persistence_and_reaudit(connected, document):
    service, client = connected
    assert client.snapshot()["session"]["development"] is True
    created = client.upload(metadata(document), document, "desktop-key")
    aid = created["audit_id"]
    assert service.audit(aid)["events"][0]["phase"] == "recibido"
    assert service.audit(aid)["run_id"] is None
    assert len(client.snapshot()["policies"]) == 1
    detail = client.call("/api/policies/" + created["policy_id"])
    assert "bloqueo" in detail["preview_text"]
    path = f"/api/policies/{created['policy_id']}/versions/{created['version_id']}/document"
    assert client.call(path, raw=True) == document
    with pytest.raises(ApiError) as pending:
        client.results(aid)
    assert pending.value.code == "409"
    manifest, report = pair(document)
    report["findings"][0]["token"] = "do-not-expose"
    report["findings"][0]["evidence"] = "token=do-not-expose"
    service.finish(aid, manifest, report)
    result = client.results(aid)
    assert "script_key" not in result["manifest"]
    assert "do-not-expose" not in json.dumps(result)
    assert normalize(result["manifest"], result["report"])["counts"]["pass"] == 1
    assert b"completed" in client.call(f"/api/audits/{aid}/export?format=json", raw=True)
    assert b"C1" in client.call(f"/api/audits/{aid}/export?format=md", raw=True)
    reopened = Service(service.database)
    assert reopened.audit(aid)["status"] == "completed"
    assert reopened.audit(aid, results=True) == result
    new = client.call(
        "/api/audits",
        "POST",
        {"policy_version_id": created["version_id"], "device_id": "fgt_local"},
        "new-audit",
    )
    assert new["audit_id"] != aid
    assert service.audit(aid)["status"] == "completed"
    assert service.audit(new["audit_id"])["status"] == "pending"


def test_idempotent_create_complete_and_concurrent_retries(service, document):
    meta = metadata(document)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: service.create_policy(meta, "same"), range(8)))
    assert all(r == responses[0] for r in responses)
    assert len(service.collection("audits")["items"]) == 1
    with pytest.raises(Error) as conflict:
        service.create_policy({**meta, "name": "Changed"}, "same")
    assert conflict.value.status == 409
    created, payload = upload(service, document, "same")
    for key in ("same", "retry-other-key"):
        service.complete(created["policy_id"], created["version_id"], payload, key)
    assert len(service.audit(created["audit_id"])["events"]) == 1
    service.reaudit({"policy_version_id": created["version_id"], "device_id": "fgt_local"}, "again")
    completion = service.complete(
        created["policy_id"], created["version_id"], payload, "late-complete"
    )
    assert completion["audit_id"] == created["audit_id"]


def test_upload_integrity_expiration_and_immutability(service, document):
    meta = metadata(document)
    created = service.create_policy(meta, "one")
    token = parse_qs(urlsplit(created["upload"]["url"]).query)["token"][0]
    with pytest.raises(Error, match="invalid upload token"):
        service.put_upload(created["upload_id"], "wrong", document, meta["mime_type"])
    with pytest.raises(Error, match="checksum mismatch"):
        service.put_upload(created["upload_id"], token, document + b"x", meta["mime_type"])
    created, _ = upload(service, document, "one")
    with pytest.raises(Error, match="upload already confirmed"):
        service.put_upload(created["upload_id"], token, document, meta["mime_type"])
    other = service.create_policy(meta, "two")
    token = parse_qs(urlsplit(other["upload"]["url"]).query)["token"][0]
    service.clock = lambda: 10**12
    with pytest.raises(Error, match="upload expired"):
        service.put_upload(other["upload_id"], token, document, meta["mime_type"])


def test_corrupt_document_never_becomes_dispatchable(service):
    with pytest.raises(Error) as invalid:
        upload(service, b"not a docx")
    assert invalid.value.status == 422
    with service.db() as db:
        assert db.execute("SELECT dispatch FROM audits").fetchone()[0] == "waiting"


def test_complete_without_put_and_other_version(service, document):
    meta = metadata(document)
    created = service.create_policy(meta, "one")
    body = {"upload_id": created["upload_id"], "sha256": meta["sha256"], "size": meta["size"]}
    with pytest.raises(Error, match="upload missing"):
        service.complete(created["policy_id"], created["version_id"], body, "one")
    with pytest.raises(Error) as absent:
        service.complete(created["policy_id"], "other", body, "one")
    assert absent.value.status == 404


def test_results_correlation_and_immutable_reports(service, document):
    created, _ = upload(service, document)
    manifest, report = pair(document)
    with pytest.raises(Error, match="run mismatch"):
        service.finish(created["audit_id"], {**manifest, "run_id": "wrong"}, report)
    with pytest.raises(Error, match="policy hash mismatch"):
        service.finish(created["audit_id"], {**manifest, "policy_sha256": "wrong"}, report)
    service.finish(created["audit_id"], manifest, report)
    service.finish(created["audit_id"], manifest, report)
    with pytest.raises(Error, match="immutable result"):
        service.finish(created["audit_id"], manifest, {**report, "status": "truncated"})


def test_pagination_has_no_duplicates(service, document):
    for index in range(52):
        service.create_policy(metadata(document), str(index))
    first = service.collection("policies")
    second = service.collection("policies", first["next_cursor"])
    assert len(first["items"]) == 50 and len(second["items"]) == 2
    assert second["next_cursor"] is None
    assert len({p["id"] for p in first["items"] + second["items"]}) == 52
    with pytest.raises(Error):
        service.collection("policies", "bad cursor")


@pytest.mark.parametrize(
    "headers", [{"Origin": "https://untrusted.example"}, {"Host": "untrusted.example"}]
)
def test_http_rejects_browser_and_rebinding(connected, headers):
    _, client = connected
    with pytest.raises(HTTPError) as error:
        urlopen(Request(client.base_url + "/api/session", headers=headers), timeout=5)
    assert error.value.code == 403
    body = json.loads(error.value.read())
    assert body["correlation_id"] == error.value.headers["X-Correlation-ID"]


@pytest.mark.parametrize(
    "field,value",
    [("size", True), ("size", -1), ("device_id", "other"), ("extension", []), ("sha256", "wrong")],
)
def test_invalid_metadata_returns_client_error(connected, document, field, value):
    _, client = connected
    with pytest.raises(ApiError) as error:
        client.call("/api/policies", "POST", {**metadata(document), field: value}, "invalid")
    assert error.value.code in {"400", "404", "413"}
