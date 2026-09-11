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
    def __init__(self, responses: dict[str, object] | None = None):
        self._responses = responses or {}
        self.calls: list[str] = []

    def _get(self, path: str):
        self.calls.append(path)
        return self._responses.get(path)


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
        client = _FakeFortiGateClient({"system/admin": []})

        with pytest.raises(AttributeError):
            execute(source, VALID_MANIFEST, client)

        assert client.calls == []


class TestCallCountBudget:
    def test_call_count_cap_terminates_and_records_reason(self):
        source = "for i in range(10):\n    fgt.get('admins')\n"
        client = _FakeFortiGateClient({"system/admin": []})
        budget = SandboxBudget(max_wall_clock_s=120.0, max_fgt_calls=3, max_findings=500)

        with pytest.raises(SandboxBudgetExceeded) as excinfo:
            execute(source, VALID_MANIFEST, client, budget=budget)

        assert excinfo.value.reason == "call_count_exceeded"

    def test_call_count_cap_respects_memoization_still_counts_logical_calls(self):
        # Same endpoint every time (memoized underlying fetch) — the budget
        # must still count each LOGICAL fgt.get() call, or a flood against
        # one cached endpoint would never trip the cap.
        source = "for i in range(10):\n    fgt.get('admins')\n"
        client = _FakeFortiGateClient({"system/admin": []})
        budget = SandboxBudget(max_wall_clock_s=120.0, max_fgt_calls=5, max_findings=500)

        with pytest.raises(SandboxBudgetExceeded) as excinfo:
            execute(source, VALID_MANIFEST, client, budget=budget)

        assert excinfo.value.reason == "call_count_exceeded"
        assert client.calls == ["system/admin"]  # only 1 real fetch, cap still tripped


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
            def _get(self, path):
                super()._get(path)
                captured["on_timeout"]()  # simulate: signal fires right here
                return None

        source = (
            "report.finding('chk1', 'pass', 'antes del timeout')\n"
            "fgt.get('admins')\n"
            "report.finding('chk1', 'pass', 'nunca debería llegar acá')\n"
        )
        client = _TimeoutTriggeringClient({"system/admin": []})
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
        client = _FakeFortiGateClient({"system/admin": []})

        result = execute(source, VALID_MANIFEST, client)

        assert len(result.findings) == 1
        assert result.findings[0]["check_id"] == "chk1"
        assert result.notes == [{"check_id": "chk1", "message": "revisado"}]
