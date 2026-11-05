"""
Transporte LLM sobre Amazon Bedrock (API Converse).

Unico punto del pipeline que habla con el modelo. Reemplaza la llamada HTTP
cruda a api.anthropic.com: la autenticacion pasa a ser IAM (el rol de la
Lambda necesita `bedrock:InvokeModel`), por lo que ya no existe ninguna API
key que leer de Secrets Manager.

Contrato:
  - El modelo se resuelve con `resolve_model_id()`: variable de entorno
    `BEDROCK_MODEL_ID` o, en su defecto, `DEFAULT_MODEL_ID` (un perfil de
    inferencia cross-region; verificar disponibilidad en la cuenta con
    `aws bedrock list-inference-profiles`).
  - `converse()` envia SIEMPRE `maxTokens` explicito, un unico mensaje de
    usuario y el system prompt seguido de un `cachePoint` (prompt caching
    del lado de Bedrock -- el system prompt es identico entre llamadas de
    una misma fase, asi que es el prefijo cacheable natural).
  - Cualquier fallo (SDK, servicio, forma de respuesta inesperada) se
    traduce a `BedrockCallError`; el caller decide como reportarlo.
  - Cada llamada emite un evento `llm_call` y tres metricas EMF via
    `observability` (tokens de entrada/salida y latencia).

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

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
MODEL_ID_ENV = "BEDROCK_MODEL_ID"

_CLIENT_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=120)

_client = None


class BedrockCallError(Exception):
    """La llamada a Bedrock fallo o la respuesta no tiene la forma esperada."""


@dataclass(frozen=True)
class ConverseResult:
    text: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    latency_ms: float
    model_id: str
    stop_reason: str | None


def resolve_model_id() -> str:
    """Model id efectivo: `BEDROCK_MODEL_ID` si esta definido, si no el default."""
    return os.environ.get(MODEL_ID_ENV, "").strip() or DEFAULT_MODEL_ID


def get_client():
    """Cliente `bedrock-runtime` cacheado a nivel de modulo (creacion perezosa)."""
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", config=_CLIENT_CONFIG)
    return _client


def reset_client() -> None:
    """Descarta el cliente cacheado (util en tests o tras cambiar credenciales)."""
    global _client
    _client = None


def build_request(system_prompt: str, user_prompt: str, *, max_tokens: int, model_id: str) -> dict:
    """Arma el payload exacto de `Converse` -- separado para poder testearlo."""
    return {
        "modelId": model_id,
        "system": [{"text": system_prompt}, {"cachePoint": {"type": "default"}}],
        "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
        "inferenceConfig": {"maxTokens": max_tokens},
    }


def _extract_text(response: dict) -> str:
    blocks = response["output"]["message"]["content"]
    texts = [b["text"] for b in blocks if isinstance(b, dict) and "text" in b]
    if not texts:
        raise BedrockCallError("unexpected response shape: no text blocks in output")
    return "".join(texts).strip()


def _build_result(response: dict, *, model_id: str, measured_latency_ms: float) -> ConverseResult:
    text = _extract_text(response)
    usage = response.get("usage") or {}
    metrics = response.get("metrics") or {}
    latency = metrics.get("latencyMs")
    return ConverseResult(
        text=text,
        input_tokens=int(usage.get("inputTokens", 0) or 0),
        output_tokens=int(usage.get("outputTokens", 0) or 0),
        cache_read_tokens=int(usage.get("cacheReadInputTokens", 0) or 0),
        cache_write_tokens=int(usage.get("cacheWriteInputTokens", 0) or 0),
        latency_ms=float(latency) if latency is not None else measured_latency_ms,
        model_id=model_id,
        stop_reason=response.get("stopReason"),
    )


def converse(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int,
    model_id: str | None = None,
    client=None,
    stage: str = "unspecified",
    attempt: int | None = None,
) -> ConverseResult:
    """Una llamada sincronica a Bedrock Converse.

    `stage`/`attempt` solo alimentan el evento de observabilidad (map |
    reduce | nist, numero de intento de la fase reduce); no cambian la
    request. Levanta `BedrockCallError` ante cualquier fallo.
    """
    resolved_model_id = model_id or resolve_model_id()
    bedrock = client or get_client()
    request = build_request(
        system_prompt, user_prompt, max_tokens=max_tokens, model_id=resolved_model_id
    )

    started = time.perf_counter()
    try:
        response = bedrock.converse(**request)
        result = _build_result(
            response,
            model_id=resolved_model_id,
            measured_latency_ms=(time.perf_counter() - started) * 1000.0,
        )
    except ClientError as e:
        error = e.response.get("Error", {})
        code = error.get("Code", "ClientError")
        message = error.get("Message", str(e))
        logger.error("Error de Bedrock (%s) en fase %s: %s", code, stage, message)
        _log_failed_call(stage, attempt, resolved_model_id, started, f"{code}: {message}")
        raise BedrockCallError(f"{code}: {message}") from e
    except BotoCoreError as e:
        logger.error("Error de red/SDK llamando a Bedrock en fase %s: %s", stage, e)
        _log_failed_call(stage, attempt, resolved_model_id, started, f"network/sdk error: {e}")
        raise BedrockCallError(f"network/sdk error: {e}") from e
    except BedrockCallError as e:
        _log_failed_call(stage, attempt, resolved_model_id, started, str(e))
        raise
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.error("Respuesta de Bedrock con forma inesperada en fase %s: %r", stage, e)
        _log_failed_call(stage, attempt, resolved_model_id, started, f"unexpected shape: {e!r}")
        raise BedrockCallError(f"unexpected response shape: {e!r}") from e

    observability.log_event(
        "llm_call",
        stage=stage,
        attempt=attempt,
        model_id=result.model_id,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_read_tokens=result.cache_read_tokens,
        cache_write_tokens=result.cache_write_tokens,
        latency_ms=round(result.latency_ms, 1),
        stop_reason=result.stop_reason,
    )
    dimensions = {"Stage": stage}
    observability.emit_metric("LlmInputTokens", result.input_tokens, dimensions=dimensions)
    observability.emit_metric("LlmOutputTokens", result.output_tokens, dimensions=dimensions)
    observability.emit_metric(
        "LlmLatencyMs", round(result.latency_ms, 1), unit="Milliseconds", dimensions=dimensions
    )
    return result


def _log_failed_call(
    stage: str, attempt: int | None, model_id: str, started: float, error: str
) -> None:
    observability.log_event(
        "llm_call",
        stage=stage,
        attempt=attempt,
        model_id=model_id,
        latency_ms=round((time.perf_counter() - started) * 1000.0, 1),
        error=error,
    )
