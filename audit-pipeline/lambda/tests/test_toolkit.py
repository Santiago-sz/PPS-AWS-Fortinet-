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


VALID_MANIFEST = {
    "run_id": "run-1",
    "checks": [
        {"check_id": "chk1", "title": "Admin lockout", "clause_ref": {"page": 3, "quote": "..."}},
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
