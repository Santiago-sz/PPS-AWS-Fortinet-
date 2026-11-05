# 03 — Harness Engineering aplicado al pipeline

Diagrama: `diagrams/03-harness-capas-de-control.png`.

## 1. Qué es Harness Engineering

La idea central es que un **agente = modelo + arnés (harness)**: el modelo
aporta la capacidad de razonar y generar; el arnés es todo lo que lo rodea
—restricciones, herramientas acotadas, presupuestos, verificación,
observabilidad y evaluación— y es lo que convierte una salida probabilística
en un sistema con garantías operativas. En esta lectura, la ingeniería no
consiste en "pedirle mejor al modelo" sino en **diseñar el entorno** en el que
el modelo no puede causar daño aunque se equivoque, y en **medir** cuánto se
equivoca.

Fuentes usadas para la definición:

- Artículo arXiv 2609.00006 — https://arxiv.org/pdf/2609.00006
- Software Improvement Group, "What is harness engineering?" —
  https://www.softwareimprovementgroup.com/blog/what-is-harness-engineering/
- nxcode, "What is Harness Engineering — complete guide 2026" —
  https://www.nxcode.io/resources/news/what-is-harness-engineering-complete-guide-2026

Advertencia metodológica para la tesis: el término es de 2026 y **no está
estandarizado**; distintas fuentes lo usan con énfasis distintos (arnés de
ejecución de agentes de código, arnés de evaluación, arnés de seguridad). En
el texto conviene (a) citar las fuentes, (b) dar la definición operativa que
se adopta ("conjunto de controles deterministas que acotan y verifican la
salida de un modelo generativo"), y (c) mostrar que el pipeline la implementa
pilar por pilar, que es lo que hace la tabla siguiente.

## 2. Pilares del arnés → código concreto

Rutas relativas a `audit-pipeline/`.

| Pilar | Qué garantiza | Dónde está | Detalle verificable |
|---|---|---|---|
| **Restricciones estáticas (allowlist)** | El código generado solo puede expresar lo que el dominio necesita; todo lo demás se rechaza por defecto (*fail closed*) | `lambda/script_validator.py` | `_ALLOWED_NODE_TYPES` (Module, FunctionDef, If, For, comprehensions, Call, Constant, operadores, f-strings…), `_DENIED_NODE_TYPES` (Import, ClassDef, Lambda, While, **Try**, Raise, With, Global, Delete, Starred, Yield, Await, Async*), `_DENY_BY_NAME` (getattr, eval, exec, open, type, `__import__`…), identificadores con `__` prohibidos, `MAX_AST_NODES = 4000`, `MAX_NESTING = 3`, `fgt.get()` solo con literal del catálogo (`endpoint_not_in_catalog`), `report.finding()` solo con `check_id` del manifest y cobertura completa (`check_id_coverage_incomplete`). `Try` se niega para que `SandboxBudgetExceeded` sea inatrapable. |
| **Herramientas acotadas (capabilities)** | El modelo no recibe un cliente HTTP ni credenciales: recibe dos objetos con cuatro métodos | `lambda/toolkit.py`, `lambda/fortigate_client.py` | `FgtCapability.get(label)` / `endpoints()`; `ReportCapability.finding()` / `note()`. `clause_ref` y `remediation` se resuelven **del lado del servidor** desde el manifest: el script no puede forjar la cita ni redactar la remediación. `FortiGateClient` solo hace `GET` sobre `ENDPOINTS` (31 labels) bajo `/api/v2/cmdb`. |
| **Presupuestos duros** | Un script defectuoso o malicioso no puede agotar la Lambda ni inundar el firewall | `lambda/sandbox.py` | `SandboxBudget(max_wall_clock_s=120, max_fgt_calls=40, max_findings=500)`; gate por llamada (multiplataforma) + backstop `signal.setitimer` (Linux); `__builtins__ = {}` con 21 nombres seguros. El corte produce `status=truncated` **conservando** los hallazgos parciales. |
| **Ciclo de retroalimentación acotado** | El modelo corrige sus propios errores con evidencia concreta, pero un número finito de veces | `lambda/llm_client.py` | `MAX_GENERATION_ATTEMPTS = 3`; `build_retry_feedback` envía `{attempt, failure_kind, rule_id, message, line, col, snippet}` + el script anterior; `MAX_MAP_CALLS = 12` y `MAP_GROUP_MAX_CHARS = 12_000` (se generan más llamadas antes que truncar; exceso → `MapCallBudgetExceededError`). Agotado → `generation_failed`, nunca un script parcial. |
| **Verificación independiente** | La confianza no se hereda entre etapas | `lambda/handler_executor.py` | Recalcula `sha256(script)` y lo compara con manifest **y** payload antes de `ast.parse`; vuelve a correr `script_validator.validate` desde cero. `s3_io.put_script` calcula el hash sobre los bytes exactos subidos. |
| **Ejecutor determinista sin acceso al modelo** | Separación de poderes: quien genera no toca el firewall; quien ejecuta no puede generar | `terraform/iam.tf`, `lambda/handler_executor.py` | Rol `executor` sin `bedrock:*` ni lectura del bucket de políticas; rol `generator` sin `secretsmanager:*`. El executor no importa `llm_client`/`bedrock_client` y es stdlib-only (sin layer). |
| **Compuerta humana** | Un operador puede revisar el script y las remediaciones antes de que algo toque el equipo | `lambda/handler_generator.py`, `api/pps_api/aws_bridge.py` | `AUTO_EXECUTE=false` → `awaiting_approval`; `pps-api aws list-pending` / `pps-api aws approve <run_id>` reenvía solo el puntero firmado. Las remediaciones son texto para humanos; nada las ejecuta (`AGENTS.md` regla 3). |
| **Observabilidad** | Cada decisión del arnés deja evidencia consultable | `lambda/observability.py`, `lambda/bedrock_client.py`, `terraform/bedrock_logging.tf`, `terraform/monitoring.tf` | Eventos JSON de una línea (`llm_call`, `generation_result`, `generator_result`, `awaiting_approval`, `executor_result`), métricas EMF en `PPS/AuditPipeline` (`LlmInputTokens`, `LlmOutputTokens`, `LlmLatencyMs`, `GenerationAttempts`, `GenerationFirstAttemptPass`), Model Invocation Logging (prompt + respuesta), DLQ + alarmas. |
| **Evaluación (evals)** | La calidad del generador se mide con métricas reproducibles, no con impresiones | `evals/run_evals.py`, `evals/thresholds.json`, `evals/README.md` | Mismo camino que producción (`chunker` → `map` → `reduce+retry` → `validate`). Métricas: `first_attempt_pass`, `attempts_used`, `validator_ok_final`, `checks_in_range`, `check_recall`, `endpoint_precision`, `remediation_coverage`, tokens, latencia. Modo `offline` (fixtures grabadas; corre en CI y en `test_evals_offline.py`) y `live`/`--record`. Umbrales: recall ≥ 0.6, precisión ≥ 0.8, remediación ≥ 0.8, first-attempt rate ≥ 0.5, success = 1.0. |
| **Arnés de desarrollo** | El propio código del arnés está protegido contra regresiones | `lambda/tests/`, `api/tests/`, `desktop/tests/`, `pyproject.toml`, `.github/workflows/ci.yml`, `AGENTS.md` | 275 tests (lambda, incl. corpus adversarial del validador y contrato IaC↔env vars) + 30 (api) + 45 (desktop); `ruff`; `checkov` (109 passed / 29 failed documentados en `checkov-report.md`); `terraform fmt/validate`; CI en cada push; `AGENTS.md` fija las reglas no negociables (nunca debilitar validador/sandbox, solo lectura, remediación como propuesta, roles separados). |

Última corrida de evals (offline, fixtures grabadas):

| policy | status | 1st-pass | attempts | checks | recall | ep-prec | remed | tok in/out |
|---|---|---|---|---|---|---|---|---|
| politica-acceso-administrativo | ok | no | 2 | 5 | 1.00 | 1.00 | 1.00 | 8070/3330 |
| politica-contrasenas | ok | yes | 1 | 5 | 1.00 | 1.00 | 1.00 | 4770/2150 |
| politica-registro-y-ntp | ok | yes | 1 | 4 | 1.00 | 1.00 | 1.00 | 4700/1740 |
| **overall** | success 1.00 | **0.67** | — | — | 1.00 | 1.00 | 1.00 | 17540/7220 |

## 3. Qué medir y reportar en la tesis

| Métrica | Cómo se obtiene | Qué demuestra |
|---|---|---|
| Tasa de aprobación al primer intento (`first_attempt_pass_rate`) y `attempts_used` | `run_evals.py --mode live` (JSON en `evals/results/`); en producción, métrica EMF `GenerationFirstAttemptPass` / `GenerationAttempts` y evento `generation_result.failure_kinds_per_attempt` | Cuánto trabajo hace el ciclo validador → feedback → reintento. Un 0.67 significa que 1 de 3 normativas necesitó corrección automática. |
| `check_recall` | evals | Fidelidad a la normativa: el modelo encontró los controles que un humano marcó como verificables. |
| `endpoint_precision` | evals | El modelo no inventa endpoints fuera del catálogo (restricción + prompt). |
| `remediation_coverage` | evals; en reportes, `remediation_count / len(findings)` | Utilidad para el operador. |
| Tokens de entrada/salida y `cache_read_tokens` | `llm_call` events, EMF, `ConverseResult`, facturación de Bedrock | Costo por auditoría; efecto del `cachePoint`. |
| Latencia por fase (`latency_ms` por `Stage`) y `wall_clock_ms` del executor | EMF `LlmLatencyMs`, evento `executor_result` | Encaje en los presupuestos de tiempo (900 s / 300 s / 120 s). |
| Rechazos del validador en producción | `generation_result.failure_kinds_per_attempt`, `failure_reason=revalidation_failed:*` | Qué reglas del allowlist trabajan de verdad. |
| Cortes por presupuesto | `executor_result.status=truncated`, `budget_exceeded` | Frecuencia con que el sandbox interviene. |

Dos casos de estudio ya disponibles:

1. **El estado `truncated`.** La especificación exigía preservar hallazgos
   parciales ante un corte; reportarlos como `completed` daba una falsa
   sensación de auditoría íntegra y como `could_not_audit` los descartaba. Se
   introdujo un tercer estado con `report.json.truncated=true`, cabecera de
   advertencia en Markdown y asunto SNS propio (`reporter.py`,
   `handler_executor.py`, tests `TestBuildPolicyReport*`). Ilustra que el
   arnés también gobierna la *semántica de la salida*, no solo la seguridad.
2. **La brecha del catálogo detectada por evals (resuelta).** Las normativas
   de contraseñas y de registro/NTP producían menos checks que cláusulas
   porque `fortigate_client.ENDPOINTS` no incluía `system/password-policy`,
   `system/ntp`, `log.fortianalyzer/setting` ni `log.syslogd/setting`. El
   prompt de map prohíbe inventar controles, así que el modelo **omitía** en
   lugar de alucinar; `max_checks` acotaba ese comportamiento. El catálogo
   se amplió de 11 a 31 labels GET-only (`password_policy`, `ntp`,
   `log_syslogd`, `log_fortianalyzer`, `log_settings`, `log_memory`,
   `admin_profiles`, `api_users`, `ha`, `fortiguard`, `snmp_sysinfo`,
   `vdom_settings`, `central_management`, `firewall_addresses`,
   `static_routes`, `sdwan`, `ldap_servers`, `radius_servers`,
   `dhcp_servers`, `ssl_ssh_profiles`) y los evals pasaron de 5→9 y 4→8
   checks sin tocar validador ni sandbox: el hallazgo del arnés
   (restricción + eval) se cerró ampliando la tupla `(path, label)`.

## 4. Limitaciones conocidas

- **Clase de bypass del allowlist AST (CVE-2026-40158).** Un filtro que solo
  inspecciona `ast.Attribute.attr` es evadible por reflexión
  (`getattr(type, "__getattribute__")`). Mitigación en capas: allowlist de
  métodos por receptor, `getattr`/`type` denegados por nombre, `__builtins__`
  vacío, y los presupuestos del sandbox como última línea. El corpus
  adversarial de `test_script_validator.py` debe seguir fallando como falla.
- **Sin muro de red a nivel de infraestructura.** El toolkit niega la red
  sintácticamente, pero el executor fuera de VPC tiene egreso a Internet. El
  muro (VPC + SG de egreso restringido + endpoints de S3/Secrets/SNS) existe
  como opción (`executor_subnet_ids`) y queda como fast-follow.
- **Backstop `SIGALRM` solo en Linux.** En Windows el test se salta y solo
  actúa el gate por llamada; la Lambda real (Linux) sí lo tiene. Falta
  ejecutar ese test en Linux/CI y documentar el resultado.
- **Cuota de Bedrock = 0 en la cuenta de prueba.** Impide hoy la corrida
  `live` y la prueba de punta a punta con modelo real (ver `02-...md` §4.3).
- **Evals pequeñas.** Tres normativas sintéticas de un solo chunk: validan el
  camino pero no la robustez con normativas largas (map multi-grupo, TF-IDF
  de respaldo). Ampliar el corpus es parte del trabajo de evaluación de la tesis.
- **Observabilidad del lado de la API local.** `aws sync` enumera `reports/`
  y correlaciona por `policy_key`; para producción haría falta un índice
  persistido y deduplicación de invocaciones (documentado en `api/README.md`).
