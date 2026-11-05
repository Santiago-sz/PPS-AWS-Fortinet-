"""
Analizador NIST CSF usando Claude a través de Amazon Bedrock (Converse).

Toma la data cruda del FortiGate, construye un prompt estructurado
y devuelve un análisis de seguridad mapeado a las 5 funciones del NIST CSF.

Flujo legacy (`handler.py`), conservado detrás del flag
`enable_legacy_nist_schedule`. El transporte vive en `bedrock_client`: no
hay API key ni endpoint HTTP acá — la autorización es IAM del rol Lambda.
"""

import json
import logging

import bedrock_client

logger = logging.getLogger(__name__)

# La API tiene un límite de tokens de entrada.
# Truncamos la data del FortiGate para no excederlo — 80k chars
# es suficiente para cubrir configuraciones de FortiGate medianos.
MAX_DATA_CHARS = 80_000

# Tope de tokens de salida (siempre explícito en la request a Bedrock).
MAX_OUTPUT_TOKENS = 4096

# Prompt del sistema: le dice al modelo qué rol cumple y en qué formato
# debe responder. Separarlo del prompt de usuario permite cachearlo en
# Bedrock (cachePoint) — ahorra tokens de entrada en cada ejecución.
SYSTEM_PROMPT = """Sos un experto en ciberseguridad especializado en evaluación de posturas de seguridad
bajo el framework NIST Cybersecurity Framework (CSF) 2.0.

Recibirás la configuración de un FortiGate exportada via REST API.
Tu tarea es analizar esa configuración y producir un reporte estructurado en JSON.

El JSON debe tener exactamente este esquema:
{
  "executive_summary": "string — resumen ejecutivo en 3-4 oraciones",
  "overall_score": número entre 1.0 y 5.0,
  "functions": {
    "GOVERN": {
      "score": número entre 1.0 y 5.0,
      "findings": ["lista de hallazgos concretos"],
      "recommendations": ["lista de recomendaciones priorizadas"]
    },
    "IDENTIFY": { ... mismo esquema ... },
    "PROTECT":  { ... mismo esquema ... },
    "DETECT":   { ... mismo esquema ... },
    "RESPOND":  { ... mismo esquema ... },
    "RECOVER":  { ... mismo esquema ... }
  },
  "critical_issues": ["lista de problemas críticos que requieren atención inmediata"],
  "quick_wins": ["lista de mejoras de bajo esfuerzo y alto impacto"]
}

Scoring:
1.0 = No implementado
2.0 = Parcialmente implementado
3.0 = Implementado pero sin hardening
4.0 = Bien implementado
5.0 = Implementado con mejores prácticas

Respondé SOLO con el JSON. Sin texto antes ni después. Sin markdown fences.
"""


def _build_user_prompt(fortigate_data: dict, device_info: dict) -> str:
    """
    Construye el prompt de usuario con la configuración del FortiGate.

    Serializa la data a JSON y la trunca si excede MAX_DATA_CHARS.
    La truncación es un safeguard — en la práctica las configuraciones
    de FortiGate medianas entran bien dentro del límite.
    """
    data_str = json.dumps(fortigate_data, indent=2, default=str)

    if len(data_str) > MAX_DATA_CHARS:
        logger.warning(
            "Data del FortiGate truncada: %d → %d chars",
            len(data_str),
            MAX_DATA_CHARS,
        )
        data_str = data_str[:MAX_DATA_CHARS] + "\n... [truncado por límite de tokens]"

    host = device_info.get("host", "desconocido")

    return f"""Analizá la siguiente configuración del FortiGate con host {host}
y generá el reporte NIST CSF 2.0 en el formato JSON especificado.

CONFIGURACIÓN DEL DISPOSITIVO:
{data_str}
"""


def analyze(fortigate_data: dict, device_info: dict) -> dict:
    """
    Llama al modelo vía Bedrock y devuelve el análisis NIST CSF como dict.

    Args:
        fortigate_data: dict con la data de todos los endpoints del FortiGate.
        device_info:    dict con metadatos del dispositivo (host, region, etc.).

    Returns:
        dict con el análisis estructurado según el esquema NIST CSF definido
        en SYSTEM_PROMPT. En caso de error devuelve un dict con 'error' —
        esta función nunca levanta excepciones.
    """
    model_id = bedrock_client.resolve_model_id()
    logger.info("Iniciando análisis — modelo Bedrock: %s", model_id)

    user_prompt = _build_user_prompt(fortigate_data, device_info)
    raw_text = ""

    try:
        result = bedrock_client.converse(
            SYSTEM_PROMPT,
            user_prompt,
            max_tokens=MAX_OUTPUT_TOKENS,
            model_id=model_id,
            stage="nist",
        )
        raw_text = result.text

        # Logueamos el uso de tokens para monitorear costos en CloudWatch
        logger.info(
            "Tokens — input: %s (cache_read: %s, cache_write: %s) | output: %s | %.0f ms",
            result.input_tokens,
            result.cache_read_tokens,
            result.cache_write_tokens,
            result.output_tokens,
            result.latency_ms,
        )

        # Parseamos el JSON que el modelo devolvió
        analysis = json.loads(raw_text)
        logger.info(
            "Análisis completo — score general: %s/5.0",
            analysis.get("overall_score"),
        )
        return analysis

    except bedrock_client.BedrockCallError as e:
        logger.error("Error llamando a Bedrock: %s", e)
        return {"error": "bedrock_error", "detail": str(e)}

    except json.JSONDecodeError as e:
        # El modelo respondió algo que no es JSON válido — raro pero posible
        logger.error("El modelo no devolvió JSON válido: %s", str(e))
        return {"error": "json_parse_error", "raw": raw_text}

    except Exception as e:
        logger.error("Error inesperado en análisis: %s", str(e))
        return {"error": "unexpected", "detail": str(e)}
