"""
Observabilidad estructurada para el pipeline de auditoria (solo stdlib).

Tres primitivas, todas pensadas para CloudWatch Logs en AWS Lambda:

  log_event(event, **fields)   -> una linea JSON `{"event":..., "ts":..., ...}`
  emit_metric(name, value, ...)-> una linea JSON en formato CloudWatch
                                  Embedded Metric Format (EMF): CloudWatch la
                                  convierte automaticamente en una metrica
                                  sin ninguna llamada a la API de CloudWatch.
  timer()                      -> context manager que mide milisegundos.

Cada evento o metrica se escribe como EXACTAMENTE una linea JSON por stdout,
a traves del logger propio de este modulo. El logger no propaga al root
logger a proposito: el formato configurado por los handlers (timestamp,
nivel, nombre) prefijaria la linea y romperia el parseo EMF/JSON del lado
de CloudWatch. Los logs legibles por humanos siguen saliendo por los
loggers de cada modulo, sin cambios.
"""

import json
import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

NAMESPACE = "PPS/AuditPipeline"

logger = logging.getLogger("pps.observability")


class _StdoutHandler(logging.StreamHandler):
    """StreamHandler que resuelve `sys.stdout` en cada emision.

    Resolverlo tarde (y no al importar el modulo) permite que una
    redireccion posterior de stdout -- la captura de pytest, por ejemplo --
    siga recibiendo las lineas.
    """

    def __init__(self) -> None:
        super().__init__(stream=sys.stdout)

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, value) -> None:
        # El stream es siempre sys.stdout; se ignora cualquier asignacion.
        return None


def _configure_logger() -> None:
    if not any(isinstance(h, _StdoutHandler) for h in logger.handlers):
        handler = _StdoutHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


_configure_logger()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _emit(payload: dict) -> None:
    logger.info(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")))


def log_event(event: str, **fields) -> dict:
    """Escribe un evento estructurado como una unica linea JSON.

    El payload siempre lleva `event` y `ts` (UTC ISO-8601); el resto de los
    campos se agregan tal cual. Devuelve el payload emitido (util en tests).
    """
    payload = {"event": event, "ts": _now_iso(), **fields}
    _emit(payload)
    return payload


def emit_metric(
    name: str,
    value: float,
    unit: str = "Count",
    dimensions: dict | None = None,
    namespace: str = NAMESPACE,
) -> dict:
    """Escribe una metrica en CloudWatch Embedded Metric Format (EMF).

    CloudWatch Logs detecta el bloque `_aws` y publica la metrica en el
    namespace indicado, con las dimensiones dadas (sus valores viajan como
    campos de primer nivel en la misma linea, como exige el formato).
    """
    dims = {str(k): str(v) for k, v in (dimensions or {}).items()}
    payload = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": namespace,
                    "Dimensions": [list(dims.keys())],
                    "Metrics": [{"Name": name, "Unit": unit}],
                }
            ],
        },
        **dims,
        name: value,
    }
    _emit(payload)
    return payload


class Timer:
    """Cronometro simple en milisegundos (perf_counter)."""

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._end: float | None = None

    @property
    def elapsed_ms(self) -> float:
        end = self._end if self._end is not None else time.perf_counter()
        return (end - self._start) * 1000.0

    def stop(self) -> float:
        self._end = time.perf_counter()
        return self.elapsed_ms


@contextmanager
def timer() -> Iterator[Timer]:
    """Context manager: `with timer() as t: ...; t.elapsed_ms`."""
    t = Timer()
    try:
        yield t
    finally:
        t.stop()
