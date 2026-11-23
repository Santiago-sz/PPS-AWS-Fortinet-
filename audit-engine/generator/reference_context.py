"""
Documentacion de referencia para la fase reduce, recuperada de la Knowledge
Base (`knowledge_retriever`).

Se ejecuta SOLO en el generador, despues de que la fase map produjo los
controles y antes de la fase reduce. Es aditiva y opcional: nunca reemplaza
el recorrido completo de la normativa ni modifica los controles.

Reglas:
  - Una consulta por control, armada unicamente con campos del propio control
    (`title` e `intent`). Nunca con texto crudo de la normativa: ni chunks ni
    la cita de `clause_ref`.
  - Topes explicitos: `MAX_RETRIEVE_CALLS` llamadas `Retrieve` por corrida,
    `MAX_REFERENCE_CHARS_PER_CONTROL` caracteres de referencia por control y
    `MAX_REFERENCE_CHARS` en total. Un fragmento de referencia entra ENTERO o
    se omite, nunca se recorta: por control se omite el que no cabe y se
    prueba el siguiente; sobre el total se descartan primero los de menor
    puntaje. Nunca se recorta la normativa ni se quita un control (regla 7
    de AGENTS.md).
  - El origen de cada fragmento se reduce a la clave del objeto
    (`knowledge_retriever.source_identifier`): el nombre del bucket incluye
    el id de cuenta y no debe llegar al prompt, al manifest ni a los eventos.
  - Fallo blando y visible: un error de recuperacion deja a ese control sin
    referencia, emite el evento `kb_retrieve` y queda contado en el bloque
    del manifest. La generacion continua.
  - El bloque del manifest registra, por `check_id`, el origen y el puntaje de
    cada fragmento usado. Nunca el texto recuperado.
  - La seccion del prompt es material de consulta delimitado, no
    instrucciones: lo que el script puede llamar lo siguen decidiendo el
    catalogo de endpoints y `script_validator`.

El executor no importa este modulo: lee el bloque `knowledge_base` del
manifest (ver `toolkit.ReportCapability`).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import knowledge_retriever
import observability
import reference_kinds

logger = logging.getLogger(__name__)

# Cantidad maxima de llamadas `Retrieve` por corrida (una por control). Los
# controles que exceden el tope quedan sin referencia y se cuentan en
# `controls_skipped_by_call_cap`.
MAX_RETRIEVE_CALLS = 40

# Tope de caracteres de texto recuperado que se agrega al prompt de reduce,
# sumando todos los controles (aprox. 20.000 tokens). Calibrado con el primer
# E2E real (2026-11-18): con 12.000 solo 5 de 17 controles recibian referencia
# y se descartaban 20 fragmentos.
MAX_REFERENCE_CHARS = 80_000

# Tope de caracteres de texto recuperado por control. Evita que un control
# con fragmentos largos consuma el presupuesto de los demas. Tamanos
# observados en la base real el 2026-11-18 para una consulta: 9.943, 1.463,
# 1.109 y 1.082 caracteres. Con 3.000 el fragmento mejor puntuado quedaba
# siempre afuera y en el primer E2E real se omitieron 32 fragmentos; se subio
# a 10.000 para admitir un fragmento grande completo.
MAX_REFERENCE_CHARS_PER_CONTROL = 10_000

REFERENCE_SECTION_START = "=== INICIO DOCUMENTACION DE REFERENCIA ==="
REFERENCE_SECTION_END = "=== FIN DOCUMENTACION DE REFERENCIA ==="
_CHECK_HEADER_PREFIX = "--- check_id="
_OMITTED_DELIMITER = "[delimitador omitido]"

_QUERY_FIELDS = ("title", "intent")


@dataclass(frozen=True)
class ReferenceContext:
    """Resultado de la recuperacion para una corrida.

    `prompt_section` es la seccion delimitada para el prompt de reduce (cadena
    vacia si no quedo ningun fragmento). `manifest_block` es el bloque
    `knowledge_base` del manifest.
    """

    prompt_section: str
    manifest_block: dict


@dataclass(frozen=True)
class _Kept:
    check_index: int
    rank: int
    fragment: knowledge_retriever.RetrievedFragment


def build_query(check: dict) -> str | None:
    """Consulta de busqueda para un control: `title` e `intent`, con los
    espacios normalizados. Devuelve None si el control no tiene texto util."""
    parts = []
    for field in _QUERY_FIELDS:
        value = check.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(" ".join(value.split()))
    return ". ".join(parts) if parts else None


def _retrieve_for_checks(
    checks: list[dict], config: knowledge_retriever.RetrievalConfig, retrieve: Callable
) -> tuple[list[_Kept], dict]:
    kept: list[_Kept] = []
    counts = {"attempted": 0, "failed": 0, "skipped_by_call_cap": 0, "skipped_by_control_cap": 0}
    metadata_filter = config.metadata_filter

    for check_index, check in enumerate(checks):
        query = build_query(check)
        if query is None:
            continue
        if counts["attempted"] >= MAX_RETRIEVE_CALLS:
            counts["skipped_by_call_cap"] += 1
            continue
        counts["attempted"] += 1
        try:
            fragments = retrieve(
                query,
                knowledge_base_id=config.knowledge_base_id,
                max_results=config.max_results,
                metadata_filter=metadata_filter,
            )
        except knowledge_retriever.KnowledgeRetrievalError:
            # `knowledge_retriever` ya emitio `kb_retrieve` con el codigo del error.
            counts["failed"] += 1
            continue
        except Exception as e:
            # La referencia es opcional: ningun fallo al obtenerla interrumpe
            # la generacion. Se registra solo el tipo, nunca el mensaje (puede
            # citar la consulta).
            counts["failed"] += 1
            error = type(e).__name__
            logger.error("Error al recuperar referencia (%s)", error)
            observability.log_event(
                "kb_retrieve",
                knowledge_base_id=config.knowledge_base_id,
                max_results=config.max_results,
                results=0,
                latency_ms=0.0,
                status="error",
                error=error,
            )
            continue
        # El servicio puede devolver menos resultados que `max_results`: se
        # usan los que lleguen, en su orden. Presupuesto por control: un
        # fragmento entra ENTERO o se omite; si no cabe, se prueba el
        # siguiente. Nunca se recorta un fragmento (un corte puede dejar un
        # bloque de configuracion a medias y volverlo enganoso).
        used = 0
        for rank, fragment in enumerate(fragments):
            size = len(fragment.text)
            if not fragment.text.strip():
                continue
            if used + size > MAX_REFERENCE_CHARS_PER_CONTROL:
                counts["skipped_by_control_cap"] += 1
                continue
            used += size
            kept.append(_Kept(check_index=check_index, rank=rank, fragment=fragment))
    return kept, counts


def _apply_size_cap(kept: list[_Kept]) -> tuple[list[_Kept], int]:
    """Descarta fragmentos enteros, de menor a mayor puntaje, hasta respetar
    `MAX_REFERENCE_CHARS`. Un puntaje ausente cuenta como el mas bajo; ante
    empate se descarta primero el de peor posicion del ultimo control."""
    total = sum(len(item.fragment.text) for item in kept)
    if total <= MAX_REFERENCE_CHARS:
        return kept, 0

    def drop_order(item: _Kept):
        score = item.fragment.score
        return (
            score is not None,
            score if score is not None else 0.0,
            -item.check_index,
            -item.rank,
        )

    dropped: set[tuple[int, int]] = set()
    for item in sorted(kept, key=drop_order):
        if total <= MAX_REFERENCE_CHARS:
            break
        dropped.add((item.check_index, item.rank))
        total -= len(item.fragment.text)
    remaining = [item for item in kept if (item.check_index, item.rank) not in dropped]
    return remaining, len(dropped)


def _neutralize(text: str) -> str:
    """Impide que el texto recuperado imite los delimitadores de la seccion."""
    return (
        text.replace(REFERENCE_SECTION_END, _OMITTED_DELIMITER)
        .replace(REFERENCE_SECTION_START, _OMITTED_DELIMITER)
        .replace(_CHECK_HEADER_PREFIX, "- check_id=")
    )


def _fragment_header(fragment: knowledge_retriever.RetrievedFragment) -> str:
    identifier = knowledge_retriever.source_identifier(fragment.source_uri)
    source = " ".join(identifier.split()) if identifier else "no informada"
    score = f"{fragment.score:.4f}" if fragment.score is not None else "no informado"
    return f"[fuente: {_neutralize(source)} | puntaje: {score}]"


def _render_prompt_section(checks: list[dict], kept: list[_Kept]) -> str:
    if not kept:
        return ""
    lines = [REFERENCE_SECTION_START]
    current_index = None
    for item in kept:
        if item.check_index != current_index:
            current_index = item.check_index
            lines.append(f"{_CHECK_HEADER_PREFIX}{checks[current_index].get('check_id')} ---")
        lines.append(_fragment_header(item.fragment))
        lines.append(_neutralize(item.fragment.text.strip()))
    lines.append(REFERENCE_SECTION_END)
    return "\n".join(lines)


def _references_by_check(checks: list[dict], kept: list[_Kept]) -> dict:
    """Referencias del manifest por `check_id`: origen, puntaje y tipo.

    `kind` es aditivo: `technical` para la documentacion propia y del
    fabricante, `normative` para el resto (ver `reference_kinds`). Se deduce
    de la clave del documento; no cambia que se recupera ni que llega al
    prompt.
    """
    references: dict[str, list[dict]] = {}
    for item in kept:
        score = item.fragment.score
        source = knowledge_retriever.source_identifier(item.fragment.source_uri)
        references.setdefault(str(checks[item.check_index].get("check_id")), []).append(
            {
                "source": source,
                "score": round(score, 4) if score is not None else None,
                "kind": reference_kinds.classify(source),
            }
        )
    return references


def collect(
    checks: list[dict],
    config: knowledge_retriever.RetrievalConfig,
    *,
    retrieve: Callable | None = None,
) -> ReferenceContext:
    """Recupera la referencia de cada control y arma la seccion del prompt y
    el bloque del manifest. Nunca levanta por un fallo de recuperacion y
    nunca modifica `checks`."""
    retrieve_fn = retrieve if retrieve is not None else knowledge_retriever.retrieve
    kept, counts = _retrieve_for_checks(checks, config, retrieve_fn)
    kept, dropped = _apply_size_cap(kept)
    references = _references_by_check(checks, kept)

    manifest_block = {
        "enabled": True,
        "knowledge_base_id": config.knowledge_base_id,
        "max_results": config.max_results,
        "filter": (
            {knowledge_retriever.FORTIOS_VERSION_METADATA_KEY: config.fortios_version}
            if config.fortios_version
            else None
        ),
        "controls_total": len(checks),
        "controls_with_references": len(references),
        "retrievals_attempted": counts["attempted"],
        "retrievals_failed": counts["failed"],
        "controls_skipped_by_call_cap": counts["skipped_by_call_cap"],
        "fragments_skipped_by_control_cap": counts["skipped_by_control_cap"],
        "fragments_dropped_by_size_cap": dropped,
        "references": references,
    }
    observability.log_event(
        "kb_references",
        **{key: value for key, value in manifest_block.items() if key != "references"},
    )
    return ReferenceContext(
        prompt_section=_render_prompt_section(checks, kept), manifest_block=manifest_block
    )
