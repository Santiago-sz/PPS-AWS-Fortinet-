"""
Recuperacion de fragmentos desde una Knowledge Base administrada de Amazon
Bedrock (operacion `Retrieve` de `bedrock-agent-runtime`).

Estado: base para un RAG vectorial, APAGADA por defecto. Ningun handler ni
`llm_client` importa este modulo todavia; incorporar los fragmentos al prompt
es un cambio posterior (modifica prompts y obliga a regrabar las fixtures de
evals). La recuperacion es ADITIVA: aporta contexto de apoyo y nunca
reemplaza el map/reduce completo sobre la normativa, que es lo que conserva
la trazabilidad por clausula.

Contrato:
  - `load_config()` lee `KNOWLEDGE_BASE_ID` y `KNOWLEDGE_BASE_MAX_RESULTS`.
    Id ausente o en blanco => recuperacion deshabilitada (`enabled=False`).
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

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

import observability

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_ID_ENV = "KNOWLEDGE_BASE_ID"
KNOWLEDGE_BASE_MAX_RESULTS_ENV = "KNOWLEDGE_BASE_MAX_RESULTS"

DEFAULT_MAX_RESULTS = 5

# Limites del modelo de servicio de botocore incluido en el venv del repo
# (botocore 1.43.123): botocore/data/bedrock-agent-runtime/2023-07-26/
# service-2.json.gz.
#   - Shape `KnowledgeBaseQueryTextString` (miembro `text` de
#     `KnowledgeBaseQuery`, campo `retrievalQuery`): min 0, max 20000.
#   - Shape `KnowledgeBaseVectorSearchConfigurationNumberOfResultsInteger`
#     (`numberOfResults`): min 1, max 100.
MAX_QUERY_CHARS = 20000
MIN_RESULTS = 1
MAX_RESULTS = 100

_CLIENT_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=30)

_client = None


class KnowledgeRetrievalError(Exception):
    """La llamada `Retrieve` fallo o la respuesta no tiene la forma esperada."""


@dataclass(frozen=True)
class RetrievalConfig:
    knowledge_base_id: str
    max_results: int

    @property
    def enabled(self) -> bool:
        """True solo si hay una Knowledge Base configurada."""
        return bool(self.knowledge_base_id)


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
    """
    knowledge_base_id = os.environ.get(KNOWLEDGE_BASE_ID_ENV, "").strip()
    raw_max_results = os.environ.get(KNOWLEDGE_BASE_MAX_RESULTS_ENV, "").strip()
    if not raw_max_results:
        return RetrievalConfig(knowledge_base_id=knowledge_base_id, max_results=DEFAULT_MAX_RESULTS)
    try:
        max_results = int(raw_max_results)
    except ValueError:
        raise ValueError(f"{KNOWLEDGE_BASE_MAX_RESULTS_ENV} must be an integer") from None
    if not MIN_RESULTS <= max_results <= MAX_RESULTS:
        raise ValueError(
            f"{KNOWLEDGE_BASE_MAX_RESULTS_ENV} must be between {MIN_RESULTS} and {MAX_RESULTS}"
        )
    return RetrievalConfig(knowledge_base_id=knowledge_base_id, max_results=max_results)


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


def build_request(query: str, *, knowledge_base_id: str, max_results: int) -> dict:
    """Arma el payload exacto de `Retrieve` -- separado para poder testearlo."""
    return {
        "knowledgeBaseId": knowledge_base_id,
        "retrievalQuery": {"text": query},
        "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": max_results}},
    }


def _validate_inputs(query: str, knowledge_base_id: str, max_results: int) -> None:
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
    client=None,
) -> list[RetrievedFragment]:
    """Una llamada sincronica a `Retrieve` sobre la Knowledge Base indicada.

    Devuelve los fragmentos con texto, en el orden que entrega el servicio;
    los resultados sin contenido textual se omiten.

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
    _validate_inputs(query, knowledge_base_id, max_results)
    kb_client = client or get_client()
    request = build_request(query, knowledge_base_id=knowledge_base_id, max_results=max_results)

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
