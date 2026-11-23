"""
Tests para toolkit.py — objetos de capacidad `fgt` y `report` inyectados
en el namespace del sandbox.

`fgt` envuelve un `FortiGateClient` real (mockeado acá, nunca se hace red);
`report` resuelve `clause_ref` del lado del servidor, desde el manifest —
el script generado nunca puede pasar/forjar su propio clause_ref.
"""

import pytest

import fortigate_client
from toolkit import (
    NEVER_EMPTY_ENDPOINTS,
    FgtCapability,
    ReadLedger,
    ReportCapability,
    UnknownEndpointError,
)


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


# ---------------------------------------------------------------------------
# Datos ausentes, ilegibles o imposiblemente vacíos (decisión 12)
# ---------------------------------------------------------------------------

GAPS_MANIFEST = {
    "run_id": "run-gaps",
    "checks": [
        {
            "check_id": "chk-admins",
            "clause_ref": {"page": 1, "quote": "..."},
            "endpoints": ["admins", "api_users"],
            "remediation": REMEDIATION,
        },
        {
            "check_id": "chk-vpn",
            "clause_ref": {"page": 2, "quote": "..."},
            "endpoints": ["vpn_ipsec"],
        },
        {
            "check_id": "chk-dhcp",
            "clause_ref": {"page": 3, "quote": "..."},
            "endpoints": ["dhcp_servers"],
        },
        {
            "check_id": "chk-log",
            "clause_ref": {"page": 4, "quote": "..."},
            "endpoints": ["log_settings"],
        },
        {
            "check_id": "chk-policies",
            "clause_ref": {"page": 5, "quote": "..."},
            "endpoints": ["firewall_policies"],
        },
        {"check_id": "chk-undeclared", "clause_ref": {"page": 6, "quote": "..."}},
    ],
}

LEGACY_FINDING_KEYS = [
    "check_id",
    "clause_ref",
    "status",
    "evidence",
    "endpoints_used",
    "traceable",
    "remediation",
]


def _wired(responses: dict[str, object]):
    """`fgt` y `report` compartiendo un registro, como los cablea el sandbox."""
    ledger = ReadLedger()
    findings: list[dict] = []
    fgt = FgtCapability(_FakeFortiGateClient(responses), ledger=ledger)
    report = ReportCapability(GAPS_MANIFEST, findings, notes=[], ledger=ledger)
    return fgt, report, findings


class TestNeverEmptyEndpoints:
    def test_the_set_names_tables_a_device_in_service_always_has(self):
        assert {"admins", "api_users"} <= NEVER_EMPTY_ENDPOINTS
        assert "vpn_ipsec" not in NEVER_EMPTY_ENDPOINTS
        assert "radius_servers" not in NEVER_EMPTY_ENDPOINTS
        known = {label for _, label in fortigate_client.ENDPOINTS}
        assert known >= NEVER_EMPTY_ENDPOINTS

    def test_catalog_tuples_keep_their_two_element_shape(self):
        # `collect_all` del flujo legacy las desempaqueta de a dos.
        assert all(len(entry) == 2 for entry in fortigate_client.ENDPOINTS)

    def test_empty_admins_turns_a_pass_into_indeterminate(self):
        # Forma observada en el laboratorio: HTTP 200 con lista vacía.
        fgt, report, findings = _wired({"admins": [], "api_users": []})

        admins = fgt.get("admins")
        report.finding("chk-admins", "pass", f"total_admins={len(admins)}", ["admins"])

        finding = findings[0]
        assert finding["status"] == "indeterminate"
        assert finding["reported_status"] == "pass"
        assert finding["data_gaps"] == [{"endpoint": "admins", "kind": "empty_not_possible"}]
        assert "admins" in finding["status_reason"]
        # La evidencia que escribió el script no se altera.
        assert finding["evidence"] == "total_admins=0"

    def test_degradation_does_not_need_the_script_to_declare_endpoints(self):
        fgt, report, findings = _wired({"admins": [], "api_users": []})

        fgt.get("api_users")
        report.finding("chk-admins", "pass", "api_users=0")

        assert findings[0]["status"] == "indeterminate"
        assert findings[0]["data_gaps"] == [{"endpoint": "api_users", "kind": "empty_not_possible"}]

    def test_legitimately_empty_table_keeps_the_reported_status_and_shape(self):
        fgt, report, findings = _wired({"vpn_ipsec": [], "radius_servers": []})

        tunnels = fgt.get("vpn_ipsec")
        report.finding("chk-vpn", "pass", f"tunnels={len(tunnels)}", ["vpn_ipsec"])

        assert tunnels == []
        assert findings[0]["status"] == "pass"
        assert list(findings[0]) == LEGACY_FINDING_KEYS

    def test_a_gap_in_another_endpoint_does_not_affect_an_unrelated_check(self):
        fgt, report, findings = _wired({"admins": [], "vpn_ipsec": []})

        fgt.get("admins")
        fgt.get("vpn_ipsec")
        report.finding("chk-vpn", "pass", "tunnels=0")

        assert findings[0]["status"] == "pass"


class TestUnreadableEndpoint:
    def test_unreadable_endpoint_is_usable_as_an_empty_collection(self):
        # HTTP 400/401/403 o fallo de red: el cliente devuelve None.
        fgt, _, _ = _wired({})

        data = fgt.get("dhcp_servers")

        assert data is not None
        assert len(data) == 0
        assert [item for item in data] == []
        assert ("status" in data) is False

    def test_unreadable_endpoint_turns_the_finding_into_indeterminate(self):
        fgt, report, findings = _wired({})

        servers = fgt.get("dhcp_servers")
        report.finding("chk-dhcp", "pass", f"dhcp_servers={len(servers)}", ["dhcp_servers"])

        assert findings[0]["status"] == "indeterminate"
        assert findings[0]["reported_status"] == "pass"
        assert findings[0]["data_gaps"] == [{"endpoint": "dhcp_servers", "kind": "unreadable"}]
        assert "dhcp_servers" in findings[0]["status_reason"]

    def test_unreadable_endpoint_is_fetched_once_and_recorded_once(self):
        ledger = ReadLedger()
        client = _FakeFortiGateClient({})
        fgt = FgtCapability(client, ledger=ledger)

        fgt.get("dhcp_servers")
        fgt.get("dhcp_servers")

        assert client.calls == ["dhcp_servers"]
        assert ledger.gaps == [{"endpoint": "dhcp_servers", "kind": "unreadable"}]


class TestStatusRules:
    @pytest.mark.parametrize("reported", ["pass", "fail", "not_applicable"])
    def test_every_conclusive_status_is_degraded_and_preserved(self, reported):
        fgt, report, findings = _wired({"admins": []})

        fgt.get("admins")
        report.finding("chk-admins", reported, "x", ["admins"])

        assert findings[0]["status"] == "indeterminate"
        assert findings[0]["reported_status"] == reported

    def test_script_reported_indeterminate_keeps_status_and_gains_the_gaps(self):
        fgt, report, findings = _wired({"admins": []})

        fgt.get("admins")
        report.finding("chk-admins", "indeterminate", "x", ["admins"])

        assert findings[0]["status"] == "indeterminate"
        assert "reported_status" not in findings[0]
        assert findings[0]["data_gaps"] == [{"endpoint": "admins", "kind": "empty_not_possible"}]

    def test_degraded_finding_carries_no_remediation(self):
        # Una propuesta sin evidencia que la respalde no se presenta.
        fgt, report, findings = _wired({"admins": []})

        fgt.get("admins")
        report.finding("chk-admins", "fail", "x", ["admins"])

        assert findings[0]["remediation"] is None

    @pytest.mark.parametrize("status", ["PASS", "ok", "", None, 1, ["pass"]])
    def test_status_outside_the_four_allowed_becomes_indeterminate(self, status):
        findings: list[dict] = []
        report = ReportCapability(VALID_MANIFEST, findings, notes=[])

        report.finding("chk1", status, "x")

        assert findings[0]["status"] == "indeterminate"
        assert "reported_status" in findings[0]
        assert findings[0]["status_reason"]

    def test_check_whose_declared_endpoints_were_never_read_is_indeterminate(self):
        fgt, report, findings = _wired({"vpn_ipsec": []})

        report.finding("chk-vpn", "pass", "sin leer nada", ["vpn_ipsec"])

        assert findings[0]["status"] == "indeterminate"
        assert findings[0]["data_gaps"] == [{"endpoint": "vpn_ipsec", "kind": "not_read"}]

    def test_check_without_declared_endpoints_inherits_every_gap_of_the_run(self):
        # Sin declaración no se puede acotar de qué dato depende el control.
        fgt, report, findings = _wired({"admins": []})

        fgt.get("admins")
        report.finding("chk-undeclared", "pass", "x")

        assert findings[0]["status"] == "indeterminate"

    def test_check_without_declared_endpoints_and_without_gaps_is_untouched(self):
        fgt, report, findings = _wired({"dns": {"primary": "192.0.2.1"}})

        fgt.get("dns")
        report.finding("chk-undeclared", "pass", "x")

        assert findings[0]["status"] == "pass"
        assert list(findings[0]) == LEGACY_FINDING_KEYS


class TestTrackedContainers:
    def test_returned_data_still_behaves_like_plain_dicts_and_lists(self):
        raw = [
            {"name": "p1", "status": "enable", "srcintf": [{"name": "port1"}]},
            {"name": "p2", "status": "disable", "srcintf": [{"name": "port2"}]},
        ]
        fgt, _, _ = _wired({"firewall_policies": raw})

        data = fgt.get("firewall_policies")

        assert data == raw
        assert isinstance(data, list)
        assert isinstance(data[0], dict)
        assert len(data) == 2
        assert [p["name"] for p in data if p["status"] == "enable"] == ["p1"]
        assert sorted(key for key in data[0]) == ["name", "srcintf", "status"]
        assert data[0]["srcintf"][0]["name"] == "port1"
        assert str(data[1]) == str(raw[1])
        assert data[:1] == raw[:1]

    def test_field_missing_in_every_sibling_is_a_gap(self):
        raw = {"status": "enable", "resolve-ip": "disable"}
        fgt, report, findings = _wired({"log_settings": raw})

        settings = fgt.get("log_settings")
        event = settings["event"] if "event" in settings else "disable"
        report.finding("chk-log", "fail", f"event={event}", ["log_settings"])

        assert findings[0]["status"] == "indeterminate"
        assert findings[0]["reported_status"] == "fail"
        assert findings[0]["data_gaps"] == [
            {"endpoint": "log_settings", "kind": "missing_field", "field": "event"}
        ]
        assert "event" in findings[0]["status_reason"]

    def test_field_present_in_some_siblings_is_optional_and_not_a_gap(self):
        raw = [{"name": "p1", "comments": "x"}, {"name": "p2"}]
        fgt, report, findings = _wired({"firewall_policies": raw})

        policies = fgt.get("firewall_policies")
        commented = [p for p in policies if "comments" in p]
        report.finding("chk-policies", "pass", f"commented={len(commented)}")

        assert findings[0]["status"] == "pass"

    def test_reading_a_present_field_is_not_a_gap(self):
        fgt, report, findings = _wired({"log_settings": {"status": "enable"}})

        settings = fgt.get("log_settings")
        report.finding("chk-log", "pass", "status=" + settings["status"])

        assert findings[0]["status"] == "pass"

    def test_subscript_on_a_missing_field_still_raises_and_is_recorded(self):
        ledger = ReadLedger()
        fgt = FgtCapability(_FakeFortiGateClient({"dns": {"primary": "192.0.2.1"}}), ledger=ledger)

        with pytest.raises(KeyError):
            fgt.get("dns")["tertiary"]

        assert ledger.gaps == [{"endpoint": "dns", "kind": "missing_field", "field": "tertiary"}]

    def test_nested_objects_keep_the_tracking(self):
        raw = [{"name": "p1", "srcintf": [{"name": "port1"}]}]
        fgt, report, findings = _wired({"firewall_policies": raw})

        policies = fgt.get("firewall_policies")
        zones = [i["zone"] for p in policies for i in p["srcintf"] if "zone" in i]
        report.finding("chk-policies", "pass", f"zones={zones}")

        assert findings[0]["data_gaps"] == [
            {"endpoint": "firewall_policies", "kind": "missing_field", "field": "zone"}
        ]

    def test_gaps_name_endpoints_and_fields_never_values(self):
        raw = [{"name": "valor-secreto-del-equipo", "accprofile": "perfil-secreto"}]
        fgt, report, findings = _wired({"admins": raw, "api_users": []})

        admins = fgt.get("admins")
        fgt.get("api_users")
        trusted = [a for a in admins if "trusthost1" in a]
        report.finding("chk-admins", "pass", f"trusted={len(trusted)}")

        rendered = str(findings[0]["data_gaps"]) + findings[0]["status_reason"]
        assert "valor-secreto-del-equipo" not in rendered
        assert "perfil-secreto" not in rendered
        assert {gap["kind"] for gap in findings[0]["data_gaps"]} == {
            "missing_field",
            "empty_not_possible",
        }
