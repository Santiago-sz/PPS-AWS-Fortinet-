import json

import pytest

from pps_desktop.domain import (
    RUN_STATUSES,
    normalize,
    normalize_remediation,
    inspect_policy,
    load_pair,
    newest_first,
    redact,
)


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


def test_remediation_normalized_redacted_and_counted():
    manifest, report = pair()
    proposal = {
        "summary": "Cerrar el acceso. token=abc123",
        "steps": ["Configurar trusthost.", "password=hunter2 en el paso"],
        "fortigate_cli": "config system admin\nend",
    }
    manifest["checks"][2]["remediation"] = proposal  # fail, remediation from the check
    manifest["checks"][3]["remediation"] = {"summary": None, "steps": [], "fortigate_cli": None}
    report["findings"][3]["remediation"] = {"summary": "Revisar manualmente.", "steps": []}
    report["findings"][0]["remediation"] = proposal  # pass: retained but not counted
    result = normalize(manifest, report)
    rows = {r["check_id"]: r for r in result["rows"]}
    failed = rows["3"]["remediation"]
    assert failed["fortigate_cli"] == "config system admin\nend"
    assert "abc123" not in failed["summary"] and "hunter2" not in failed["steps"][1]
    assert failed["steps"][0] == "Configurar trusthost."
    assert rows["4"]["remediation"] == {
        "summary": "Revisar manualmente.",
        "steps": [],
        "fortigate_cli": None,
    }
    assert rows["2"]["remediation"] is None and rows["6"]["remediation"] is None
    assert rows["1"]["remediation"] is not None
    assert result["remediation_count"] == 2
    assert normalize_remediation({"summary": "", "steps": [], "fortigate_cli": None}) is None
    assert normalize_remediation("texto") is None


def test_finding_degraded_by_missing_data_shows_reason_and_no_proposal():
    manifest, report = pair()
    proposal = {"summary": "Restringir administradores.", "steps": [], "fortigate_cli": None}
    manifest["checks"][3]["remediation"] = proposal
    manifest["checks"][2]["remediation"] = proposal
    reason = "Datos no disponibles: el endpoint `admins` devolvió una respuesta vacía."
    report["findings"][3].update(
        {
            "evidence": "total_admins=0",
            "remediation": None,
            "reported_status": "pass",
            "data_gaps": [{"endpoint": "admins", "kind": "empty_not_possible"}],
            "status_reason": reason,
        }
    )
    result = normalize(manifest, report)
    rows = {r["check_id"]: r for r in result["rows"]}
    degraded = rows["4"]
    assert degraded["status"] == "indeterminate"
    assert degraded["status_reason"] == reason
    assert degraded["reported_status"] == "pass"
    # El resultado informado no cuenta como aprobado.
    assert result["counts"]["pass"] == 2 and result["counts"]["indeterminate"] == 1
    # Sin evidencia no se presenta la propuesta del manifest.
    assert degraded["remediation"] is None
    assert rows["3"]["remediation"] is not None
    assert result["remediation_count"] == 1
    # Un hallazgo sin lagunas no gana texto.
    assert rows["1"]["status_reason"] is None and rows["1"]["reported_status"] is None


def test_awaiting_approval_has_label_and_is_not_terminal():
    from pps_desktop.domain import TERMINAL

    assert RUN_STATUSES["awaiting_approval"] == "Pendiente de aprobación"
    assert "awaiting_approval" not in TERMINAL


def test_redaction():
    assert redact({"api_key": "secret", "nested": {"password": "hello"}}) == {
        "api_key": "[OCULTO]",
        "nested": {"password": "[OCULTO]"},
    }
    assert "abc" not in redact("token=abc Bearer abc")


def test_newest_first_orders_by_date_and_keeps_undated_items_last():
    items = [
        {"id": "old", "started_at": "2026-11-22T00:18:01Z"},
        {"id": "undated"},
        {"id": "new", "started_at": "2026-11-25T00:30:11Z"},
        {"id": "invalid", "started_at": "not-a-date"},
        {"id": "middle", "started_at": "2026-11-23T02:07:33+00:00"},
    ]
    ordered = newest_first(items, "started_at")
    assert [item["id"] for item in ordered] == ["new", "middle", "old", "undated", "invalid"]
    assert [item["id"] for item in items][0] == "old"  # the input list is not modified


def test_newest_first_puts_the_later_item_first_when_dates_tie():
    items = [
        {"id": "first", "started_at": "2026-11-23T03:05:57Z"},
        {"id": "second", "started_at": "2026-11-23T03:05:57Z"},
    ]
    assert [item["id"] for item in newest_first(items, "started_at")] == ["second", "first"]
