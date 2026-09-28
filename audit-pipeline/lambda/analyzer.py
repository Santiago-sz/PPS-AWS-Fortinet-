"""
Analizador NIST CSF usando Claude API.

Toma la data cruda del FortiGate, construye un prompt estructurado
y devuelve un análisis de seguridad mapeado a las 5 funciones del NIST CSF.
"""

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# Modelo a usar. claude-3-5-sonnet es el balance óptimo entre
# capacidad de análisis y costo por token para este workload.
CLAUDE_MODEL = "claude-sonnet-4-6"

# La API de Claude tiene un límite de tokens de entrada.
# Truncamos la data del FortiGate para no excederlo — 80k chars
# es suficiente para cubrir configuraciones de FortiGate medianos.
MAX_DATA_CHARS = 80_000

# Prompt del sistema: le dice a Claude qué rol cumple y en qué formato
# debe responder. Separarlo del prompt de usuario permite cachearlo
# en la API de Claude (Prompt Caching) — ahorra tokens en cada ejecución.
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


def analyze(fortigate_data: dict, device_info: dict, claude_api_key: str) -> dict:
    """
    Llama a Claude API y devuelve el análisis NIST CSF como dict.

    Args:
        fortigate_data: dict con la data de todos los endpoints del FortiGate.
        device_info:    dict con metadatos del dispositivo (host, region, etc.).
        claude_api_key: API key de Anthropic, leída desde Secrets Manager.

    Returns:
        dict con el análisis estructurado según el esquema NIST CSF definido
        en SYSTEM_PROMPT. En caso de error devuelve un dict con 'error'.
    """
    logger.info("Iniciando análisis Claude — modelo: %s", CLAUDE_MODEL)

    user_prompt = _build_user_prompt(fortigate_data, device_info)

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 4096,
        # system como lista para habilitar Prompt Caching en futuras versiones.
        # cache_control type "ephemeral" cachea el system prompt por 5 minutos —
        # en ejecuciones frecuentes reduce el costo de tokens de entrada ~90%.
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_prompt}],
    }

    body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": claude_api_key,
            "anthropic-version": "2023-06-01",
            # Header requerido para activar Prompt Caching
            "anthropic-beta": "prompt-caching-2024-07-31",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            response_body = json.loads(resp.read().decode("utf-8"))

        # La respuesta de Claude viene en response.content[0].text
        raw_text = response_body["content"][0]["text"].strip()

        # Logueamos el uso de tokens para monitorear costos en CloudWatch
        usage = response_body.get("usage", {})
        logger.info(
            "Tokens — input: %s (cache_read: %s, cache_create: %s) | output: %s",
            usage.get("input_tokens"),
            usage.get("cache_read_input_tokens", 0),
            usage.get("cache_creation_input_tokens", 0),
            usage.get("output_tokens"),
        )

        # Parseamos el JSON que Claude devolvió
        analysis = json.loads(raw_text)
        logger.info(
            "Análisis completo — score general: %s/5.0",
            analysis.get("overall_score"),
        )
        return analysis

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        logger.error("Error HTTP %s en Claude API: %s", e.code, error_body)
        return {"error": f"HTTP {e.code}", "detail": error_body}

    except json.JSONDecodeError as e:
        # Claude respondió algo que no es JSON válido — raro pero posible
        logger.error("Claude no devolvió JSON válido: %s", str(e))
        return {"error": "json_parse_error", "raw": raw_text if "raw_text" in dir() else ""}

    except Exception as e:
        logger.error("Error inesperado en análisis: %s", str(e))
        return {"error": "unexpected", "detail": str(e)}
