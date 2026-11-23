# Evals del generador de scripts de auditoría

Harness de evaluación del pipeline policy-driven: toma normativas sintéticas,
las pasa por el **mismo camino que producción** (`chunker.chunk` →
`llm_client.map_chunks_to_checks` → `llm_client.generate_script_with_retries`
→ `script_validator.validate`) y mide la calidad del resultado contra un
conjunto esperado escrito a mano. Es el tercer pilar del harness junto con
los tests unitarios (`lambda/tests/`) y el análisis estático de IaC (checkov).

No ejecuta ningún script generado ni toca un FortiGate: solo mide la fase
de generación (map/reduce + validación). Las fixtures grabadas recorren el
camino sin Knowledge Base; con la recuperación habilitada el prompt de
reduce cambia y ese camino no tiene todavía una grabación.

Una segunda suite mide la calidad de recuperación de la Knowledge Base; ver
«Evals de recuperación» más abajo.

## Cómo correr

```bash
cd audit-engine

# Offline (default): sin red ni credenciales, usa recorded/*.json. Es lo que corre CI.
../.venv/Scripts/python.exe evals/run_evals.py --mode offline

# Live: Bedrock real. Requiere credenciales AWS con bedrock:InvokeModel y el
# perfil de inferencia habilitado (BEDROCK_MODEL_ID opcional, default
# us.anthropic.claude-sonnet-4-6). Imprime una estimación de tokens antes de llamar.
AWS_PROFILE=pps-tesis AWS_REGION=us-east-1 ../.venv/Scripts/python.exe evals/run_evals.py --mode live

# Live + re-grabar fixtures (sobrescribe recorded/<normativa>.json)
AWS_PROFILE=pps-tesis AWS_REGION=us-east-1 ../.venv/Scripts/python.exe evals/run_evals.py --mode live --record

# Una sola normativa / ver chunks detectados / ver eventos de observability
../.venv/Scripts/python.exe evals/run_evals.py --policy politica-contrasenas
../.venv/Scripts/python.exe evals/run_evals.py --dump-chunks
../.venv/Scripts/python.exe evals/run_evals.py --verbose
```

Salida: una tabla Markdown por stdout y `results/<timestamp>-<modo>.json`
con todas las métricas, los checks producidos y los fallos de umbral.
Código de salida `1` si alguna métrica queda por debajo de
`thresholds.json`. En Windows conviene `PYTHONUTF8=1` (los `.md` tienen
tildes).

El smoke test `lambda/tests/test_evals_offline.py` corre el modo offline
dentro de la suite de pytest, así que `pytest` ya falla si las fixtures o
los umbrales se rompen.

## Estructura

| Ruta | Contenido |
|---|---|
| `policies/<nombre>.md` | Normativa sintética en español (25-60 líneas, cláusulas numeradas). **No son documentos reales.** |
| `expected/<nombre>.json` | Checks esperados: `id`, `keywords` (grupos any-of), `endpoints_any` (labels de `fortigate_client.ENDPOINTS`), más `min_checks` / `max_checks`. |
| `recorded/<nombre>.json` | Respuestas del modelo en orden de llamada (map primero, luego cada intento de reduce). Las escritas a mano usan `json` (map) y `lines` (script) por legibilidad; `--record` guarda `text` crudo. |
| `thresholds.json` | Umbrales por normativa y agregados. |
| `results/` | Salidas (ignoradas por Git). |
| `run_evals.py` | El runner. Solo stdlib + módulos de `lambda/`. |

Las normativas en Markdown se convierten a `(texto, metadata)` con la misma
forma que produce `extractor._extract_docx` (un entry por línea, headings
`#` con nivel), de modo que `chunker.chunk` detecta las cláusulas por
metadata igual que con un DOCX real. Con las tres normativas actuales cada
una cabe en un único chunk (`chunk-0001`) y por lo tanto en una sola
llamada de map.

## Métricas

Por normativa:

| Métrica | Definición |
|---|---|
| `status` | `ok`, `generation_failed`, `no_verifiable_controls` o `error` (fallo de transporte/parseo). |
| `first_attempt_pass` | `status == ok` y el validador aceptó el script en el intento 1. |
| `attempts_used` | Intento de reduce que produjo el script entregado (`MAX_GENERATION_ATTEMPTS` = 3 por defecto). Sin correcciones de campos coincide con los intentos consumidos. |
| `unknown_field_references` / `unknown_fields` | Cantidad y nombres de los campos que el script entregado lee y el catálogo de campos no lista (`field_catalog.find_unknown_field_references`; decisión 13). Es un aviso, no un rechazo: no tiene umbral. |
| `reduce_calls` / `reduce_calls_unanswered` | Llamadas de reduce respondidas, y llamadas pedidas que no tuvieron respuesta. La segunda es mayor que cero cuando un intento de corrección de campos falla; en offline, cuando la fixture no trae ese intento. |
| `validator_ok_final` | `script_validator.validate(script, manifest).valid` re-ejecutado sobre el script final. |
| `checks_count` / `checks_in_range` | Cantidad de `PolicyCheck` producidos por el map y si cae en `[min_checks, max_checks]`. |
| `check_recall` | Fracción de checks esperados que matchean algún check producido: para cada grupo de `keywords` al menos un sinónimo aparece en `title + intent + clause_ref.quote` (minúsculas, sin tildes). |
| `endpoint_precision` | Fracción de referencias a endpoints (sumando todos los checks) que están en el catálogo **y** en la unión de `endpoints_any` esperados. `0.0` si no hay referencias. |
| `remediation_coverage` | Fracción de checks con `remediation.summary` no nulo. |
| `input_tokens` / `output_tokens` / `cache_read_tokens` | Sumados sobre todas las llamadas (`ConverseResult`; en offline, lo que declara la fixture). |
| `latency_ms` | Suma de `latencyMs` reportado por Bedrock (o de la fixture). `wall_ms` es el tiempo real del runner. |

Agregadas: `first_attempt_pass_rate`, `generation_success_rate`,
`mean_check_recall`, `mean_endpoint_precision`,
`mean_remediation_coverage`, totales de tokens y latencia,
`total_unknown_field_references` y `reduce_calls_unanswered`.

`first_attempt_pass` conserva su definición: el validador aceptó el primer
intento, aunque después se entregue una corrección de nombres de campo de un
intento posterior.

Umbrales actuales (`thresholds.json`): por normativa `check_recall ≥ 0.6`,
`endpoint_precision ≥ 0.8`, `remediation_coverage ≥ 0.8`,
`checks_in_range`, `validator_ok_final`; agregado
`first_attempt_pass_rate ≥ 0.5` y `generation_success_rate = 1.0`.

## Estado de las fixtures frente al catálogo de campos (2026-11-22)

Las tres fixtures de `recorded/` son anteriores al catálogo de campos
(decisión 13) y **no se regrabaron**: hacerlo exige Bedrock. Desde ese cambio
el system prompt de reduce incluye el catálogo y un script válido que lee un
campo no listado dispara un intento de corrección. Consecuencias en modo
offline, que el runner informa en su salida y en `results/`:

- Los tres scripts grabados leen campos que el catálogo no lista (6 en total:
  `admintimeout`; `min-length`, `must-contain`, `password-expire`; `event`,
  `forward-traffic`).
- Cada normativa pide una llamada de corrección que la fixture no trae. El
  transporte offline responde «fixture agotada», el ciclo conserva el script
  válido anterior y la normativa termina `ok`. Son 3 llamadas sin respuesta.
- El código de salida sigue siendo 0 y las métricas con umbral no cambian,
  pero las fixtures ya no representan lo que el modelo responde al prompt
  actual. Las cifras de tokens y latencia grabadas tampoco.

Para regrabar (lo ejecuta el dueño; contacta Bedrock):

```bash
cd audit-engine
AWS_PROFILE=pps-tesis AWS_REGION=us-east-1 ../.venv/Scripts/python.exe evals/run_evals.py --mode live --record
```

Costo: tres normativas, cada una con 1 llamada de map y entre 1 y 3 de
reduce, es decir entre 6 y 12 llamadas a Converse. El runner imprime antes de
llamar su estimación de peor caso, unos 113.000 tokens en total con el
catálogo (4 caracteres por token; no es una medición). Con la cuota de 10
pedidos por minuto, 12 llamadas seguidas pueden alcanzar el límite; el cliente
reintenta. Revisar el diff de `recorded/` antes de commitear.

## Qué cubren las fixtures offline

- `politica-acceso-administrativo`: 5 checks; el **primer reduce contiene
  `import re` a propósito** para que el validador lo rechace
  (`denied_node:Import`) y se ejercite el ciclo de reintento con feedback
  → `first_attempt_pass=false`, `attempts_used=2`.
- `politica-contrasenas`: 9 checks al primer intento. Las cláusulas de
  longitud/complejidad/historial (2.1-2.3) se verifican sobre
  `password_policy` (`system/password-policy`); la caducidad (3.1) combina
  `admins` + `password_policy` y el cambio forzado en el primer login (3.2)
  usa `admins`. `max_checks` acota que el modelo no fragmente cláusulas en
  controles redundantes.
- `politica-registro-y-ntp`: 8 checks al primer intento. Registro
  centralizado y canal cifrado (2.1-2.2) se verifican sobre
  `log_fortianalyzer` / `log_syslogd`, el registro de la denegación
  implícita (3.1) sobre `log_settings` y la sincronización horaria (4.1)
  sobre `ntp`.

Hasta la ampliación del catálogo (labels `password_policy`, `ntp`,
`log_syslogd`, `log_fortianalyzer`, `log_settings`, `log_memory`,
`admin_profiles`, `api_users`, `ha`, `fortiguard`, `snmp_sysinfo`,
`vdom_settings`, `central_management`, `firewall_addresses`,
`static_routes`, `sdwan`, `ldap_servers`, `radius_servers`,
`dhcp_servers`, `ssl_ssh_profiles`) estas dos normativas producían 5 y 4
checks: las cláusulas sin endpoint se **omitían** en lugar de inventarse,
y esa brecha quedó documentada como hallazgo de los evals. Las fixtures
actuales son escritas a mano contra el catálogo ampliado; conviene
re-grabarlas en modo `live` cuando haya cuota de Bedrock.

Los scripts grabados respetan las reglas del validador: solo
`fgt.get("<label>")` con literal del catálogo, `report.finding("chk-NNNN", ...)`
con todos los ids del manifest, sin `import`/`try`/`while`, sin acceso a
atributos fuera de `fgt`/`report` (ni siquiera `dict.get` o `str.split`),
anidamiento ≤ 3.

## Agregar una normativa

1. Escribir `policies/<nombre>.md` con headings `## N. Título` y cláusulas
   `N.M texto`. Sintética, sin datos reales.
2. Escribir `expected/<nombre>.json`. Elegir `keywords` tolerantes a
   paráfrasis (grupos de sinónimos) y `endpoints_any` solo con labels del
   catálogo. Fijar `min_checks`/`max_checks` contando qué cláusulas son
   realmente verificables con el catálogo.
3. Grabar la fixture: `run_evals.py --mode live --record --policy <nombre>`
   (o escribirla a mano con el formato de las existentes). Revisar que el
   script grabado pase el validador; si el modelo necesitó reintentos,
   quedan grabados tal cual.
4. Correr `run_evals.py --mode offline` y `pytest lambda/tests/test_evals_offline.py`.

## Re-grabar respuestas live

`--mode live --record` reemplaza `recorded/<nombre>.json` con las
respuestas reales (texto crudo, tokens, latencia, `model_id`,
`recorded_at`). Hacerlo cuando cambie el prompt de map/reduce, el modelo, el
catálogo de endpoints o el catálogo de campos
(`generator/fortios_field_catalog.py`, que forma parte del prompt de reduce),
y revisar el diff antes de commitear: la fixture
es lo que CI considera "comportamiento de referencia". Si la nueva grabación
baja alguna métrica por debajo del umbral, el run live ya sale con código 1.

## Evals de recuperación (Knowledge Base)

Suite aparte del mismo runner, `--suite retrieval`. Mide solo la operación
`Retrieve` de la Knowledge Base: no invoca al modelo ni genera scripts. La
suite por defecto sigue siendo `generation`; los comandos de arriba no
cambian.

```bash
cd audit-engine

# Offline: puntúa retrieval/recorded.json. Sin red ni credenciales.
../.venv/Scripts/python.exe evals/run_evals.py --suite retrieval --mode offline

# Live: consulta la base real a través de knowledge_retriever. Requiere
# credenciales AWS con bedrock:Retrieve sobre esa base.
KNOWLEDGE_BASE_ID=<id> AWS_REGION=us-east-1 ../.venv/Scripts/python.exe evals/run_evals.py --suite retrieval --mode live

# Live + regrabar la fixture (sobrescribe retrieval/recorded.json)
KNOWLEDGE_BASE_ID=<id> AWS_REGION=us-east-1 ../.venv/Scripts/python.exe evals/run_evals.py --suite retrieval --mode live --record
```

`KNOWLEDGE_BASE_FORTIOS_VERSION` (opcional) aplica en modo live el mismo
filtro por metadato que usa el generador. `--results-dir`, `--thresholds` y
`--verbose` funcionan igual que en la suite de generación; `--policy`,
`--max-attempts` y `--dump-chunks` no aplican.

| Ruta | Contenido |
|---|---|
| `retrieval/questions.json` | Conjunto de preguntas versionado (`version`, `k`). Cada pregunta tiene `id`, `topic`, `question` y `expected_sources`: subcadenas del identificador del documento esperado (sin distinguir mayúsculas; basta con que una coincida). |
| `retrieval/recorded.json` | Resultados grabados por pregunta: lista ordenada de `{source, score}`, donde `source` es la clave del objeto (sin bucket: su nombre incluye el id de cuenta). Nunca texto de fragmentos. |
| `thresholds.json`, clave `retrieval` | Umbrales del agregado. |
| `retrieval_eval.py` | Métricas y ejecución; `run_evals.py` lo invoca. |

Métricas:

| Métrica | Definición |
|---|---|
| `hit_rate_at_k` | Fracción de preguntas con algún documento esperado entre los primeros `k` resultados (`k` = 5). |
| `mrr` | Media del recíproco de la posición del primer documento esperado; 0 para una pregunta sin acierto entre los primeros `k`. |

Por pregunta se informan `hit`, `rank`, `reciprocal_rank`, los resultados y,
en modo live, `error` si la consulta falló (cuenta como pregunta sin
acierto). Umbrales actuales: `hit_rate_at_k ≥ 0.8` y `mrr ≥ 0.6`. Salida:
tabla Markdown y `results/<timestamp>-retrieval-<modo>.json`; código de
salida `1` si no se cumple un umbral.

**La fixture actual es sintética.** `retrieval/recorded.json` lleva
`"synthetic": true`: fue escrita a mano, con orígenes y puntajes inventados,
porque el conjunto de documentos de la Knowledge Base todavía no está
cargado. Sirve para ejercitar el cálculo de métricas y umbrales (incluye
aciertos en distintas posiciones y una pregunta sin acierto); **no dice nada
sobre la calidad de recuperación de una base real**. El runner lo advierte
en la salida y lo registra como `synthetic_fixture` en el archivo de
resultados. Los `expected_sources` de las preguntas también son provisorios:
hay que ajustarlos a los nombres reales de los documentos, subir `version` y
regrabar en modo live. Los umbrales tampoco están calibrados contra datos
reales.

Las 13 preguntas cubren temas de hardening que el catálogo de endpoints
puede verificar: acceso administrativo, política de contraseñas, registro,
NTP, políticas de firewall e inspección SSL. El modo live no se ejecutó
todavía; `tests/test_retrieval_evals.py` lo prueba con el recuperador
simulado.

## Qué citar en la tesis

- La tabla Markdown y el JSON de `results/` de una corrida **live**
  (`model_id`, fecha, tokens y latencia por normativa) como evidencia
  cuantitativa de la fase de generación.
- `first_attempt_pass_rate` y `attempts_used` como medida de cuánto
  trabajo hace el ciclo validador → feedback → reintento (design.md,
  "Retry feedback").
- `check_recall` / `endpoint_precision` como proxy de fidelidad a la
  normativa y al catálogo (el modelo no inventa endpoints ni controles).
- Las brechas de cobertura del catálogo detectadas por las normativas 2 y 3
  y su resolución (de 11 a 31 labels en `fortigate_client.ENDPOINTS`, con
  el salto de 5→9 y 4→8 checks) como ejemplo de que los evals guían
  mejoras del arnés sin tocar validador ni sandbox.
- Complementar con el log de invocaciones de Bedrock
  (`terraform/bedrock_logging.tf`) para el texto completo de prompts y
  respuestas de la corrida citada.
