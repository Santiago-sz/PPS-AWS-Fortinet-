"""
Tests para sandbox.py — namespace restringido + presupuesto duro para
ejecutar un script ya validado por script_validator.py.

Nota de plataforma (ver apply-progress / risk notes): `signal.setitimer` +
`SIGALRM` son Unix-only en la stdlib. Este entorno de test corre en
Windows (Git Bash), donde NO están disponibles — verificado explícitamente
en `_signal_alarm_available()` más abajo. Producción corre en AWS Lambda
(Linux), donde sí están disponibles.

Estrategia cross-platform:
  - El cap de wall-clock se prueba dos veces con dos mecanismos distintos:
    1. El GATE por-llamada (`_check_wall_clock`, corre en CADA llamada a
       fgt/report) — se prueba inyectando un `clock` fake determinístico.
       Este es el mecanismo real de producción, no un mock del sandbox.
    2. El backstop de `signal.setitimer` para spins de CPU pura sin
       ninguna llamada a fgt/report — se prueba inyectando un
       `alarm_installer` fake que dispara `on_timeout()` en el momento
       exacto que el test controla (simula "la señal llegó acá").
  - Un test de integración real con `signal.setitimer` real corre
    `skipif` en plataformas sin soporte (Windows) — documentado
    explícitamente, no fingido como pasado.
"""

import signal

import pytest

from sandbox import (
    SandboxBudget,
    SandboxBudgetExceeded,
    execute,
)


def _signal_alarm_available() -> bool:
    return hasattr(signal, "setitimer") and hasattr(signal, "SIGALRM")


class _FakeFortiGateClient:
    """Doble de FortiGateClient exponiendo la superficie PÚBLICA
    `get(endpoint_key)` (task 6.3) — la misma que usa `FgtCapability`."""

    def __init__(self, responses: dict[str, object] | None = None):
        self._responses = responses or {}
        self.calls: list[str] = []

    def get(self, endpoint_key: str):
        self.calls.append(endpoint_key)
        return self._responses.get(endpoint_key)


VALID_MANIFEST = {
    "run_id": "run-1",
    "checks": [
        {"check_id": "chk1", "title": "Admin lockout", "clause_ref": {"page": 1}},
    ],
}


class TestNamespaceIsolation:
    def test_script_cannot_reach_filesystem_or_builtins(self):
        source = 'x = open("secret.txt")\n'
        client = _FakeFortiGateClient()

        with pytest.raises(NameError):
            execute(source, VALID_MANIFEST, client)

    def test_script_cannot_import_anything(self):
        # With __builtins__ = {}, the IMPORT_NAME opcode can't even find
        # `__import__` itself — raises ImportError, not NameError, but the
        # net effect is identical: no import ever succeeds.
        source = "import os\nx = os.getcwd()\n"
        client = _FakeFortiGateClient()

        with pytest.raises(ImportError):
            execute(source, VALID_MANIFEST, client)

    def test_safe_names_are_available(self):
        source = "report.note('chk1', str(len([1, 2, 3])))\n"
        client = _FakeFortiGateClient()

        result = execute(source, VALID_MANIFEST, client)

        assert result.notes == [{"check_id": "chk1", "message": "3"}]


class TestDisallowedCapabilityCall:
    def test_disallowed_capability_method_fails_inside_sandbox(self):
        # `fgt.destroy` doesn't exist on FgtCapability — must fail with
        # AttributeError, and MUST NOT reach the underlying client at all
        # (no network/filesystem/credential reach).
        source = "fgt.destroy()\n"
        client = _FakeFortiGateClient({"admins": []})

        with pytest.raises(AttributeError):
            execute(source, VALID_MANIFEST, client)

        assert client.calls == []


class TestCallCountBudget:
    def test_call_count_cap_terminates_and_records_reason(self):
        source = "for i in range(10):\n    fgt.get('admins')\n"
        client = _FakeFortiGateClient({"admins": []})
        budget = SandboxBudget(max_wall_clock_s=120.0, max_fgt_calls=3, max_findings=500)

        with pytest.raises(SandboxBudgetExceeded) as excinfo:
            execute(source, VALID_MANIFEST, client, budget=budget)

        assert excinfo.value.reason == "call_count_exceeded"

    def test_call_count_cap_respects_memoization_still_counts_logical_calls(self):
        # Same endpoint every time (memoized underlying fetch) — the budget
        # must still count each LOGICAL fgt.get() call, or a flood against
        # one cached endpoint would never trip the cap.
        source = "for i in range(10):\n    fgt.get('admins')\n"
        client = _FakeFortiGateClient({"admins": []})
        budget = SandboxBudget(max_wall_clock_s=120.0, max_fgt_calls=5, max_findings=500)

        with pytest.raises(SandboxBudgetExceeded) as excinfo:
            execute(source, VALID_MANIFEST, client, budget=budget)

        assert excinfo.value.reason == "call_count_exceeded"
        assert client.calls == ["admins"]  # only 1 real fetch, cap still tripped


class TestWallClockBudgetViaPerCallGate:
    def test_wall_clock_cutoff_terminates_and_preserves_partial_findings(self):
        # Deterministic fake clock: returns 0.0 for the first three toolkit
        # calls (two findings + the check before the third), then a value
        # that blows the budget on the third call's gate check.
        ticks = iter([0.0, 0.0, 0.0, 999.0])

        def fake_clock():
            return next(ticks, 999.0)

        source = (
            "report.finding('chk1', 'pass', 'evidencia 1')\n"
            "report.finding('chk1', 'pass', 'evidencia 2')\n"
            "report.finding('chk1', 'pass', 'evidencia 3')\n"
        )
        client = _FakeFortiGateClient()
        budget = SandboxBudget(max_wall_clock_s=10.0, max_fgt_calls=40, max_findings=500)

        with pytest.raises(SandboxBudgetExceeded) as excinfo:
            execute(source, VALID_MANIFEST, client, budget=budget, clock=fake_clock)

        assert excinfo.value.reason == "wall_clock_exceeded"
        # Partial findings collected BEFORE the cutoff must be preserved.
        assert len(excinfo.value.findings) >= 1
        assert excinfo.value.findings[0]["evidence"] == "evidencia 1"


class TestWallClockBudgetViaSignalBackstop:
    def test_injected_alarm_timeout_preserves_findings_collected_so_far(self):
        """
        Simulates "the OS-level wall-clock signal fired exactly here" by
        letting the fake FortiGate client itself invoke the captured
        on_timeout callback mid-script — deterministic, cross-platform,
        and exercises the REAL on_timeout -> SandboxBudgetExceeded wiring
        (not a mock of the exception itself).
        """
        captured = {}

        def fake_alarm_installer(seconds, on_timeout):
            captured["on_timeout"] = on_timeout
            return lambda: None  # uninstall no-op

        class _TimeoutTriggeringClient(_FakeFortiGateClient):
            def get(self, endpoint_key):
                super().get(endpoint_key)
                captured["on_timeout"]()  # simulate: signal fires right here
                return None

        source = (
            "report.finding('chk1', 'pass', 'antes del timeout')\n"
            "fgt.get('admins')\n"
            "report.finding('chk1', 'pass', 'nunca debería llegar acá')\n"
        )
        client = _TimeoutTriggeringClient({"admins": []})
        budget = SandboxBudget(max_wall_clock_s=120.0, max_fgt_calls=40, max_findings=500)

        with pytest.raises(SandboxBudgetExceeded) as excinfo:
            execute(
                source,
                VALID_MANIFEST,
                client,
                budget=budget,
                alarm_installer=fake_alarm_installer,
            )

        assert excinfo.value.reason == "wall_clock_exceeded"
        assert len(excinfo.value.findings) == 1
        assert excinfo.value.findings[0]["evidence"] == "antes del timeout"

    @pytest.mark.skipif(
        not _signal_alarm_available(),
        reason=(
            "signal.setitimer/SIGALRM is Unix-only in the stdlib — not "
            "available on this Windows test environment. Production Lambda "
            "runs Linux, where this path is real and active. Run this test "
            "on a Linux/WSL/CI runner to exercise it for real."
        ),
    )
    def test_real_signal_backstop_terminates_pure_cpu_spin_with_no_toolkit_calls(self):
        # No fgt/report call at all -> the per-call gate never runs. Only
        # the real signal.setitimer backstop can catch this.
        source = "for i in range(10**9):\n    pass\n"
        client = _FakeFortiGateClient()
        budget = SandboxBudget(max_wall_clock_s=0.05, max_fgt_calls=40, max_findings=500)

        with pytest.raises(SandboxBudgetExceeded) as excinfo:
            execute(source, VALID_MANIFEST, client, budget=budget)

        assert excinfo.value.reason == "wall_clock_exceeded"


class TestFindingsBudget:
    def test_findings_cap_terminates_execution(self):
        source = "for i in range(10):\n    report.finding('chk1', 'pass', 'ok')\n"
        client = _FakeFortiGateClient()
        budget = SandboxBudget(max_wall_clock_s=120.0, max_fgt_calls=40, max_findings=3)

        with pytest.raises(SandboxBudgetExceeded) as excinfo:
            execute(source, VALID_MANIFEST, client, budget=budget)

        assert excinfo.value.reason == "findings_exceeded"
        assert len(excinfo.value.findings) == 3


class TestSuccessfulExecution:
    def test_execution_under_budget_returns_all_findings_and_notes(self):
        source = (
            "fgt.get('admins')\n"
            "report.finding('chk1', 'pass', 'ok')\n"
            "report.note('chk1', 'revisado')\n"
        )
        client = _FakeFortiGateClient({"admins": []})

        result = execute(source, VALID_MANIFEST, client)

        assert len(result.findings) == 1
        assert result.findings[0]["check_id"] == "chk1"
        assert result.notes == [{"check_id": "chk1", "message": "revisado"}]


# ---------------------------------------------------------------------------
# Datos ausentes: el sandbox cablea el registro entre `fgt` y `report`
# (decisión 12). Los scripts imitan los modismos de los scripts generados y
# no cooperan: no comprueban None ni declaran lagunas.
# ---------------------------------------------------------------------------

LAB_MANIFEST = {
    "run_id": "run-lab",
    "checks": [
        {"check_id": "chk-0002", "clause_ref": {"page": 1}, "endpoints": ["admins"]},
        {
            "check_id": "chk-0003",
            "clause_ref": {"page": 2},
            "endpoints": ["admins", "api_users"],
        },
        {"check_id": "chk-0010", "clause_ref": {"page": 3}, "endpoints": ["vpn_ipsec"]},
        {"check_id": "chk-0011", "clause_ref": {"page": 4}, "endpoints": ["radius_servers"]},
        {"check_id": "chk-0012", "clause_ref": {"page": 5}, "endpoints": ["dhcp_servers"]},
        {"check_id": "chk-0013", "clause_ref": {"page": 6}, "endpoints": ["snmp_sysinfo"]},
    ],
}

# Formas leídas del equipo de laboratorio (FortiOS 7.6.8, perfil
# super_admin_readonly): 200 con lista vacía en las cuatro tablas y un error
# HTTP (None en el cliente) en las dos rutas mal formadas.
LAB_RESPONSES = {
    "admins": [],
    "api_users": [],
    "vpn_ipsec": [],
    "radius_servers": [],
    "dhcp_servers": None,
    "snmp_sysinfo": None,
}

LAB_SCRIPT = """
admins = fgt.get("admins")
api_users = fgt.get("api_users")
supers = [a["name"] for a in admins if a["accprofile"] == "super_admin"]
report.finding(
    "chk-0002",
    "pass" if len(supers) <= 2 else "fail",
    "total_admins=" + str(len(admins)) + " super_admin_accounts=" + str(supers),
)
report.finding(
    "chk-0003",
    "pass",
    "total_admins=" + str(len(admins)) + " api_users=" + str(len(api_users)),
)
tunnels = fgt.get("vpn_ipsec")
report.finding("chk-0010", "pass", "tunnels=" + str(len(tunnels)), ["vpn_ipsec"])
radius = fgt.get("radius_servers")
report.finding("chk-0011", "not_applicable", "radius=" + str(len(radius)))
dhcp = fgt.get("dhcp_servers")
enabled = [s for s in dhcp if s["status"] == "enable"]
report.finding("chk-0012", "pass", "dhcp_enabled=" + str(len(enabled)))
snmp = fgt.get("snmp_sysinfo")
snmp_status = snmp["status"] if "status" in snmp else "disable"
report.finding("chk-0013", "fail" if snmp_status == "enable" else "pass", "snmp=" + snmp_status)
"""


class TestAbsentDataEndsInIndeterminate:
    def _run(self):
        result = execute(LAB_SCRIPT, LAB_MANIFEST, _FakeFortiGateClient(dict(LAB_RESPONSES)))
        return {f["check_id"]: f for f in result.findings}

    def test_the_false_pass_on_administrators_is_no_longer_reported(self):
        findings = self._run()

        for check_id in ("chk-0002", "chk-0003"):
            assert findings[check_id]["status"] == "indeterminate"
            assert findings[check_id]["reported_status"] == "pass"
            assert "admins" in findings[check_id]["status_reason"]
        assert {g["endpoint"] for g in findings["chk-0003"]["data_gaps"]} == {
            "admins",
            "api_users",
        }

    def test_legitimately_empty_tables_keep_their_result(self):
        findings = self._run()

        assert findings["chk-0010"]["status"] == "pass"
        assert findings["chk-0011"]["status"] == "not_applicable"
        assert "data_gaps" not in findings["chk-0010"]
        assert "reported_status" not in findings["chk-0011"]

    def test_unreadable_endpoints_do_not_crash_the_run_and_are_indeterminate(self):
        findings = self._run()

        assert len(findings) == 6
        for check_id, endpoint in (("chk-0012", "dhcp_servers"), ("chk-0013", "snmp_sysinfo")):
            assert findings[check_id]["status"] == "indeterminate"
            assert findings[check_id]["reported_status"] == "pass"
            assert {"endpoint": endpoint, "kind": "unreadable"} in findings[check_id]["data_gaps"]

    def test_no_pass_survives_on_a_check_with_absent_data(self):
        findings = self._run()

        passed = {cid for cid, f in findings.items() if f["status"] == "pass"}
        assert passed == {"chk-0010"}

    def test_budgets_still_count_calls_on_unreadable_endpoints(self):
        source = "for i in range(10):\n    fgt.get('dhcp_servers')\n"
        budget = SandboxBudget(max_wall_clock_s=120.0, max_fgt_calls=3, max_findings=500)

        with pytest.raises(SandboxBudgetExceeded) as excinfo:
            execute(source, LAB_MANIFEST, _FakeFortiGateClient(), budget=budget)

        assert excinfo.value.reason == "call_count_exceeded"

    def test_the_script_gains_no_new_names_in_its_namespace(self):
        source = "x = ReadLedger\n"

        with pytest.raises(NameError):
            execute(source, LAB_MANIFEST, _FakeFortiGateClient())
