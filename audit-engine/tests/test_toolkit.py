"""
Tests para toolkit.py — objetos de capacidad `fgt` y `report` inyectados
en el namespace del sandbox.

`fgt` envuelve un `FortiGateClient` real (mockeado acá, nunca se hace red);
`report` resuelve `clause_ref` del lado del servidor, desde el manifest —
el script generado nunca puede pasar/forjar su propio clause_ref.
"""

import pytest

from toolkit import FgtCapability, ReportCapability, UnknownEndpointError


class _FakeFortiGateClient:
    """Doble de FortiGateClient: cuenta llamadas, nunca hace red real.

    Implementa la superficie PÚBLICA `get(endpoint_key)` (task 6.3) — la
    misma que expone el `FortiGateClient` real — porque `FgtCapability`
    delega en ella en vez del método interno `_get(path)`.
    """

    def __init__(self, responses: dict[str, object]):
        self._responses = responses
        self.calls: list[str] = []

    def get(self, endpoint_key: str):
        self.calls.append(endpoint_key)
        return self._responses.get(endpoint_key)


REMEDIATION = {
    "summary": "Habilitar bloqueo de cuenta.",
    "steps": ["System > Settings"],
    "fortigate_cli": "config system global\n    set admin-lockout-threshold 3\nend",
}

VALID_MANIFEST = {
    "run_id": "run-1",
    "checks": [
        {
            "check_id": "chk1",
            "title": "Admin lockout",
            "clause_ref": {"page": 3, "quote": "..."},
            "remediation": REMEDIATION,
        },
        {"check_id": "chk2", "title": "DNS hardening", "clause_ref": {"page": 5, "quote": "..."}},
    ],
}


class TestFgtCapability:
    def test_get_resolves_endpoint_key_to_path_and_returns_data(self):
        client = _FakeFortiGateClient({"admins": [{"name": "admin"}]})
        fgt = FgtCapability(client)

        result = fgt.get("admins")

        assert result == [{"name": "admin"}]
        assert client.calls == ["admins"]

    def test_repeated_get_is_memoized_underlying_fetch_happens_once(self):
        client = _FakeFortiGateClient({"dns": {"primary": "8.8.8.8"}})
        fgt = FgtCapability(client)

        first = fgt.get("dns")
        second = fgt.get("dns")

        assert first == {"primary": "8.8.8.8"}
        assert second == {"primary": "8.8.8.8"}
        assert client.calls == ["dns"]  # only ONE real fetch

    def test_on_call_hook_fires_every_logical_call_even_when_memoized(self):
        # The sandbox's call-count budget must see every fgt.get() call, even
        # cache hits — otherwise a flood against one memoized endpoint would
        # never trip MAX_FGT_CALLS.
        call_count = {"n": 0}
        client = _FakeFortiGateClient({"dns": {}})

        def _bump():
            call_count["n"] += 1

        fgt = FgtCapability(client, on_call=_bump)

        fgt.get("dns")
        fgt.get("dns")
        fgt.get("dns")

        assert call_count["n"] == 3
        assert client.calls == ["dns"]

    def test_unknown_endpoint_fails_safely(self):
        client = _FakeFortiGateClient({})
        fgt = FgtCapability(client)

        with pytest.raises(UnknownEndpointError):
            fgt.get("not_a_real_endpoint")

        assert client.calls == []  # never attempted a fetch for garbage input

    def test_endpoints_lists_the_known_catalog(self):
        client = _FakeFortiGateClient({})
        fgt = FgtCapability(client)

        result = fgt.endpoints()

        assert "admins" in result
        assert "dns" in result
        assert "not_a_real_endpoint" not in result


class TestReportCapability:
    def test_finding_resolves_clause_ref_from_manifest_server_side(self):
        findings: list[dict] = []
        report = ReportCapability(VALID_MANIFEST, findings, notes=[])

        report.finding("chk1", "fail", "hay admins configurados")

        assert len(findings) == 1
        assert findings[0]["check_id"] == "chk1"
        assert findings[0]["clause_ref"] == {"page": 3, "quote": "..."}
        assert findings[0]["status"] == "fail"
        assert findings[0]["evidence"] == "hay admins configurados"
        assert findings[0]["traceable"] is True

    def test_finding_resolves_the_correct_clause_ref_per_check_id(self):
        findings: list[dict] = []
        report = ReportCapability(VALID_MANIFEST, findings, notes=[])

        report.finding("chk2", "pass", "dns ok")

        assert findings[0]["clause_ref"] == {"page": 5, "quote": "..."}

    def test_missing_check_id_is_flagged_untraceable_not_crashed(self):
        findings: list[dict] = []
        report = ReportCapability(VALID_MANIFEST, findings, notes=[])

        report.finding("does_not_exist", "indeterminate", "no se pudo evaluar")

        assert len(findings) == 1
        assert findings[0]["clause_ref"] is None
        assert findings[0]["traceable"] is False
        assert findings[0]["remediation"] is None

    def test_finding_resolves_remediation_from_manifest_server_side(self):
        """La remediacion propuesta viaja desde el manifest al finding por el
        toolkit -- el script no puede redactarla ni alterarla (misma regla
        que clause_ref) y nada la ejecuta."""
        findings: list[dict] = []
        report = ReportCapability(VALID_MANIFEST, findings, notes=[])

        report.finding("chk1", "fail", "sin bloqueo")
        report.finding("chk2", "pass", "dns ok")

        assert findings[0]["remediation"] == REMEDIATION
        # check sin propuesta en el manifest -> None, nunca KeyError
        assert findings[1]["remediation"] is None

    def test_finding_signature_does_not_accept_a_remediation_argument(self):
        findings: list[dict] = []
        report = ReportCapability(VALID_MANIFEST, findings, notes=[])

        with pytest.raises(TypeError):
            report.finding("chk1", "fail", "x", remediation={"summary": "forjada"})

        assert findings == []

    def test_note_appends_without_affecting_findings(self):
        findings: list[dict] = []
        notes: list[dict] = []
        report = ReportCapability(VALID_MANIFEST, findings, notes=notes)

        report.note("chk1", "revisado manualmente")

        assert findings == []
        assert notes == [{"check_id": "chk1", "message": "revisado manualmente"}]

    def test_on_call_hooks_fire_for_finding_and_note_independently(self):
        finding_calls = {"n": 0}
        note_calls = {"n": 0}
        report = ReportCapability(
            VALID_MANIFEST,
            findings=[],
            notes=[],
            on_finding=lambda: finding_calls.__setitem__("n", finding_calls["n"] + 1),
            on_note=lambda: note_calls.__setitem__("n", note_calls["n"] + 1),
        )

        report.finding("chk1", "pass", "ok")
        report.note("chk1", "fyi")

        assert finding_calls["n"] == 1
        assert note_calls["n"] == 1


# ---------------------------------------------------------------------------
# Documentos de referencia: resueltos desde el manifest, igual que clause_ref
# ---------------------------------------------------------------------------

REFERENCES_MANIFEST = {
    **VALID_MANIFEST,
    "knowledge_base": {
        "enabled": True,
        "controls_with_references": 1,
        "retrievals_failed": 0,
        "references": {
            "chk1": [
                {"source": "fortinet/hardening.pdf", "score": 0.91},
                {"source": None, "score": None},
            ]
        },
    },
}


class TestReportCapabilityReferences:
    def test_old_manifest_without_the_block_produces_the_previous_finding_shape(self):
        findings: list[dict] = []
        report = ReportCapability(VALID_MANIFEST, findings, notes=[])

        report.finding("chk1", "fail", "sin bloqueo")

        assert list(findings[0]) == [
            "check_id",
            "clause_ref",
            "status",
            "evidence",
            "endpoints_used",
            "traceable",
            "remediation",
        ]

    def test_references_are_resolved_from_the_manifest_per_check_id(self):
        findings: list[dict] = []
        report = ReportCapability(REFERENCES_MANIFEST, findings, notes=[])

        report.finding("chk1", "fail", "sin bloqueo")
        report.finding("chk2", "pass", "dns ok")
        report.finding("does_not_exist", "indeterminate", "x")

        assert findings[0]["references"] == [
            {"source": "fortinet/hardening.pdf", "score": 0.91},
            {"source": None, "score": None},
        ]
        # Recuperación habilitada pero sin documentos para ese control.
        assert findings[1]["references"] == []
        assert findings[2]["references"] == []

    def test_finding_signature_does_not_accept_a_references_argument(self):
        findings: list[dict] = []
        report = ReportCapability(REFERENCES_MANIFEST, findings, notes=[])

        with pytest.raises(TypeError):
            report.finding("chk1", "fail", "x", references=[{"source": "forjada", "score": 1.0}])

        assert findings == []

    def test_mutating_a_finding_does_not_alter_later_findings(self):
        findings: list[dict] = []
        report = ReportCapability(REFERENCES_MANIFEST, findings, notes=[])

        report.finding("chk1", "fail", "x")
        findings[0]["references"][0]["source"] = "alterada"
        findings[0]["references"].append({"source": "forjada", "score": 1.0})
        report.finding("chk1", "fail", "x")

        assert findings[1]["references"][0]["source"] == "fortinet/hardening.pdf"
        assert len(findings[1]["references"]) == 2

    @pytest.mark.parametrize(
        "block",
        [
            None,
            "texto",
            {"enabled": False, "references": {"chk1": [{"source": "s3://x", "score": 1}]}},
            {"references": {"chk1": [{"source": "s3://x", "score": 1}]}},
        ],
    )
    def test_absent_disabled_or_malformed_block_adds_no_references_key(self, block):
        findings: list[dict] = []
        manifest = {**VALID_MANIFEST, "knowledge_base": block}
        report = ReportCapability(manifest, findings, notes=[])

        report.finding("chk1", "fail", "x")

        assert "references" not in findings[0]

    def test_malformed_reference_entries_are_dropped_or_neutralized(self):
        findings: list[dict] = []
        manifest = {
            **VALID_MANIFEST,
            "knowledge_base": {
                "enabled": True,
                "references": {
                    "chk1": [
                        "no-es-un-objeto",
                        {"source": 123, "score": "alto", "text": "no debe viajar"},
                        {"source": "  fortinet/a.pdf\n| inyectado  ", "score": True},
                        {"source": "s" * 2000, "score": 0.5},
                    ],
                    "chk2": "no-es-una-lista",
                },
            },
        }
        report = ReportCapability(manifest, findings, notes=[])

        report.finding("chk1", "fail", "x")
        report.finding("chk2", "pass", "x")

        assert findings[0]["references"] == [
            {"source": None, "score": None},
            {"source": "fortinet/a.pdf | inyectado", "score": None},
            {"source": "s" * 300, "score": 0.5},
        ]
        assert findings[1]["references"] == []
