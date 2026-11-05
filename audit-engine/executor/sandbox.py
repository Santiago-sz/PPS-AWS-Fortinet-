"""
Ejecución de un script de auditoría ya validado, bajo namespace restringido
y presupuesto duro.

`execute()` NO re-valida el script — esa es responsabilidad de un caller
separado (handler_executor.py, Phase 8, fuera de alcance acá) que corre
`script_validator.validate()` de forma independiente antes de llegar acá
(design.md: "Gate order... Executor repeats all three against
script_sha256"). Este módulo asume que el AST allowlist ya pasó y se
concentra en dos cosas: namespace mínimo + límites duros.

Runaway containment (design.md Decision #6): `script_validator.py` deniega
`Try` — eso es lo que hace que `SandboxBudgetExceeded` sea imposible de
atrapar por el script generado. Este módulo asume esa garantía; no la
re-implementa acá.

Nota de plataforma: `signal.setitimer`/`SIGALRM` son Unix-only en la
stdlib de Python — no existen en Windows. El cap de wall-clock tiene DOS
mecanismos independientes por eso:
  1. Gate por-llamada (`_check_wall_clock`): corre en CADA llamada a
     fgt/report, usando `clock()` (inyectable, `time.monotonic` por
     default) — funciona en cualquier plataforma.
  2. Backstop de `signal.setitimer` (`_default_alarm_installer`): cubre el
     caso de un script que nunca llama a fgt/report (spin de CPU pura vía
     `for`/comprehensions) — solo activo donde `signal.setitimer` existe.
     En producción (AWS Lambda, Linux) siempre existe. En este entorno de
     desarrollo (Windows) se detecta la ausencia explícitamente y se
     degrada a no-op con un warning de log — nunca finge que el backstop
     corrió cuando no corrió.
"""

import builtins
import logging
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from toolkit import FgtCapability, ReportCapability

logger = logging.getLogger(__name__)

# Nombres seguros inyectados en el namespace del script (design.md
# Interfaces: "safe names"). Todo lo demás queda fuera de alcance porque
# __builtins__ se reemplaza por un dict vacío.
_SAFE_NAME_LIST = (
    "len",
    "str",
    "int",
    "float",
    "bool",
    "list",
    "dict",
    "set",
    "tuple",
    "sorted",
    "any",
    "all",
    "min",
    "max",
    "sum",
    "enumerate",
    "zip",
    "range",
    "isinstance",
    "abs",
    "round",
)


@dataclass(frozen=True)
class SandboxBudget:
    max_wall_clock_s: float = 120.0
    max_fgt_calls: int = 40
    max_findings: int = 500


DEFAULT_BUDGET = SandboxBudget()


class SandboxBudgetExceeded(Exception):
    """Un límite duro se excedió. Siempre carga los findings/notes
    parciales recolectados hasta el momento del corte — nunca se pierden."""

    def __init__(self, reason: str, message: str, findings: list[dict], notes: list[dict]):
        self.reason = reason  # "wall_clock_exceeded" | "call_count_exceeded" | "findings_exceeded"
        self.findings = findings
        self.notes = notes
        super().__init__(message)


@dataclass(frozen=True)
class SandboxResult:
    findings: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)


def _safe_names() -> dict[str, Any]:
    return {name: getattr(builtins, name) for name in _SAFE_NAME_LIST}


def _build_namespace(fgt: FgtCapability, report: ReportCapability) -> dict[str, Any]:
    namespace: dict[str, Any] = {"__builtins__": {}}
    namespace.update(_safe_names())
    namespace["fgt"] = fgt
    namespace["report"] = report
    return namespace


def _no_op_uninstall() -> None:
    return None


def _default_alarm_installer(seconds: float, on_timeout: Callable[[], None]) -> Callable[[], None]:
    if not (hasattr(signal, "setitimer") and hasattr(signal, "SIGALRM")):
        logger.warning(
            "signal.setitimer/SIGALRM unavailable on this platform — the "
            "pure-CPU-spin wall-clock backstop is disabled. Only the "
            "per-toolkit-call gate remains active here. Production Lambda "
            "(Linux) always has signal.setitimer available."
        )
        return _no_op_uninstall

    def _handler(signum, frame):
        on_timeout()

    previous_handler = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)

    def _uninstall() -> None:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)

    return _uninstall


def execute(
    source: str,
    manifest: dict,
    fgt_client: Any,
    budget: SandboxBudget = DEFAULT_BUDGET,
    clock: Callable[[], float] = time.monotonic,
    alarm_installer: Callable[[float, Callable[[], None]], Callable[[], None]] | None = None,
) -> SandboxResult:
    """Compila y ejecuta `source` bajo namespace restringido + presupuesto.

    Deja propagar cualquier excepción que no sea `SandboxBudgetExceeded`
    (ej. `AttributeError` de una llamada a capability inexistente,
    `NameError` de un builtin no inyectado) — el caller decide cómo
    reportarla; este módulo solo garantiza que NINGUNA de esas rutas
    alcanza red/filesystem/credenciales reales.
    """
    findings: list[dict] = []
    notes: list[dict] = []
    start = clock()

    def _raise(reason: str, message: str) -> None:
        raise SandboxBudgetExceeded(reason, message, list(findings), list(notes))

    def _check_wall_clock() -> None:
        if clock() - start > budget.max_wall_clock_s:
            _raise(
                "wall_clock_exceeded",
                f"execution exceeded the {budget.max_wall_clock_s}s wall-clock budget",
            )

    fgt_call_count = {"n": 0}

    def _on_fgt_call() -> None:
        _check_wall_clock()
        fgt_call_count["n"] += 1
        if fgt_call_count["n"] > budget.max_fgt_calls:
            _raise(
                "call_count_exceeded",
                f"exceeded the {budget.max_fgt_calls}-call budget for fgt.get()",
            )

    def _on_finding_call() -> None:
        _check_wall_clock()
        if len(findings) >= budget.max_findings:
            _raise("findings_exceeded", f"exceeded the {budget.max_findings}-finding budget")

    def _on_note_call() -> None:
        _check_wall_clock()

    def _on_timeout() -> None:
        _raise(
            "wall_clock_exceeded",
            f"execution exceeded the {budget.max_wall_clock_s}s wall-clock budget (signal)",
        )

    fgt = FgtCapability(fgt_client, on_call=_on_fgt_call)
    report = ReportCapability(
        manifest, findings, notes, on_finding=_on_finding_call, on_note=_on_note_call
    )
    namespace = _build_namespace(fgt, report)

    install = alarm_installer or _default_alarm_installer
    uninstall = install(budget.max_wall_clock_s, _on_timeout)
    try:
        compiled = compile(source, "<generated_audit_script>", "exec")
        exec(compiled, namespace)
    finally:
        uninstall()

    return SandboxResult(findings=findings, notes=notes)
