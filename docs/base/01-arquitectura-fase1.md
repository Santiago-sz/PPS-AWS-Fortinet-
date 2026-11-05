# 01 — Arquitectura objetivo de la Fase 1

Fase 1 = **auditoría de solo lectura de un FortiGate guiada por una normativa
cargable (PDF/DOCX)**, con hallazgos que citan la cláusula incumplida y
remediaciones **propuestas** (nunca aplicadas). Todo el código canónico vive en
`audit-pipeline/` y `desktop/`; las carpetas `lambda/` y `terraform/` de la
raíz son copias legacy (ver `04-estructura-del-repositorio.md`).

Diagramas: `diagrams/01-arquitectura-aws.png`,
`diagrams/02-secuencia-flujo-de-auditoria.png`, `diagrams/06-modelo-de-datos.png`.

## 1. Flujo de punta a punta

| # | Paso | Componente | Detalle verificado en código |
|---|---|---|---|
| 1 | Carga de la normativa | App de escritorio (`desktop/`) → API local (`audit-pipeline/api`, `pps-api serve`) | `POST /api/policies` + `PUT /uploads/{id}` + `complete-upload`; la API valida MIME, tamaño (20 MiB), SHA-256 y que el PDF/DOCX tenga texto. Persistencia en SQLite (`.pps-api/development.sqlite3`). La carga **no** llama a AWS. |
| 2 | Envío a S3 | `pps-api aws dispatch` (`aws_bridge.Bridge.dispatch`) | `PutObject` en `s3://<policies_bucket>/policies/{audit_id}.pdf|docx` con metadatos `audit-id` y `policy-sha256`. Alternativa manual: `aws s3 cp`. |
| 3 | Disparo | S3 `ObjectCreated:*` con filtro `policies/` + sufijo `.pdf`/`.docx` (`storage.tf`) | Invoca de forma asíncrona la Lambda `policy_generator`. |
| 4 | Extracción | `extractor.py` (layer `pps-doc-parsers`: pypdf, python-docx, lxml) | Falla explícita (`ExtractionError`: `corrupt`, `encrypted`, `no_text_layer`, `unsupported_content_type`). Nunca trunca. |
| 5 | Chunking | `chunker.py` | Respeta límites de cláusula (headings DOCX o regex "Capítulo/Sección/Artículo/1.2.3"); `heading_path` y página por chunk; `DEFAULT_MAX_CHUNK_CHARS = 4000`. |
| 6 | Map | `llm_client.map_chunks_to_checks` → `bedrock_client.converse` (API Converse) | Un prompt por grupo de chunks (`MAP_GROUP_MAX_CHARS = 12_000`, `MAX_MAP_CALLS = 12`; si se exceden → `MapCallBudgetExceededError`, nunca se trunca). Devuelve `PolicyCheck[]` con `clause_ref` (cita textual), `endpoints` del catálogo, `severity`, `intent`, `remediation`. `check_id` (`chk-NNNN`) lo asigna el código, no el modelo. |
| 7 | Reduce + validación con reintento | `llm_client.generate_script_with_retries` + `script_validator.validate` | Hasta `MAX_GENERATION_ATTEMPTS = 3`. Cada fallo reenvía el script anterior + feedback estructurado `{attempt, failure_kind, rule_id, message, line, col, snippet}` derivado del **primer** error. Agotado → `generation_failed`. |
| 8 | Firma y persistencia | `s3_io.put_script` / `put_manifest` | `artifacts/{run_id}/script.py` y `artifacts/{run_id}/manifest.json`; `script_sha256` se calcula sobre los bytes exactos escritos a S3. |
| 9 | Invocación o compuerta humana | `handler_generator.lambda_handler` | `AUTO_EXECUTE=true` → `lambda:InvokeFunction` (`InvocationType=Event`) con el puntero `{run_id, manifest_key, script_key, script_sha256}`. `AUTO_EXECUTE=false` → devuelve `awaiting_approval`; un operador aprueba con `pps-api aws approve <run_id>`. |
| 10 | Integridad + re-validación | `handler_executor.lambda_handler` | Recalcula SHA-256 del script y lo compara con el manifest **y** con el payload antes de tocar el AST; luego `script_validator.validate` desde cero. Cualquier rechazo → `could_not_audit` (`integrity_check_failed`, `revalidation_failed:<rule_id>`). |
| 11 | Ejecución en sandbox | `sandbox.execute` + `toolkit.py` | `__builtins__ = {}` + 21 nombres seguros + `fgt`/`report`. Presupuestos: `max_wall_clock_s=120`, `max_fgt_calls=40`, `max_findings=500`. Corte → `truncated` con hallazgos parciales preservados. |
| 12 | Lectura del FortiGate | `fortigate_client.FortiGateClient.get(label)` | Solo `GET https://<host>/api/v2/cmdb/<path>` sobre los 31 endpoints de `ENDPOINTS`; memoizado; timeout 15 s; endpoint caído → `None` (no aborta). |
| 13 | Reporte | `reporter.deliver_policy_report` | `reports/{run_id}/report.md` + `report.json` y notificación SNS (asunto según `completed` / `truncated` / `could_not_audit`). |
| 14 | Sincronización local | `pps-api aws sync` (`Bridge.sync`) | Lista `reports/`, lee cada `report.json`, lo correlaciona por `policy_key` con la auditoría local, baja `artifacts/{run_id}/manifest.json` y persiste el par en SQLite (inmutable). |
| 15 | Consola | App de escritorio | Resumen, resultados, cláusula citada, columna REMEDIACIÓN (`Sí`/`—`), detalle "Remediación propuesta" con leyenda de que nada se aplicó. |

Fallos del generador (extracción, modelo, `no_verifiable_controls`,
`generation_failed`) escriben `reports/{run_id}/report.{md,json}` con
`status=could_not_audit` **solo en S3**: el rol del generador no tiene
`sns:Publish` (decisión de mínimo privilegio documentada en
`handler_generator.py`). El executor sí notifica por SNS éxito y fallo.

## 2. Componentes AWS

Prefijo real: `${project_name}-${environment}` → con los defaults
`pps-prod`. Cuenta de prueba: `656051538542`, región `us-east-1`.

| Servicio | Nombre (patrón) | Propósito | IAM / notas |
|---|---|---|---|
| S3 | `pps-prod-policies-<account_id>` | Entrada: `policies/*.pdf|docx`. Versionado, PAB total, SSE-S3, notificación → generador | Solo lo lee el generador (`s3:GetObject`, `s3:ListBucket`). El executor no tiene permiso sobre él. |
| S3 | `pps-prod-reports-<account_id>` | `artifacts/{run_id}/{script.py,manifest.json}` y `reports/{run_id}/{report.md,report.json}`. Lifecycle 365 d (`artifact_retention_days`, `report_retention_days`) | Generador: `PutObject` en `artifacts/*` y `reports/*`. Executor: `GetObject artifacts/*`, `PutObject reports/*`. |
| Lambda | `pps-prod-policy-generator` (`handler_generator.lambda_handler`, 900 s, 1024 MB, layer) | Extract → chunk → map/reduce → validate → firmar → invocar | Rol `pps-prod-generator-role`: `bedrock:InvokeModel*` (foundation-model `anthropic.*` + `inference-profile/*` de la cuenta), S3 arriba, `lambda:InvokeFunction` sobre el executor, `sqs:SendMessage` a su DLQ, logs. **Sin acceso a ningún secret.** |
| Lambda | `pps-prod-audit-executor` (`handler_executor.lambda_handler`, 300 s, 512 MB, stdlib-only) | Integridad + re-validación + sandbox + FortiGate + reporte | Rol `pps-prod-executor-role`: `secretsmanager:GetSecretValue` (solo el token FortiGate), S3 arriba, `sns:Publish`, `sqs:SendMessage` a su DLQ, logs. **Sin `bedrock:*`.** `AWSLambdaVPCAccessExecutionRole` solo si `executor_subnet_ids` no está vacío. |
| Lambda | `pps-prod-assessor` (`handler.lambda_handler`) | Flujo NIST CSF 2.0 legacy; se despliega pero su schedule EventBridge está apagado (`enable_legacy_nist_schedule=false`) | Rol `pps-prod-lambda-role` (secret + Bedrock + S3 + SNS). |
| Lambda Layer | `pps-prod-doc-parsers` | pypdf + python-docx + lxml (manylinux2014_x86_64, py3.12). Construido por `scripts/build_layer.py` | Solo se adjunta al generador. |
| Amazon Bedrock | `us.anthropic.claude-sonnet-4-6` (perfil de inferencia cross-region, `BEDROCK_MODEL_ID`) | Modelo para map/reduce (y para el assessor legacy) | Autorización por IAM; no existe API key. Prompt caching con `cachePoint` tras el system prompt. |
| CloudWatch Logs | `/aws/lambda/pps-prod-{policy-generator,audit-executor,assessor}`; `/aws/bedrock/pps-prod-model-invocations` | Logs, eventos JSON (`llm_call`, `generation_result`, `generator_result`, `awaiting_approval`, `executor_result`) y métricas EMF (`PPS/AuditPipeline`); Model Invocation Logging con prompt + respuesta | Retención `log_retention_days` (365). Invocation logging es **único por cuenta/región** (`enable_bedrock_invocation_logging`). |
| SNS | `pps-prod-notifications` | Reportes del executor + alarmas | Suscripción email (`notification_email`), requiere confirmación. |
| SQS | `pps-prod-policy-generator-dlq`, `pps-prod-audit-executor-dlq` | Eventos que agotaron los reintentos asíncronos de Lambda (14 días, SSE-SQS) | Alarma `*-dlq-messages` ≥ 1. |
| CloudWatch Alarms | `pps-prod-{assessor,policy-generator,audit-executor}-errors`, `pps-prod-*-dlq-messages` | `Errors ≥ 1` en 5 min; mensajes visibles en DLQ | Acción: el topic SNS. |
| Secrets Manager | `pps-prod-fortigate-token` | Token REST de FortiGate (`{"token": "..."}`; `host` opcional e ignorado: manda `FORTIGATE_HOST`) | Placeholder creado por Terraform con `ignore_changes`; valor real cargado a mano. |
| IAM | `pps-prod-bedrock-logging-role` | Rol de servicio para que Bedrock escriba el log de invocaciones | Trust acotada con `aws:SourceAccount` / `aws:SourceArn`. |

Variables de entorno exactas por función: ver `AGENTS.md` §4 y
`terraform/lambda.tf` (el test `test_handler.py::TestTerraformEnvVarsMatchHandler`
verifica el contrato IaC ↔ código).

## 3. Dónde vive la IA y por qué

- **Amazon Bedrock dentro de la cuenta.** La única pieza que habla con el
  modelo es `bedrock_client.converse` (API Converse, `maxTokens` explícito,
  system prompt + `cachePoint`). Autorización por IAM del rol de la Lambda: no
  hay API key que rotar ni filtrar, y el tráfico no sale de AWS.
- **Model Invocation Logging** (`bedrock_logging.tf`) registra prompt y
  respuesta de cada invocación: es la evidencia primaria para la tesis ("qué se
  pidió y qué devolvió"). El log contiene el texto de las normativas: tratarlo
  como dato sensible.
- **El executor no tiene acceso al modelo** (ni IAM ni imports). Lo que llega
  al FortiGate es un script ya validado y firmado; un compromiso del executor
  no puede generar código nuevo, y un compromiso del generador no puede
  alcanzar el firewall ni leer su token.
- Modelo actual: `claude-sonnet-4-6` (ACTIVE en la cuenta). `claude-sonnet-5-5`
  no está disponible para esta cuenta (ver `05-decisiones.md`).

## 4. Por qué Lambda + invocación asíncrona y no Step Functions (en Fase 1)

Decisión #2 del diseño (`openspec/.../design.md`): el contrato
generador → executor es un `lambda:InvokeFunction` asíncrono con un puntero
pequeño; el hash de integridad viaja con la llamada; los bytes quedan en S3;
dos funciones, dos roles disjuntos, cero servicios nuevos. Step Functions se
rechazó para el MVP porque:

- El flujo es lineal (un disparo, un reintento acotado **dentro** del
  generador, una ejecución). No hay ramas paralelas ni esperas largas que
  justifiquen una máquina de estados.
- Añade IAM, definición ASL y costo de aprendizaje sin reducir riesgo: el
  riesgo real está en el código generado, y eso lo resuelven el validador, el
  sandbox y la separación de roles, no la orquestación.

Step Functions entra naturalmente en Fase 2 cuando aparezca al menos una de
estas necesidades: (a) **compuerta de aprobación con espera** (`waitForTaskToken`)
en lugar del par `AUTO_EXECUTE=false` + `pps-api aws approve`; (b) normativas
cuyo map/reduce supere los 900 s de una Lambda (paralelizar map por grupo);
(c) remediación asistida con pasos humanos intermedios.

## 5. Estados de un run

| Estado | Quién lo produce | Significado | Dónde se ve |
|---|---|---|---|
| `invoked` | generador (valor de retorno) | Artefactos firmados y executor invocado | Evento `generator_result` |
| `awaiting_approval` | generador (`AUTO_EXECUTE=false`) | Script + manifest en S3, sin ejecutar | Evento `awaiting_approval`; `pps-api aws list-pending`; GUI "Pendiente de aprobación" |
| `completed` | executor | Auditoría completa | `report.json.status`, SNS "completed" |
| `truncated` | executor | Presupuesto del sandbox agotado (`wall_clock_exceeded`, `call_count_exceeded`, `findings_exceeded`); hallazgos parciales **sí** se reportan; `report.json.truncated=true` | SNS "TRUNCATED", GUI "Parcial · límite alcanzado" |
| `could_not_audit` (+ `failure_reason`) | generador o executor | No hay evidencia utilizable. Razones: `extraction_error:<reason>`, `ClaudeCallError:<msg>` (p. ej. `ThrottlingException`), `MapResponseParseError`, `MapCallBudgetExceededError`, `no_verifiable_controls`, `generation_failed`, `integrity_check_failed`, `revalidation_failed:<rule_id>`, `execution_error:<tipo>` | `report.json`, SNS solo si lo escribió el executor |
| `generation_failed`, `no_verifiable_controls` | generador (**valor de retorno** de la Lambda) | El `report.json` correspondiente lleva `status=could_not_audit` con ese `failure_reason` | Evento `generator_result`; API local mapea `no_verifiable_controls` a "sin controles verificables" |

## 6. Modelo de datos

```text
Chunk        = {chunk_id, ordinal, heading_path[], page, char_span, text}
ClauseRef    = {chunk_id, heading_path[], page, quote}
Remediation  = {summary: str|null, steps: [str], fortigate_cli: str|null}   # PROPUESTA
PolicyCheck  = {check_id, title, clause_ref, endpoints[], severity, intent, remediation}
RunManifest  = {run_id, policy_key, policy_sha256, script_key, script_sha256,
                checks: [PolicyCheck], attempts, model, generated_at}
Finding      = {check_id, clause_ref, status: pass|fail|not_applicable|indeterminate,
                evidence, endpoints_used[], traceable, remediation}
Note         = {check_id, message}
report.json  = {run_id, policy_key, timestamp, status, truncated: bool,
                findings: [Finding], notes: [Note], remediation_count, failure_reason?}
```

- `clause_ref` y `remediation` los resuelve **el toolkit** desde el manifest
  (`ReportCapability.finding`); el script generado no puede pasarlos ni
  forjarlos. `reporter` re-deriva `traceable` (requiere `clause_ref.quote` no
  vacío) antes de persistir.
- `remediation_count` cuenta hallazgos con `summary`, `steps` o `fortigate_cli`.
  La sección Markdown "Remediaciones propuestas" incluye todo `fail` y los
  `indeterminate` con propuesta, con el disclaimer de que nada fue aplicado.
- `GET /api/audits/{id}/results` de la API local devuelve
  `{"manifest", "report", "next_cursor", "summary"}` con
  `summary = {total, pass, fail, indeterminate, not_applicable, with_remediation}`
  calculado al leer; el resultado almacenado es inmutable.

Layout S3:

```text
s3://pps-prod-policies-<acct>/policies/{audit_id}.pdf|docx
s3://pps-prod-reports-<acct>/artifacts/{run_id}/manifest.json
s3://pps-prod-reports-<acct>/artifacts/{run_id}/script.py
s3://pps-prod-reports-<acct>/reports/{run_id}/report.json
s3://pps-prod-reports-<acct>/reports/{run_id}/report.md
```
