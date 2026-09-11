"""
Objetos de capacidad inyectados en el namespace del sandbox: `fgt` y `report`.

Un script generado nunca ve `FortiGateClient` directamente — solo estos dos
objetos, con una superficie deliberadamente mínima:

  fgt.get(endpoint_key) -> data | None   # solo lectura, memoizado
  fgt.endpoints() -> list[str]
  report.finding(check_id, status, evidence, endpoints_used=None)
  report.note(check_id, message)

`report.finding` resuelve `clause_ref` del lado del servidor, a partir del
manifest — el script jamás puede pasar ni forjar su propio clause_ref
(design.md Decision #4).

Nota de puente con Phase 6 (fuera de alcance acá): `fortigate_client.py`
todavía no expone un `get(endpoint_key)` público (task 6.3) — este módulo
usa el método interno `FortiGateClient._get(path)` como bridge. Cuando 6.3
aterrice, el llamado interno puede reemplazarse por el método público sin
cambiar la superficie de `FgtCapability`.
"""

from collections.abc import Callable
from typing import Any

import fortigate_client


class UnknownEndpointError(Exception):
    """`fgt.get()` fue llamado con un endpoint_key fuera del catálogo."""


def _noop() -> None:
    return None


class FgtCapability:
    """Acceso de solo lectura y memoizado a los endpoints de FortiGate.

    `on_call` es el hook de presupuesto del sandbox (cap de cantidad de
    llamadas + wall-clock) — se invoca en CADA llamada lógica, incluso en
    un cache hit, porque el límite de llamadas debe frenar un flood contra
    un mismo endpoint memoizado, no solo llamadas de red reales.
    """

    def __init__(self, client: Any, on_call: Callable[[], None] | None = None):
        self._client = client
        self._on_call = on_call or _noop
        self._cache: dict[str, Any] = {}
        self._path_by_label = {label: path for path, label in fortigate_client.ENDPOINTS}

    def get(self, endpoint_key: str) -> Any:
        self._on_call()

        if endpoint_key in self._cache:
            return self._cache[endpoint_key]

        path = self._path_by_label.get(endpoint_key)
        if path is None:
            raise UnknownEndpointError(f"unknown FortiGate endpoint: '{endpoint_key}'")

        value = self._client._get(path)
        self._cache[endpoint_key] = value
        return value

    def endpoints(self) -> list[str]:
        return sorted(self._path_by_label)


class ReportCapability:
    """Registro de hallazgos/notas — `clause_ref` siempre resuelto acá,
    nunca aceptado como argumento del script."""

    def __init__(
        self,
        manifest: dict | None,
        findings: list[dict],
        notes: list[dict],
        on_finding: Callable[[], None] | None = None,
        on_note: Callable[[], None] | None = None,
    ):
        checks = (manifest or {}).get("checks") or []
        self._checks_by_id = {
            c["check_id"]: c for c in checks if isinstance(c, dict) and c.get("check_id")
        }
        self._findings = findings
        self._notes = notes
        self._on_finding = on_finding or _noop
        self._on_note = on_note or _noop

    def finding(
        self,
        check_id: str,
        status: str,
        evidence: str,
        endpoints_used: list[str] | None = None,
    ) -> None:
        self._on_finding()

        check = self._checks_by_id.get(check_id)
        traceable = check is not None
        clause_ref = check.get("clause_ref") if traceable else None

        self._findings.append(
            {
                "check_id": check_id,
                "clause_ref": clause_ref,
                "status": status,
                "evidence": evidence,
                "endpoints_used": list(endpoints_used) if endpoints_used else [],
                "traceable": traceable,
            }
        )

    def note(self, check_id: str, message: str) -> None:
        self._on_note()
        self._notes.append({"check_id": check_id, "message": message})
