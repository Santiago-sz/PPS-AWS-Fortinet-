import json

import pytest

from pps_desktop.domain import normalize, inspect_policy, load_pair, redact


def pair(status="completed"):
    manifest = {"run_id": "r", "checks": [{"check_id": str(i)} for i in range(1, 7)]}
    report = {
        "run_id": "r",
        "status": status,
        "findings": [
            {"check_id": "1", "status": "pass"},
            {"check_id": "2", "status": "pass"},
            {"check_id": "3", "status": "fail"},
            {"check_id": "4", "status": "indeterminate"},
            {"check_id": "5", "status": "not_applicable"},
        ],
    }
    return manifest, report


def test_expected_universe_and_exclusions():
    result = normalize(*pair())
    assert result["counts"]["expected"] == 6
    assert result["counts"]["not_evaluated"] == 1
    assert result["counts"]["evaluated"] == 5
    assert result["coverage_percent"] == pytest.approx(5 / 6 * 100)
    assert result["compliance_percent"] == pytest.approx(2 / 3 * 100)
    assert result["partial"]  # Even a completed run may have missing results.


@pytest.mark.parametrize(
    "status", ["truncated", "could_not_audit", "generation_failed", "no_verifiable_controls"]
)
def test_failure_never_becomes_total_posture(status):
    manifest, report = pair(status)
    report["findings"] = [{"check_id": str(i), "status": "pass"} for i in range(1, 7)]
    assert normalize(manifest, report)["partial"]


def test_full_success_and_empty_universe():
    manifest, report = pair()
    report["findings"].append({"check_id": "6", "status": "pass"})
    assert normalize(manifest, report)["partial"] is False
    result = normalize({"run_id": "r", "checks": []}, {"run_id": "r", "status": "completed"})
    assert result["compliance_percent"] is None
    assert result["coverage_percent"] is None


def test_duplicates_and_unknown_checks_retained_without_inflating_counts():
    manifest, report = pair()
    report["findings"].extend(
        [{"check_id": "1", "status": "fail"}, {"check_id": "unknown", "status": "pass"}]
    )
    result = normalize(manifest, report)
    assert result["counts"]["anomaly"] == 1
    assert result["counts"]["evaluated"] == 4
    assert result["counts"]["pass"] == 1
    assert len(result["rows"][0]["observations"]) == 2
    assert result["unknown_findings"][0]["check_id"] == "unknown"


def test_duplicate_manifest_is_anomaly():
    manifest, report = pair()
    manifest["checks"].append({"check_id": "1"})
    result = normalize(manifest, report)
    assert result["counts"]["expected"] == 6
    assert result["counts"]["anomaly"] == 1


def test_no_fabricated_citations_or_mutation():
    manifest, report = pair()
    manifest["checks"][0]["clause_ref"] = {"quote": "Manifest quote"}
    report["findings"][0].update({"traceable": False, "clause_ref": {"quote": "Finding quote"}})
    before = json.dumps(report)
    result = normalize(manifest, report)
    assert result["rows"][0]["traceable"] is False
    assert result["rows"][0]["clause_ref"] is None
    assert json.dumps(report) == before


def test_mismatched_import_rejected(tmp_path):
    manifest, report = pair()
    report["run_id"] = "another"
    paths = [tmp_path / "manifest.json", tmp_path / "report.json"]
    for path, content in zip(paths, (manifest, report)):
        path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="run_id"):
        load_pair(*paths)


@pytest.mark.parametrize(
    "name,data",
    [("bad.pdf", b"not PDF"), ("bad.docx", b"not ZIP"), ("bad.exe", b"MZ"), ("empty.pdf", b"")],
)
def test_invalid_policy_rejected(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    with pytest.raises(ValueError):
        inspect_policy(path, 100)


def test_policy_hash_and_size(tmp_path):
    import hashlib

    path = tmp_path / "policy.pdf"
    path.write_bytes(b"%PDF-1.7\nexample")
    doc = inspect_policy(path, 100)
    assert doc["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert doc["size"] == path.stat().st_size
    with pytest.raises(ValueError, match="MB"):
        inspect_policy(path, 4)


def test_redaction():
    assert redact({"api_key": "secret", "nested": {"password": "hello"}}) == {
        "api_key": "[OCULTO]",
        "nested": {"password": "[OCULTO]"},
    }
    assert "abc" not in redact("token=abc Bearer abc")
