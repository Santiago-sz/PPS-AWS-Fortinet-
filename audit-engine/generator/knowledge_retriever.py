"""
Recuperacion de fragmentos desde una Knowledge Base administrada de Amazon
Bedrock (operacion `Retrieve` de `bedrock-agent-runtime`).

Estado: base para un RAG vectorial, APAGADA por defecto. Lo usa
`reference_context` (una consulta por control, entre map y reduce) solo
cuando `handler_generator` encuentra `KNOWLEDGE_BASE_ID` configurado; las
evals de recuperacion (`evals/retrieval_eval.py`) lo usan en modo live. La
recuperacion es ADITIVA: aporta contexto de apoyo y nunca reemplaza el
map/reduce completo sobre la normativa, que es lo que conserva la
trazabilidad por clausula.

Contrato:
  - `load_config()` lee `KNOWLEDGE_BASE_ID`, `KNOWLEDGE_BASE_MAX_RESULTS` y
    `KNOWLEDGE_BASE_FORTIOS_VERSION`. Id ausente o en blanco => recuperacion
    deshabilitada (`enabled=False`). Version en blanco => sin filtro.
  - `build_request()` es el UNICO lugar donde se arma la peticion; la
    configuracion de busqueda usada se elige con `SEARCH_CONFIGURATION_KEY`.
  - `retrieve()` hace UNA llamada `Retrieve` y devuelve `RetrievedFragment`.
    No pagina (`nextToken` se ignora): `max_results` acota el resultado.
  - Entradas invalidas levantan `ValueError` ANTES de llamar al servicio.
  - Cualquier fallo del SDK, del servicio o de la forma de la respuesta se
    traduce a `KnowledgeRetrievalError`, cuyo mensaje lleva solo el codigo o
    el tipo del error: nunca la consulta, el mensaje del servicio ni texto
    de documentos.
  - Cada llamada emite exactamente un evento `kb_retrieve` via
    `observability` (id de la base, cantidad de resultados, latencia y
    estado). Ni la consulta ni el texto recuperado se registran.

Autorizacion: IAM. El rol del generador recibe `bedrock:Retrieve` sobre la
base configurada solo cuando `knowledge_base_id` no esta vacio (ver
`infrastructure/pipeline/iam.tf`). El executor no importa este modulo ni
tiene permisos de Bedrock.

El cliente boto3 se crea de forma perezosa y se cachea a nivel de modulo
(`get_client`), con reintentos adaptativos del SDK para throttling.
"""

import logging
import os
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

import observability

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_ID_ENV = "KNOWLEDGE_BASE_ID"
KNOWLEDGE_BASE_MAX_RESULTS_ENV = "KNOWLEDGE_BASE_MAX_RESULTS"
KNOWLEDGE_BASE_FORTIOS_VERSION_ENV = "KNOWLEDGE_BASE_FORTIOS_VERSION"

# Clave de metadatos con la que se etiquetan los documentos de la base. El
# filtro opcional compara por igualdad contra esta clave.
FORTIOS_VERSION_METADATA_KEY = "fortios_version"

DEFAULT_MAX_RESULTS = 5

# Limites del modelo de servicio de botocore incluido en el venv del repo
# (botocore 1.43.123): botocore/data/bedrock-agent-runtime/2023-07-26/
# service-2.json.gz.
#   - Shape `KnowledgeBaseQueryTextString` (miembro `text` de
#     `KnowledgeBaseQuery`, campo `retrievalQuery`): min 0, max 20000.
#   - Shape `KnowledgeBaseVectorSearchConfigurationNumberOfResultsInteger`
#     (`numberOfResults`): min 1, max 100.
#   - Shape `FilterKey` (miembro `key` de `FilterAttribute`): min 1, max 100.
MAX_QUERY_CHARS = 20000
MIN_RESULTS = 1
MAX_RESULTS = 100
MAX_FILTER_KEY_CHARS = 100

# Configuracion de busqueda que se envia en `retrievalConfiguration`. El
# modelo de servicio (shape `KnowledgeBaseRetrievalConfiguration`, estructura
# comun, no union) declara dos miembros opcionales:
#   - "vectorSearchConfiguration"  (`KnowledgeBaseVectorSearchConfiguration`)
#   - "managedSearchConfiguration" (`ManagedSearchConfiguration`)
# Ambos aceptan `numberOfResults` (1..100) y `filter` (`RetrievalFilter`), que
# es todo lo que usa este modulo. El modelo no indica cual corresponde a cada
# tipo de base; lo define el servicio.
#
# VERIFICADO contra la base desplegada el 2026-11-18: una Knowledge Base de
# tipo MANAGED rechaza "vectorSearchConfiguration" con `ValidationException`
# ("vectorSearchConfiguration is not supported for managed knowledge bases.
# Use managedSearchConfiguration instead.") y acepta
# `{"managedSearchConfiguration": {"numberOfResults": 3}}`.
#
# SIN VERIFICAR contra el servicio: el miembro `filter` dentro de
# `managedSearchConfiguration`. El modelo de servicio lo declara
# (`ManagedSearchConfiguration.filter` -> `RetrievalFilter`), pero no se probo
# ninguna consulta con filtro.
#
# Para una base con almacen vectorial propio, cambiar SOLO esta linea por
# "vectorSearchConfiguration".
SEARCH_CONFIGURATION_KEY = "managedSearchConfiguration"

_CLIENT_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=30)

_client = None


class KnowledgeRetrievalError(Exception):
    """La llamada `Retrieve` fallo o la respuesta no tiene la forma esperada."""


def source_identifier(uri: str | None) -> str | None:
    """Identificador de origen sin el nombre del bucket: la clave del objeto.

    El servicio devuelve el origen como URL HTTPS
    (`https://<bucket>.s3.amazonaws.com/<clave>`, forma observada el
    2026-11-18) y el nombre del bucket incluye el id de cuenta. Todo lo que
    sale de la recuperacion hacia prompts, manifest, reportes, eventos o
    fixtures debe usar este identificador, nunca el URI completo.

    Acepta tambien `s3://<bucket>/<clave>`, la forma path-style
    (`https://s3.<region>.amazonaws.com/<bucket>/<clave>`) y una clave ya
    suelta. De cualquier otra URL conserva solo la ruta. Devuelve None si no
    queda una clave.
    """
    if not isinstance(uri, str) or not uri.strip():
        return None
    parsed = urlparse(uri.strip())
    if not parsed.scheme:
        return uri.strip()
    key = parsed.path.lstrip("/")
    host = (parsed.hostname or "").lower()
    path_style = host.endswith("amazonaws.com") and (host.startswith(("s3.", "s3-")))
    if parsed.scheme in ("http", "https") and path_style:
        # El primer segmento de la ruta es el bucket.
        key = key.partition("/")[2]
    return unquote(key) or None


@dataclass(frozen=True)
class RetrievalConfig:
    knowledge_base_id: str
    max_results: int
    fortios_version: str = ""

    @property
    def enabled(self) -> bool:
        """True solo si hay una Knowledge Base configurada."""
        return bool(self.knowledge_base_id)

    @property
    def metadata_filter(self) -> dict | None:
        """Filtro `equals` sobre `fortios_version`, o None si no hay version."""
        if not self.fortios_version:
            return None
        return equals_filter(FORTIOS_VERSION_METADATA_KEY, self.fortios_version)


@dataclass(frozen=True)
class RetrievedFragment:
    text: str
    source_uri: str | None
    score: float | None


def load_config() -> RetrievalConfig:
    """Configuracion efectiva leida del entorno.

    `KNOWLEDGE_BASE_ID` ausente o en blanco deja la recuperacion
    deshabilitada. `KNOWLEDGE_BASE_MAX_RESULTS` ausente o en blanco usa
    `DEFAULT_MAX_RESULTS`; un valor no entero o fuera de 1..100 levanta
    `ValueError` (falla explicita en vez de corregir en silencio).
    `KNOWLEDGE_BASE_FORTIOS_VERSION` ausente o en blanco deja la consulta
    sin filtro de metadatos.
    """
    knowledge_base_id = os.environ.get(KNOWLEDGE_BASE_ID_ENV, "").strip()
    fortios_version = os.environ.get(KNOWLEDGE_BASE_FORTIOS_VERSION_ENV, "").strip()
    raw_max_results = os.environ.get(KNOWLEDGE_BASE_MAX_RESULTS_ENV, "").strip()
    max_results = DEFAULT_MAX_RESULTS
    if raw_max_results:
        try:
            max_results = int(raw_max_results)
        except ValueError:
            raise ValueError(f"{KNOWLEDGE_BASE_MAX_RESULTS_ENV} must be an integer") from None
        if not MIN_RESULTS <= max_results <= MAX_RESULTS:
            raise ValueError(
                f"{KNOWLEDGE_BASE_MAX_RESULTS_ENV} must be between {MIN_RESULTS} and {MAX_RESULTS}"
            )
    return RetrievalConfig(
        knowledge_base_id=knowledge_base_id,
        max_results=max_results,
        fortios_version=fortios_version,
    )


def get_client():
    """Cliente `bedrock-agent-runtime` cacheado a nivel de modulo (creacion perezosa)."""
    global _client
    if _client is None:
        _client = boto3.client("bedrock-agent-runtime", config=_CLIENT_CONFIG)
    return _client


def reset_client() -> None:
    """Descarta el cliente cacheado (util en tests o tras cambiar credenciales)."""
    global _client
    _client = None


def equals_filter(key: str, value: str) -> dict:
    """Filtro de metadatos por igualdad (`RetrievalFilter.equals`, cuyo valor
    es un `FilterAttribute` con `key` y `value` obligatorios)."""
    if not isinstance(key, str) or not 1 <= len(key) <= MAX_FILTER_KEY_CHARS:
        raise ValueError(f"filter key must have between 1 and {MAX_FILTER_KEY_CHARS} characters")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("filter value must not be empty")
    return {"equals": {"key": key, "value": value}}


def build_request(
    query: str,
    *,
    knowledge_base_id: str,
    max_results: int,
    metadata_filter: dict | None = None,
) -> dict:
    """Arma el payload exacto de `Retrieve` -- unico punto de construccion.

    La configuracion de busqueda se ubica bajo `SEARCH_CONFIGURATION_KEY`;
    `metadata_filter` (un `RetrievalFilter`) solo se envia si no es None.
    """
    search_configuration: dict = {"numberOfResults": max_results}
    if metadata_filter is not None:
        search_configuration["filter"] = metadata_filter
    return {
        "knowledgeBaseId": knowledge_base_id,
        "retrievalQuery": {"text": query},
        "retrievalConfiguration": {SEARCH_CONFIGURATION_KEY: search_configuration},
    }


def _validate_inputs(
    query: str, knowledge_base_id: str, max_results: int, metadata_filter: dict | None
) -> None:
    # Los mensajes describen la regla incumplida, nunca el valor recibido.
    if not isinstance(knowledge_base_id, str) or not knowledge_base_id.strip():
        raise ValueError("knowledge_base_id must not be empty")
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise ValueError("max_results must be an integer")
    if not MIN_RESULTS <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results must be between {MIN_RESULTS} and {MAX_RESULTS}")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be empty")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query exceeds the Retrieve limit of {MAX_QUERY_CHARS} characters")
    if metadata_filter is not None and (
        not isinstance(metadata_filter, dict) or not metadata_filter
    ):
        raise ValueError("metadata_filter must be a non-empty filter object")


def _to_fragments(response: dict) -> list[RetrievedFragment]:
    fragments = []
    for result in response["retrievalResults"]:
        text = result["content"].get("text")
        if not isinstance(text, str) or not text:
            # Contenido no textual (imagen, audio, fila): no aporta al prompt.
            continue
        location = result.get("location") or {}
        uri = (location.get("s3Location") or {}).get("uri")
        score = result.get("score")
        fragments.append(
            RetrievedFragment(
                text=text,
                source_uri=uri if isinstance(uri, str) and uri else None,
                score=float(score) if score is not None else None,
            )
        )
    return fragments


def retrieve(
    query: str,
    *,
    knowledge_base_id: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    metadata_filter: dict | None = None,
    client=None,
) -> list[RetrievedFragment]:
    """Una llamada sincronica a `Retrieve` sobre la Knowledge Base indicada.

    Devuelve los fragmentos con texto, en el orden que entrega el servicio;
    los resultados sin contenido textual se omiten. `metadata_filter`
    (opcional) restringe la busqueda por metadatos; ver `equals_filter`.

    Validacion de la consulta: una consulta vacia o solo con espacios, o que
    supere `MAX_QUERY_CHARS`, levanta `ValueError` sin llamar al servicio.
    Se eligio RECHAZAR y no recortar: una consulta recortada en silencio
    recupera contexto para un texto distinto del que el caller cree haber
    consultado, y el limite del servicio (20000 caracteres) queda muy por
    encima de una consulta de busqueda razonable. La regla 7 de AGENTS.md
    ("nunca truncar contenido de la normativa") se refiere al texto de la
    normativa enviado al modelo, no a esta consulta; aun asi el caller debe
    construir consultas acotadas y no pasar la normativa completa como
    consulta.

    Levanta `KnowledgeRetrievalError` ante cualquier fallo del SDK, del
    servicio o de la forma de la respuesta.
    """
    _validate_inputs(query, knowledge_base_id, max_results, metadata_filter)
    kb_client = client or get_client()
    request = build_request(
        query,
        knowledge_base_id=knowledge_base_id,
        max_results=max_results,
        metadata_filter=metadata_filter,
    )

    started = time.perf_counter()
    try:
        fragments = _to_fragments(kb_client.retrieve(**request))
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code") or "ClientError"
        # `from None`: el mensaje del servicio (que puede citar la consulta)
        # no debe quedar encadenado en el traceback de quien reciba el error.
        raise _failed_call(knowledge_base_id, max_results, started, code) from None
    except BotoCoreError as e:
        raise _failed_call(knowledge_base_id, max_results, started, type(e).__name__) from None
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as e:
        error = f"unexpected response shape ({type(e).__name__})"
        raise _failed_call(knowledge_base_id, max_results, started, error) from None

    observability.log_event(
        "kb_retrieve",
        knowledge_base_id=knowledge_base_id,
        max_results=max_results,
        results=len(fragments),
        latency_ms=_elapsed_ms(started),
        status="ok",
    )
    return fragments


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)


def _failed_call(
    knowledge_base_id: str, max_results: int, started: float, error: str
) -> KnowledgeRetrievalError:
    """Registra el fallo (solo codigo o tipo) y devuelve la excepcion a levantar."""
    logger.error("Error de Knowledge Base (%s) en la base %s", error, knowledge_base_id)
    observability.log_event(
        "kb_retrieve",
        knowledge_base_id=knowledge_base_id,
        max_results=max_results,
        results=0,
        latency_ms=_elapsed_ms(started),
        status="error",
        error=error,
    )
    return KnowledgeRetrievalError(error)
