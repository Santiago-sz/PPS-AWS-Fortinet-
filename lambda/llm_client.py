"""
Cliente Claude para generacion de scripts de auditoria policy-driven.

Adaptado de analyzer.py (misma llamada HTTP cruda via urllib, sin
dependencias externas), pero con dos diferencias deliberadas:

  1. Dos fases separadas (map/reduce), no un unico prompt monolitico:
       map:    chunk group -> PolicyCheck[]   (uno o mas grupos, bound por
               MAX_MAP_CALLS -- ver design.md Decision #3)
       reduce: PolicyCheck[] -> script.py     (un unico prompt, con ciclo
               de reintento acotado por MAX_GENERATION_ATTEMPTS)

  2. NUNCA trunca contenido. analyzer.py corta el JSON serializado a
     MAX_DATA_CHARS con un slice duro (ver `_build_user_prompt` alli). Este
     modulo jamas hace eso: si el contenido no entra en el presupuesto de
     una unica llamada de map, se generan MAS grupos (mas llamadas), nunca
     se corta el texto de un chunk. Si el numero de grupos resultante
     excede MAX_MAP_CALLS, se falla explicitamente (`MapCallBudgetExceededError`)
     en vez de forzar menos grupos mas grandes.

Contrato de PolicyCheck (design.md, Interfaces):
    PolicyCheck = {"check_id","title","clause_ref","endpoints":[...],
                   "severity","intent"}

El `check_id` es asignado ACA (no por Claude) despues de recolectar los
checks de TODOS los grupos de map, para garantizar unicidad global sin
depender de que cada llamada independiente coordine IDs entre si.

El ciclo de reintento (reduce) reenvia, en caso de fallo de
`script_validator.validate()`, el prompt original + el script anterior +
un feedback puntual derivado del PRIMER error de la validacion:
`{attempt, failure_kind, rule_id, message, line, col, snippet}` (ver
design.md "Retry feedback"). Agotado `MAX_GENERATION_ATTEMPTS` sin un
script valido, se devuelve `status: "generation_failed"` -- nunca se
ejecuta ni se ofrece un script parcial/invalido.
"""

import json
import logging
import urllib.error
import urllib.request

import script_validator

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"

# Cantidad maxima de llamadas de map permitidas para cubrir TODOS los
# grupos de chunks de una politica. Si agrupar por presupuesto de prompt
# arroja mas grupos que esto, se falla explicitamente -- nunca se combinan
# grupos a la fuerza (eso equivaldria a truncar contenido).
MAX_MAP_CALLS = 12

# Presupuesto de caracteres por grupo de map (una llamada a Claude por
# grupo). Estimado inicial -- calibrar contra una normativa real en el
# primer E2E run (ver design.md Open Questions).
MAP_GROUP_MAX_CHARS = 12_000

# Reintentos acotados de la fase reduce ante script invalido.
MAX_GENERATION_ATTEMPTS = 3


class ClaudeCallError(Exception):
    """La llamada HTTP a la API de Claude fallo o la respuesta es inutilizable.

    A diferencia de analyzer.py (que devuelve un dict `{"error": ...}` y
    sigue), este modulo falla explicitamente -- el caller (generator
    orchestration, fuera de alcance en esta fase) decide como reportarlo,
    nunca se sigue con un resultado parcial/silencioso.
    """


class MapResponseParseError(Exception):
    """La respuesta de Claude para un grupo de map no es JSON valido."""


class MapCallBudgetExceededError(Exception):
    """La politica requiere mas llamadas de map que MAX_MAP_CALLS.

    Se levanta ANTES de hacer ninguna llamada HTTP -- fallar rapido y
    explicito, nunca combinar grupos a la fuerza para entrar en el
    presupuesto (eso seria una forma de truncar contenido en silencio).
    """


MAP_SYSTEM_PROMPT = """Sos un experto en ciberseguridad y cumplimiento normativo.

Vas a recibir uno o mas fragmentos ("chunks") de una politica/normativa de
seguridad, junto con el catalogo de endpoints de FortiGate disponibles para
verificacion automatica.

Tu tarea es identificar, dentro de ESTE fragmento unicamente, los controles
que:
  (a) esten explicitamente exigidos por el texto, y
  (b) sean verificables consultando alguno de los endpoints listados.

NO inventes controles que el texto no exige. NO generes controles
genericos de "buenas practicas" que no esten citados textualmente. Si este
fragmento no contiene ningun control verificable con los endpoints dados,
devolve una lista vacia -- eso es una respuesta valida y esperada, NO un
error.

Respondé SOLO con JSON, sin texto antes ni despues, sin markdown fences,
con exactamente este esquema:
{
  "checks": [
    {
      "title": "string breve describiendo el control",
      "clause_ref": {
        "chunk_id": "el chunk_id exacto de donde sale este control",
        "heading_path": ["lista de headings, tal cual se te dio"],
        "page": numero de pagina o null,
        "quote": "cita textual EXACTA del fragmento que exige este control"
      },
      "endpoints": ["lista de endpoint labels del catalogo dado, los que hagan falta consultar"],
      "severity": "low" | "medium" | "high" | "critical",
      "intent": "string breve: que se espera verificar y por que"
    }
  ]
}
"""

REDUCE_SYSTEM_PROMPT = """Sos un generador de scripts Python de auditoria de seguridad.

Vas a recibir una lista de controles (PolicyCheck) y el catalogo de
endpoints de FortiGate disponibles. Tu tarea es escribir UN script Python
que audite CADA control de la lista contra los datos reales del FortiGate.

El script se ejecuta en un sandbox extremadamente restringido. Reglas
ABSOLUTAS -- violar cualquiera de estas hace que el script sea rechazado:

  - Namespace disponible: SOLO `fgt`, `report`, y estos nombres seguros:
    len str int float bool list dict set tuple sorted any all min max sum
    enumerate zip range isinstance abs round
  - `fgt.get(endpoint_key)` -- endpoint_key DEBE ser un string literal que
    exista en el catalogo de endpoints dado. Solo lectura, nunca escritura.
  - `fgt.endpoints()` -- lista el catalogo disponible.
  - `report.finding(check_id, status, evidence, endpoints_used=None)` --
    status DEBE ser uno de: "pass", "fail", "not_applicable", "indeterminate".
    check_id DEBE ser un string literal.
  - `report.note(check_id, message)` -- anotacion suplementaria, no
    reemplaza a `finding`.
  - DEBES llamar `report.finding(...)` EXACTAMENTE UNA VEZ por cada
    check_id de la lista dada -- cobertura completa es obligatoria.
  - PROHIBIDO (rechazo inmediato): import, class, lambda, while, try,
    raise, with, global, nonlocal, delete, yield, await, async, cualquier
    identificador que contenga "__", y los nombres getattr, setattr,
    delattr, eval, exec, compile, open, input, globals, locals, vars, dir,
    type, super, __import__, help, breakpoint, memoryview.
  - PERMITIDO: def, return, asignaciones, if/elif/else, for, comprehensions,
    operadores aritmeticos/booleanos/de comparacion, f-strings.
  - Maximo 4000 nodos AST, anidamiento maximo 3 niveles (def/if/for).

Respondé SOLO con el codigo Python del script. Sin explicaciones antes ni
despues. Sin markdown fences (nada de ```python ni ```).
"""


def _call_claude(system_prompt: str, user_prompt: str, claude_api_key: str, max_tokens: int) -> str:
    """Llama a la API de Claude y devuelve el texto crudo de la respuesta.

    A diferencia de analyzer.analyze(), nunca devuelve un dict de error --
    levanta ClaudeCallError explicitamente en cualquier falla (HTTP, red,
    o forma de respuesta inesperada).
    """
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": [
            {
                "type": "text",
                "text": system_prompt,
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
            "anthropic-beta": "prompt-caching-2024-07-31",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            response_body = json.loads(resp.read().decode("utf-8"))
        return response_body["content"][0]["text"].strip()

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        logger.error("Error HTTP %s en Claude API: %s", e.code, error_body)
        raise ClaudeCallError(f"HTTP {e.code}: {error_body}") from e

    except urllib.error.URLError as e:
        logger.error("Error de red llamando a Claude API: %s", e.reason)
        raise ClaudeCallError(f"network error: {e.reason}") from e

    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.error("Respuesta de Claude con forma inesperada: %s", str(e))
        raise ClaudeCallError(f"unexpected response shape: {e}") from e


def group_chunks_for_map(
    chunks: list[dict], max_group_chars: int = MAP_GROUP_MAX_CHARS
) -> list[list[dict]]:
    """Agrupa `chunks` (ya producidos por chunker.chunk) en grupos, uno por
    llamada de map, respetando `max_group_chars` sin partir NUNCA un chunk.

    Empaquetado greedy: agrega chunks consecutivos a un grupo mientras no
    se exceda el presupuesto; un chunk que por si solo excede el
    presupuesto se convierte en su propio grupo (nunca se lo divide --
    eso lo hace chunker.py, no esta capa).
    """
    groups: list[list[dict]] = []
    current: list[dict] = []
    current_len = 0

    for c in chunks:
        text_len = len(c["text"])
        if current and current_len + text_len > max_group_chars:
            groups.append(current)
            current = []
            current_len = 0
        current.append(c)
        current_len += text_len

    if current:
        groups.append(current)

    return groups


def _build_map_user_prompt(group: list[dict], endpoint_catalog: list[str]) -> str:
    catalog_str = ", ".join(endpoint_catalog)
    parts = [f"CATALOGO DE ENDPOINTS DISPONIBLES: {catalog_str}", "", "FRAGMENTOS:"]

    for chunk_obj in group:
        heading = " > ".join(chunk_obj["heading_path"]) or "(sin heading)"
        page = chunk_obj.get("page")
        parts.append(
            f"\n--- chunk_id={chunk_obj['chunk_id']} | heading_path={heading} | page={page} ---"
        )
        parts.append(chunk_obj["text"])

    return "\n".join(parts)


def _assign_check_ids(raw_checks: list[dict]) -> list[dict]:
    assigned = []
    for i, check in enumerate(raw_checks, start=1):
        assigned.append({**check, "check_id": f"chk-{i:04d}"})
    return assigned


def _map_chunk_group(
    group: list[dict], endpoint_catalog: list[str], claude_api_key: str
) -> list[dict]:
    user_prompt = _build_map_user_prompt(group, endpoint_catalog)
    raw_text = _call_claude(MAP_SYSTEM_PROMPT, user_prompt, claude_api_key, max_tokens=4096)

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise MapResponseParseError(f"Claude map response is not valid JSON: {e}") from e

    return parsed.get("checks") or []


def map_chunks_to_checks(
    chunks: list[dict],
    endpoint_catalog: list[str],
    claude_api_key: str,
    max_map_calls: int = MAX_MAP_CALLS,
    max_group_chars: int = MAP_GROUP_MAX_CHARS,
) -> list[dict]:
    """Fase map: chunk group -> PolicyCheck[], acumulado sobre todos los grupos.

    Levanta MapCallBudgetExceededError SIN hacer ninguna llamada HTTP si la
    politica requiere mas grupos que `max_map_calls` -- fail-fast, nunca
    silenciosamente combinar/truncar para entrar en el presupuesto.
    """
    groups = group_chunks_for_map(chunks, max_group_chars=max_group_chars)

    if len(groups) > max_map_calls:
        raise MapCallBudgetExceededError(
            f"policy requires {len(groups)} map calls, exceeds MAX_MAP_CALLS={max_map_calls}"
        )

    raw_checks: list[dict] = []
    for group in groups:
        raw_checks.extend(_map_chunk_group(group, endpoint_catalog, claude_api_key))

    return _assign_check_ids(raw_checks)


def _snippet(source: str, line: int | None, context: int = 2) -> str | None:
    if line is None:
        return None
    lines = source.splitlines()
    start = max(0, line - 1 - context)
    end = min(len(lines), line + context)
    return "\n".join(lines[start:end])


def build_retry_feedback(
    attempt: int, previous_script: str, validation_result: script_validator.ValidationResult
) -> dict:
    """Construye el feedback puntual a partir del PRIMER error de la
    validacion fallida (design.md "Retry feedback")."""
    error = validation_result.errors[0]
    return {
        "attempt": attempt,
        "failure_kind": error.failure_kind,
        "rule_id": error.rule_id,
        "message": error.message,
        "line": error.line,
        "col": error.col,
        "snippet": _snippet(previous_script, error.line),
    }


def _build_reduce_user_prompt(
    checks: list[dict], endpoint_catalog: list[str], retry_feedback: dict | None
) -> str:
    catalog_str = ", ".join(endpoint_catalog)
    checks_view = [
        {
            "check_id": c["check_id"],
            "title": c.get("title"),
            "endpoints": c.get("endpoints", []),
            "severity": c.get("severity"),
            "intent": c.get("intent"),
        }
        for c in checks
    ]

    parts = [
        f"CATALOGO DE ENDPOINTS DISPONIBLES: {catalog_str}",
        "",
        "CONTROLES A AUDITAR (JSON):",
        json.dumps(checks_view, indent=2, ensure_ascii=False),
    ]

    if retry_feedback is not None:
        parts.extend(
            [
                "",
                f"EL SCRIPT ANTERIOR (intento {retry_feedback['attempt']}) FUE RECHAZADO.",
                f"failure_kind: {retry_feedback['failure_kind']}",
                f"rule_id: {retry_feedback['rule_id']}",
                f"message: {retry_feedback['message']}",
                f"line: {retry_feedback['line']}",
                f"col: {retry_feedback['col']}",
            ]
        )
        if retry_feedback["snippet"]:
            parts.append(f"snippet:\n{retry_feedback['snippet']}")
        parts.extend(
            [
                "",
                "SCRIPT ANTERIOR (corregi SOLO el problema senalado, no reescribas todo):",
                retry_feedback.get("previous_script") or "",
            ]
        )

    return "\n".join(parts)


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines)
    return stripped


def reduce_checks_to_script(
    checks: list[dict],
    endpoint_catalog: list[str],
    claude_api_key: str,
    retry_feedback: dict | None = None,
) -> str:
    """Fase reduce: PolicyCheck[] -> script.py (una llamada a Claude)."""
    user_prompt = _build_reduce_user_prompt(checks, endpoint_catalog, retry_feedback)
    raw_text = _call_claude(REDUCE_SYSTEM_PROMPT, user_prompt, claude_api_key, max_tokens=4096)
    return _strip_code_fences(raw_text)


def generate_script_with_retries(
    checks: list[dict],
    endpoint_catalog: list[str],
    claude_api_key: str,
    max_attempts: int = MAX_GENERATION_ATTEMPTS,
) -> dict:
    """Ciclo reduce -> validate -> feedback -> retry, acotado por max_attempts.

    Retorna:
      {"status": "ok", "script": ..., "attempts": n, "checks": checks}
      {"status": "generation_failed", "attempts": max_attempts, "errors": [...]}
    """
    manifest = {"checks": checks}
    feedback: dict | None = None
    last_validation: script_validator.ValidationResult | None = None

    for attempt in range(1, max_attempts + 1):
        script = reduce_checks_to_script(
            checks, endpoint_catalog, claude_api_key, retry_feedback=feedback
        )
        validation = script_validator.validate(script, manifest)

        if validation.valid:
            return {"status": "ok", "script": script, "attempts": attempt, "checks": checks}

        last_validation = validation
        feedback = build_retry_feedback(attempt, script, validation)
        feedback["previous_script"] = script

    return {
        "status": "generation_failed",
        "attempts": max_attempts,
        "errors": [
            {
                "rule_id": e.rule_id,
                "failure_kind": e.failure_kind,
                "message": e.message,
                "line": e.line,
                "col": e.col,
            }
            for e in (last_validation.errors if last_validation else ())
        ],
    }


def generate_audit_script(
    chunks: list[dict],
    endpoint_catalog: list[str],
    claude_api_key: str,
    max_map_calls: int = MAX_MAP_CALLS,
    max_attempts: int = MAX_GENERATION_ATTEMPTS,
) -> dict:
    """Pipeline completo: map -> (no-verifiable-controls | reduce+retry).

    Si el map no produce NINGUN PolicyCheck, reduce NUNCA se invoca --
    se reporta explicitamente "no_verifiable_controls" en vez de generar
    un script vacio/no-op (spec: Requirement "No-Verifiable-Controls
    Handling").
    """
    checks = map_chunks_to_checks(
        chunks, endpoint_catalog, claude_api_key, max_map_calls=max_map_calls
    )

    if not checks:
        return {"status": "no_verifiable_controls", "checks": []}

    return generate_script_with_retries(
        checks, endpoint_catalog, claude_api_key, max_attempts=max_attempts
    )
