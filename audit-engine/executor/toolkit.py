"""
Objetos de capacidad inyectados en el namespace del sandbox: `fgt` y `report`.

Un script generado nunca ve `FortiGateClient` directamente — solo estos dos
objetos, con una superficie deliberadamente mínima:

  fgt.get(endpoint_key) -> data          # solo lectura, memoizado
  fgt.endpoints() -> list[str]
  report.finding(check_id, status, evidence, endpoints_used=None)
  report.note(check_id, message)

`report.finding` resuelve `clause_ref` (y la `remediation` propuesta) del
lado del servidor, a partir del manifest — el script jamás puede pasar ni
forjar su propio clause_ref (design.md Decision #4). Lo mismo vale para
`references` (documentos de referencia por control), que se leen del bloque
`knowledge_base` del manifest cuando existe; este modulo no consulta ningun
servicio para obtenerlos.

Datos ausentes (decisión 12): `fgt` y `report` comparten un `ReadLedger`.
`fgt.get` anota en él qué endpoint resultó ilegible o imposiblemente vacío y
devuelve los objetos envueltos en `TrackedDict`, que anota el pedido de un
campo que la respuesta no trae. `report.finding` consulta ese registro y
guarda `indeterminate` cuando el control depende de un dato que no estuvo:
la garantía es del toolkit y no requiere que el script coopere. Un endpoint
ilegible se entrega como lista vacía, no como `None`.

`FgtCapability.get()` delega en el método público `FortiGateClient.get(
endpoint_key)` (task 6.3) — la resolución de path y la memoización de bajo
nivel viven en el cliente. `FgtCapability` mantiene su PROPIA memoización
y validación de endpoint_key desconocido, porque necesita:
  1. Invocar `on_call` (el hook de presupuesto del sandbox) en CADA llamada
     lógica, incluso en un cache hit propio.
  2. Rechazar un endpoint_key inválido SIN llegar a tocar el cliente real
     (`client.get()` nunca se invoca para una clave desconocida).
"""

from collections.abc import Callable
from typing import Any

import fortigate_client


class UnknownEndpointError(Exception):
    """`fgt.get()` fue llamado con un endpoint_key fuera del catálogo."""


def _noop() -> None:
    return None


# Largo maximo del identificador de origen que se copia al hallazgo.
_MAX_REFERENCE_SOURCE_CHARS = 300


def _clean_reference(entry: Any) -> dict | None:
    """Reduce una entrada de referencia del manifest a `{source, score}`.

    Solo esos dos campos viajan al reporte, con tipos controlados: cualquier
    otro dato (incluido texto de documentos) se descarta.
    """
    if not isinstance(entry, dict):
        return None
    source = entry.get("source")
    if isinstance(source, str) and source.strip():
        source = " ".join(source.split())[:_MAX_REFERENCE_SOURCE_CHARS]
    else:
        source = None
    score = entry.get("score")
    if isinstance(score, bool) or not isinstance(score, int | float):
        score = None
    return {"source": source, "score": score}


def _references_by_check(manifest: dict | None) -> dict[str, list[dict]] | None:
    """Documentos de referencia por `check_id`, leidos del bloque
    `knowledge_base` del manifest.

    Devuelve None si el manifest no trae el bloque o no lo declara habilitado
    (manifests anteriores a la recuperacion, o recuperacion deshabilitada):
    en ese caso los hallazgos conservan su forma previa, sin `references`.
    """
    block = (manifest or {}).get("knowledge_base")
    if not isinstance(block, dict) or block.get("enabled") is not True:
        return None
    raw = block.get("references")
    if not isinstance(raw, dict):
        return {}
    resolved: dict[str, list[dict]] = {}
    for check_id, entries in raw.items():
        if not isinstance(check_id, str) or not isinstance(entries, list):
            continue
        cleaned = [c for c in (_clean_reference(entry) for entry in entries) if c is not None]
        resolved[check_id] = cleaned
    return resolved


# Estados que un hallazgo puede tener. Cualquier otro valor que envíe el
# script se guarda como `indeterminate`.
ALLOWED_STATUSES = frozenset({"pass", "fail", "not_applicable", "indeterminate"})

# Tablas que un equipo en servicio no puede tener vacías: siempre existe al
# menos un administrador, un perfil de administración y una interfaz, y el
# pipeline se autentica con un usuario de API. Una lista vacía en estos
# endpoints significa que el dato no se pudo observar (por ejemplo, por el
# perfil del token), no que la tabla esté vacía. Es un conjunto aparte y no
# un tercer elemento de `ENDPOINTS`, que el flujo legacy desempaqueta de a dos.
NEVER_EMPTY_ENDPOINTS = frozenset({"admins", "admin_profiles", "interfaces", "api_users"})

# Tipos de laguna que registra el toolkit.
GAP_UNREADABLE = "unreadable"
GAP_EMPTY_NOT_POSSIBLE = "empty_not_possible"
GAP_MISSING_FIELD = "missing_field"
GAP_NOT_READ = "not_read"

# Largo máximo de un nombre de campo o de un estado informado que se copia al
# hallazgo. Son textos que elige el script, no valores leídos del equipo.
_MAX_NAME_CHARS = 80


class ReadLedger:
    """Registro de lecturas de una corrida, compartido por `fgt` y `report`.

    Guarda nombres de endpoint, tipos de laguna y nombres de campo. Nunca
    guarda un valor leído del equipo.
    """

    def __init__(self) -> None:
        self.reads: dict[str, str] = {}
        self.gaps: list[dict] = []

    def record_read(self, endpoint: str, outcome: str) -> None:
        self.reads[endpoint] = outcome

    def record_gap(self, endpoint: str, kind: str, field: str | None = None) -> None:
        gap = {"endpoint": endpoint, "kind": kind}
        if field is not None:
            gap["field"] = field
        if gap not in self.gaps:
            self.gaps.append(gap)

    def gaps_for(self, endpoints: list[str] | None) -> list[dict]:
        """Lagunas anotadas hasta ahora; todas si `endpoints` es None."""
        return [dict(gap) for gap in self.gaps if endpoints is None or gap["endpoint"] in endpoints]


class TrackedDict(dict):
    """`dict` que anota el pedido de un campo que la respuesta no trae.

    Se comporta como un `dict` común para `isinstance`, `len`, `str`, la
    iteración y la comparación. Solo `d[k]` y `k in d` consultan el registro,
    y solo cuando la clave falta. El script no gana superficie: el validador
    ya prohíbe todo acceso con punto sobre los datos.

    Un campo que falta es una laguna solo si falta en todos los objetos
    hermanos (los elementos de la misma lista); si algún hermano lo trae, es
    un campo opcional.
    """

    __slots__ = ("_endpoint", "_ledger", "_sibling_keys")

    def __init__(self, data: dict, endpoint: str, sibling_keys: frozenset, ledger: ReadLedger):
        super().__init__(data)
        self._endpoint = endpoint
        self._sibling_keys = sibling_keys
        self._ledger = ledger

    def _note_missing(self, key: Any) -> None:
        if isinstance(key, str) and key not in self._sibling_keys:
            self._ledger.record_gap(self._endpoint, GAP_MISSING_FIELD, key[:_MAX_NAME_CHARS])

    def __contains__(self, key: Any) -> bool:
        present = super().__contains__(key)
        if not present:
            self._note_missing(key)
        return present

    def __getitem__(self, key: Any) -> Any:
        if not super().__contains__(key):
            self._note_missing(key)
        return super().__getitem__(key)


def _string_keys(items: list) -> frozenset:
    return frozenset(
        key for item in items if isinstance(item, dict) for key in item if isinstance(key, str)
    )


def _track(value: Any, endpoint: str, ledger: ReadLedger, sibling_keys: frozenset | None = None):
    """Envuelve de forma recursiva los `dict` de una respuesta.

    Las listas quedan como `list` comunes: sus elementos ya están envueltos,
    así que recorrerlas, cortarlas u ordenarlas conserva el seguimiento.
    """
    if isinstance(value, dict):
        keys = sibling_keys if sibling_keys is not None else _string_keys([value])
        tracked = {key: _track(item, endpoint, ledger) for key, item in value.items()}
        return TrackedDict(tracked, endpoint, keys, ledger)
    if isinstance(value, list):
        keys = _string_keys(value)
        return [
            _track(item, endpoint, ledger, keys if isinstance(item, dict) else None)
            for item in value
        ]
    return value


_GAP_REASONS = {
    GAP_UNREADABLE: "el endpoint `{endpoint}` no pudo leerse",
    GAP_EMPTY_NOT_POSSIBLE: (
        "el endpoint `{endpoint}` devolvió una respuesta vacía y ese dato no puede "
        "estar vacío en un equipo en servicio"
    ),
    GAP_MISSING_FIELD: "la respuesta del endpoint `{endpoint}` no trae el campo `{field}`",
    GAP_NOT_READ: "el endpoint declarado `{endpoint}` no se leyó",
}


def _describe_gaps(gaps: list[dict]) -> str:
    parts = []
    for gap in gaps:
        field = str(gap.get("field", "")).replace("`", "'")
        parts.append(_GAP_REASONS[gap["kind"]].format(endpoint=gap["endpoint"], field=field))
    return "Datos no disponibles: " + "; ".join(parts) + "."


class FgtCapability:
    """Acceso de solo lectura y memoizado a los endpoints de FortiGate.

    `on_call` es el hook de presupuesto del sandbox (cap de cantidad de
    llamadas + wall-clock) — se invoca en CADA llamada lógica, incluso en
    un cache hit, porque el límite de llamadas debe frenar un flood contra
    un mismo endpoint memoizado, no solo llamadas de red reales.
    """

    def __init__(
        self,
        client: Any,
        on_call: Callable[[], None] | None = None,
        ledger: ReadLedger | None = None,
    ):
        self._client = client
        self._on_call = on_call or _noop
        self._ledger = ledger if ledger is not None else ReadLedger()
        self._cache: dict[str, Any] = {}
        self._known_labels = {label for _, label in fortigate_client.ENDPOINTS}

    def get(self, endpoint_key: str) -> Any:
        self._on_call()

        if endpoint_key in self._cache:
            return self._cache[endpoint_key]

        if endpoint_key not in self._known_labels:
            raise UnknownEndpointError(f"unknown FortiGate endpoint: '{endpoint_key}'")

        value = self._observe(endpoint_key, self._client.get(endpoint_key))
        self._cache[endpoint_key] = value
        return value

    def _observe(self, endpoint_key: str, value: Any) -> Any:
        """Anota el resultado de la lectura y devuelve el dato con seguimiento."""
        if value is None:
            # Error HTTP, fallo de red o respuesta sin `results`. Se entrega
            # una lista vacía para que el script no falle; el control queda
            # marcado por el registro, no por el script.
            self._ledger.record_read(endpoint_key, "unreadable")
            self._ledger.record_gap(endpoint_key, GAP_UNREADABLE)
            return []
        if isinstance(value, dict | list) and len(value) == 0:
            self._ledger.record_read(endpoint_key, "empty")
            if endpoint_key in NEVER_EMPTY_ENDPOINTS:
                self._ledger.record_gap(endpoint_key, GAP_EMPTY_NOT_POSSIBLE)
        else:
            self._ledger.record_read(endpoint_key, "ok")
        return _track(value, endpoint_key, self._ledger)

    def endpoints(self) -> list[str]:
        return sorted(self._known_labels)


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
        ledger: ReadLedger | None = None,
    ):
        self._ledger = ledger
        checks = (manifest or {}).get("checks") or []
        self._checks_by_id = {
            c["check_id"]: c for c in checks if isinstance(c, dict) and c.get("check_id")
        }
        self._references_by_id = _references_by_check(manifest)
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
        # La remediacion propuesta tambien se resuelve ACA, desde el manifest
        # (mismo principio que clause_ref): el script generado nunca la
        # redacta ni la altera, y el sistema jamas la ejecuta -- solo viaja
        # al reporte como propuesta para un operador humano.
        remediation = check.get("remediation") if traceable else None

        # El estado final lo decide el toolkit, no el script: un estado fuera
        # de los permitidos, o un control que depende de un dato que no
        # estuvo, se guarda como `indeterminate` y conserva lo informado.
        gaps = self._data_gaps(check, endpoints_used)
        reported_status = status
        reasons = []
        if not (isinstance(status, str) and status in ALLOWED_STATUSES):
            reported_status = str(status)[:_MAX_NAME_CHARS]
            reasons.append("El script informó un estado que no es uno de los cuatro permitidos.")
        if gaps:
            reasons.append(_describe_gaps(gaps))
            # Sin el dato no hay evidencia que respalde una propuesta.
            remediation = None
        if reasons:
            status = "indeterminate"

        finding = {
            "check_id": check_id,
            "clause_ref": clause_ref,
            "status": status,
            "evidence": evidence,
            "endpoints_used": list(endpoints_used) if endpoints_used else [],
            "traceable": traceable,
            "remediation": remediation,
        }
        # Documentos de referencia que respaldaron la generacion del control:
        # tambien se resuelven ACA, desde el manifest, y `finding()` no acepta
        # ningun argumento para pasarlos. La clave solo existe si el manifest
        # declara la recuperacion habilitada.
        if self._references_by_id is not None:
            finding["references"] = [
                dict(reference) for reference in self._references_by_id.get(check_id, [])
            ]
        # Claves aditivas, presentes solo cuando el toolkit intervino: un
        # hallazgo sin lagunas conserva exactamente la forma anterior.
        if reasons:
            if reported_status != status:
                finding["reported_status"] = reported_status
            if gaps:
                finding["data_gaps"] = gaps
            finding["status_reason"] = " ".join(reasons)
        self._findings.append(finding)

    def _data_gaps(self, check: dict | None, endpoints_used: Any) -> list[dict]:
        """Lagunas que afectan a un control en el momento de registrarlo.

        Se atribuyen por endpoint declarado: los de `checks[].endpoints` del
        manifest más los que el script pasa en `endpoints_used` (declarar de
        más solo puede hacer la regla más estricta). Si el control no declara
        ninguno, no se puede acotar de qué dato depende y hereda todas las
        lagunas de la corrida.
        """
        if self._ledger is None:
            return []
        declared: list[str] = []
        for source in ((check or {}).get("endpoints"), endpoints_used):
            for endpoint in source if isinstance(source, list | tuple) else []:
                if isinstance(endpoint, str) and endpoint not in declared:
                    declared.append(endpoint)
        if not declared:
            return self._ledger.gaps_for(None)
        gaps = self._ledger.gaps_for(declared)
        if not any(endpoint in self._ledger.reads for endpoint in declared):
            gaps.extend({"endpoint": endpoint, "kind": GAP_NOT_READ} for endpoint in declared)
        return gaps

    def note(self, check_id: str, message: str) -> None:
        self._on_note()
        self._notes.append({"check_id": check_id, "message": message})
