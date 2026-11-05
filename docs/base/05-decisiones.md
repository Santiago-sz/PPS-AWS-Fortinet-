# 05 — Registro de decisiones (ADR resumidos)

Formato: contexto / decisión / consecuencias. Complementa la tabla
"Architecture Decisions" de `openspec/changes/policy-code-generation/design.md`
(en `G:\Mi unidad\TESIS\openspec\`), que fija las decisiones #1–#9 originales
(bucket separado, puntero asíncrono, map/reduce, clause_ref server-side,
sandbox en capas, denegar `While`/`Try`, retry solo en el generador, layer
para parsers, bandera NIST).

## ADR-01 — Modelo vía Amazon Bedrock (no API directa de Anthropic, no modelo local)

- **Contexto.** El prototipo llamaba a `api.anthropic.com` con una API key en
  Secrets Manager. La tesis necesita trazabilidad de qué se le pidió al modelo
  y una historia de credenciales defendible.
- **Decisión.** Invocar Claude a través de Bedrock (API Converse) con la
  identidad IAM del rol de cada Lambda; `bedrock_client.py` es el único punto
  de contacto; Model Invocation Logging opcional por Terraform.
- **Consecuencias.** (+) Sin API key que rotar o filtrar; tráfico dentro de
  AWS; logging nativo de prompts/respuestas; costos en la misma factura.
  (−) Dependencia de la disponibilidad del modelo en la cuenta/región y de
  las **cuotas** (hoy 0 en la cuenta nueva); formulario de caso de uso. Un
  modelo local (p. ej. en EC2/SageMaker) se descartó por costo, operación y
  calidad de generación de código; la API directa, por gestión de secretos.

## ADR-02 — Lambda + invocación asíncrona en Fase 1; Step Functions en Fase 2

- **Contexto.** El informe técnico de julio de 2026 proponía Step Functions.
  El flujo real es lineal: un evento S3, un reintento acotado interno, una
  ejecución.
- **Decisión.** Dos Lambdas con roles disjuntos; `lambda:InvokeFunction`
  (`Event`) con el puntero `{run_id, manifest_key, script_key, script_sha256}`.
- **Consecuencias.** (+) Menos servicios, IAM más simple, el hash viaja con
  la llamada, DLQ por función. (−) La compuerta humana es "fuera de banda"
  (`AUTO_EXECUTE=false` + `pps-api aws approve`); la espera de aprobación no
  tiene estado durable en AWS. Step Functions entra cuando haga falta
  `waitForTaskToken`, paralelizar el map de normativas largas o encadenar
  pasos humanos de remediación (ver `01-arquitectura-fase1.md` §4).

## ADR-03 — Remediación como propuesta, no auto-remediación

- **Contexto.** El PFG formal describía remediación automática; el dueño del
  proyecto fijó el MVP como solo lectura y la remediación automática como
  Fase 2.
- **Decisión.** El map pide `remediation {summary, steps, fortigate_cli}`
  como **propuesta para un operador**; el toolkit la resuelve desde el
  manifest; el reporte y la GUI la muestran con disclaimer; no existe código
  que escriba en el FortiGate (`AGENTS.md` regla 2 y 3).
- **Consecuencias.** (+) Riesgo operativo acotado a lectura; el equipo nunca
  cambia por una alucinación; la tesis puede medir la *calidad* de las
  propuestas sin ejecutarlas. (−) El valor de "cierre del ciclo" queda para
  Fase 2, que además requerirá aprobación con estado y rollback.

## ADR-04 — Trabajar fuera de Google Drive

- **Contexto.** Drive Desktop inyecta `desktop.ini` (incluso dentro de
  `.git`), rompió `git fetch` durante la fusión del repositorio y corrompe los
  providers de Terraform (`missing or corrupted provider plugins`).
- **Decisión.** Clon de trabajo en `C:\Users\santi\dev\PPS-AWS-Fortinet-`;
  `TF_DATA_DIR` fuera del árbol; `desktop.ini` en `.gitignore`. Las copias de
  `G:\Mi unidad\TESIS\PPS prueba\` quedan congeladas.
- **Consecuencias.** (+) Git y Terraform estables; CI reproducible.
  (−) El respaldo pasa a ser GitHub (hay que hacer push); los documentos de
  tesis siguen en Drive, por lo que conviven dos ubicaciones.

## ADR-05 — El executor no tiene acceso al modelo

- **Contexto.** Separación de poderes entre generación y ejecución.
- **Decisión.** Rol `executor` sin `bedrock:*`, sin lectura del bucket de
  políticas, sin `lambda:InvokeFunction`; código stdlib-only que no importa
  `llm_client`/`bedrock_client`. El generador, a su vez, no tiene
  `secretsmanager:*`.
- **Consecuencias.** (+) Un compromiso de cualquiera de los dos roles no
  alcanza el otro lado (ni generar código nuevo, ni tocar el firewall).
  (−) El executor no puede "pedir una corrección" al modelo: un fallo de
  re-validación es terminal (`could_not_audit`), por diseño.

## ADR-06 — Bandera `enable_legacy_nist_schedule` con default `false`

- **Contexto.** El assessor NIST CSF 2.0 original se mantiene como camino de
  repliegue durante la migración.
- **Decisión.** La Lambda `assessor` y su rol se despliegan; la regla y el
  target de EventBridge se crean solo con la bandera en `true`. Default
  `false` desde el hardening de 2026-11-04.
- **Consecuencias.** (+) Rollback sin tocar código; cero ramas NIST en el
  flujo nuevo. (−) Recursos "dormidos" en la cuenta (Lambda, rol, alarma);
  `TESTING.md` todavía describe el default anterior (`true`) y debe corregirse.

## ADR-07 — Modelo `us.anthropic.claude-sonnet-4-6`

- **Contexto.** Se evaluó `claude-sonnet-5-5`; **no está disponible para la
  cuenta 656051538542**. `us.anthropic.claude-sonnet-4-6` figura ACTIVE.
- **Decisión.** `DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"` en
  `bedrock_client.py` y `var.bedrock_model_id` en Terraform; perfil de
  inferencia cross-region (`us.`) y permiso IAM sobre `foundation-model/anthropic.*`
  en todas las regiones destino.
- **Consecuencias.** (+) Cambiar de modelo es una variable, sin tocar código.
  (−) Al cambiar de modelo hay que re-grabar las fixtures de evals
  (`--mode live --record`) y revisar umbrales; cualquier comparación en la
  tesis debe citar `model_id` y fecha.

## ADR-08 — Prompt caching con `cachePoint`

- **Contexto.** El system prompt de map y de reduce es idéntico entre
  llamadas; en el reduce con reintento se repite hasta 3 veces por run.
- **Decisión.** `build_request` envía `system: [{text}, {cachePoint: {type: "default"}}]`
  y `maxTokens` explícito; `ConverseResult` expone `cache_read_tokens` /
  `cache_write_tokens`.
- **Consecuencias.** (+) Menor costo/latencia en prompts repetidos, medible
  en `llm_call`. (−) El `botocore` del venv local (1.35.x) no conoce
  `cachePoint`: los tests mockean el cliente y verifican la forma del payload
  a mano; la validación real ocurre en el runtime de Lambda.

## ADR-09 — Cuota de Bedrock en 0: estrategia

- **Contexto.** La cuenta nueva tiene cuota aplicada 0 para Claude Sonnet 4.6
  (`L-15B8E632` tokens/min, `L-00FF3314` requests/min) → `ThrottlingException:
  Too many tokens per day`. El SDK ya usa `retries={"mode": "adaptive",
  "max_attempts": 5}`, que no resuelve una cuota nula.
- **Decisión.** (1) Pedir el aumento por consola de Service Quotas o AWS
  Support (la CLI rechaza valores por debajo del default). (2) Mientras tanto,
  tratar `could_not_audit` + `bedrock_error`/`ThrottlingException` como
  resultado **válido de la prueba de cableado** (S3 → Lambda → IAM → S3 →
  `aws sync`). (3) Mantener los evals en modo offline como evidencia
  reproducible. (4) No cambiar de región/cuenta ad hoc: el logging de
  invocaciones y el perfil de inferencia están configurados para `us-east-1`.
- **Consecuencias.** La prueba de punta a punta con modelo real y la corrida
  `live` quedan bloqueadas hasta la aprobación de la cuota; el resto del
  sistema (tests, evals offline, IaC, GUI) no depende de ella.
