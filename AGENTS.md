# AGENTS.md — guía para agentes de código

Este archivo es el contrato de trabajo para cualquier agente (Claude Code,
Codex, Copilot, etc.) que edite este repositorio. Leerlo completo antes de
tocar código. `CLAUDE.md` en la raíz solo redirige acá.

## 1. Qué es este repositorio

Sistema de auditoría de postura de seguridad para firewalls FortiGate,
desarrollado como proyecto de tesis / PPS. A partir de una **normativa en
PDF/DOCX** subida a S3, un modelo en Amazon Bedrock (Claude) extrae los
controles verificables y genera un **script Python de auditoría de solo
lectura**; ese script se valida estáticamente, se ejecuta en un sandbox que
solo expone `fgt.get(<endpoint>)` y `report.finding(...)`, consulta la REST
API del FortiGate y produce un reporte (`report.md` / `report.json`) con
hallazgos que citan la cláusula de la normativa y **remediaciones
propuestas** (nunca aplicadas). Una app de escritorio y una API local
permiten revisar los resultados sin credenciales AWS.

## 2. Mapa de carpetas

| Ruta | Qué es | Estado |
|---|---|---|
| `audit-pipeline/lambda/` | Código de las tres Lambdas (`handler_generator.py`, `handler_executor.py`, `handler.py` legacy NIST) y módulos: `extractor`, `chunker`, `llm_client`, `bedrock_client`, `script_validator`, `sandbox`, `toolkit`, `fortigate_client`, `reporter`, `s3_io`, `observability`. Tests en `lambda/tests/`. | **Canónico** |
| `audit-pipeline/terraform/` | Infra AWS (S3, Lambdas, IAM mínimo privilegio, SQS DLQ, alarmas, logging de Bedrock). | **Canónico** |
| `audit-pipeline/api/` | API HTTP local de desarrollo (`pps-api serve`) y puente a AWS (`pps-api aws dispatch|sync|list-pending|approve`). | Canónico |
| `audit-pipeline/evals/` | Harness de evaluación del generador (normativas sintéticas, fixtures grabadas, métricas, umbrales). | Canónico |
| `audit-pipeline/scripts/` | `build_layer.py` / `build_layer.sh` (Lambda Layer pypdf+python-docx+lxml). | Canónico |
| `desktop/` | App de escritorio PySide6 (consola de auditorías; sin credenciales AWS). | Canónico |
| `fortigate-sandbox-2026-06-07/` | Terraform de un FortiGate VM de laboratorio en AWS (entorno de pruebas). | Independiente |
| `lambda/`, `terraform/` (raíz) | **Copias legacy obsoletas** del pipeline original. Ver `README-LEGACY.md` en cada una. | **No editar, no borrar** |
| `docs/` | Documentación de operación (puede no existir todavía). | — |

## 3. Reglas del harness (no negociables)

1. **Nunca debilitar `script_validator.py` ni `sandbox.py`.** El validador
   es un *allowlist* de nodos AST, nombres y métodos (`fgt.get/endpoints`,
   `report.finding/note`); el sandbox impone presupuestos duros de tiempo,
   llamadas y hallazgos. No agregar nodos, builtins ni atributos al
   allowlist, no capturar `SandboxBudgetExceeded`, no permitir `try`,
   `while`, `import`, dunders ni reflexión. Si un script generado "necesita"
   algo que el validador rechaza, el que cambia es el prompt o el catálogo
   de endpoints, nunca el validador. El corpus adversarial de
   `test_script_validator.py` debe seguir fallando como falla.
2. **Los scripts generados son de solo lectura.** `fortigate_client` solo
   hace GET sobre `ENDPOINTS`; `fgt.get()` solo acepta labels de ese
   catálogo. No agregar métodos de escritura al cliente ni al toolkit.
3. **Las remediaciones son propuestas.** `remediation.{summary,steps,
   fortigate_cli}` se muestran en el reporte; nada en el sistema las
   ejecuta. No agregar código que aplique configuración al FortiGate.
4. **`audit_executor` no tiene acceso al modelo.** Su rol IAM no tiene
   `bedrock:*` y su código no importa `llm_client`/`bedrock_client`. El
   generador, a su vez, no tiene acceso al secret del FortiGate. No
   mezclar estos roles.
5. **El executor re-valida de forma independiente** (`script_sha256` +
   `script_validator.validate`) antes de ejecutar. No eliminar esa doble
   verificación "porque el generador ya validó".
6. **Las funciones del flujo NIST legacy** (`handler.py`, `analyzer.py` y
   las funciones legacy de `reporter.py`/`fortigate_client.collect_all`)
   se mantienen **byte-idénticas** salvo tarea explícita. El flujo se
   despliega pero su schedule está apagado por defecto
   (`enable_legacy_nist_schedule=false`).
7. **Nunca truncar contenido de la normativa.** `llm_client` genera más
   llamadas de map antes que cortar texto; respetar `MAX_MAP_CALLS` y
   fallar explícito.
8. **Los tests deben seguir en verde**, y los que verifican contratos
   IaC↔código (`test_handler.py::TestTerraformEnvVarsMatchHandler`) se
   actualizan junto con `terraform/lambda.tf`, no se borran.
9. **Secretos**: el único secreto es el token de FortiGate en Secrets
   Manager (placeholder en Terraform, valor real cargado a mano, `lifecycle
   ignore_changes`). No hay API keys de Anthropic: el modelo se invoca por
   IAM. Nunca escribir credenciales en `.tf`, `.py`, fixtures ni docs.
10. **Infra**: no correr `terraform apply`/`plan` contra AWS ni comandos
    `aws` mutantes sin pedido explícito del dueño del repo. `validate` con
    `-backend=false` y `TF_DATA_DIR` fuera del árbol es lo que se usa para
    verificar.

## 4. Contrato de entorno e IAM (resumen)

| Lambda | Env requeridas | Env opcionales | IAM (mínimo privilegio) |
|---|---|---|---|
| `policy_generator` (`handler_generator.lambda_handler`, 900 s, 1024 MB, layer `pps-doc-parsers`) | `S3_BUCKET`, `EXECUTOR_FUNCTION_NAME` | `BEDROCK_MODEL_ID`, `AUTO_EXECUTE`, `MAX_GENERATION_ATTEMPTS`, `POLICIES_BUCKET`, `LOG_LEVEL` | `bedrock:InvokeModel*` (anthropic.* + inference-profile), `s3:GetObject/ListBucket` en policies, `s3:PutObject` en `reports/artifacts/*` y `reports/reports/*`, `lambda:InvokeFunction` executor, `sqs:SendMessage` su DLQ, logs |
| `audit_executor` (`handler_executor.lambda_handler`, 300 s, 512 MB, stdlib-only) | `FORTIGATE_HOST`, `FORTIGATE_SECRET_ARN`, `S3_BUCKET`, `SNS_TOPIC_ARN` | `FORTIGATE_VERIFY_SSL`, `SANDBOX_WALL_CLOCK_SECONDS`, `SANDBOX_MAX_FGT_CALLS`, `LOG_LEVEL` | `secretsmanager:GetSecretValue` (solo el secret FortiGate), `s3:GetObject` `artifacts/*`, `s3:PutObject` `reports/*`, `sns:Publish`, `sqs:SendMessage` su DLQ, logs; `AWSLambdaVPCAccessExecutionRole` solo si `executor_subnet_ids` no está vacío |
| `assessor` legacy (`handler.lambda_handler`) | `FORTIGATE_HOST`, `FORTIGATE_SECRET_ARN`, `S3_BUCKET`, `SNS_TOPIC_ARN` | `BEDROCK_MODEL_ID`, `ENVIRONMENT`, `FORTIGATE_VERIFY_SSL`, `LOG_LEVEL` | secret FortiGate, Bedrock, `s3:PutObject` reports, `sns:Publish`, logs |

Observabilidad: eventos JSON por stdout (`llm_call`, `generation_result`,
`generator_result`, `awaiting_approval`, `executor_result`) y métricas EMF
en el namespace `PPS/AuditPipeline`. Logging de invocaciones de Bedrock
(`bedrock_logging.tf`) es **account-wide por región**.

## 5. Comandos

Todo desde `audit-pipeline/` con el venv de la raíz (`../.venv`), detalle en
`audit-pipeline/TESTING.md`:

```bash
../.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider        # 275 passed, 1 skipped (Windows)
../.venv/Scripts/python.exe -m ruff check lambda/ evals/ scripts/build_layer.py
../.venv/Scripts/python.exe -m ruff format --check lambda/ evals/ scripts/build_layer.py
../.venv/Scripts/python.exe scripts/build_layer.py                    # layers/pps-doc-parsers.zip
TF_DATA_DIR=C:/Users/<usuario>/.terraform-data/pps-audit-pipeline terraform -chdir=terraform fmt -check -recursive
TF_DATA_DIR=... terraform -chdir=terraform init -backend=false && TF_DATA_DIR=... terraform -chdir=terraform validate
PYTHONUTF8=1 ../.venv/Scripts/python.exe -m checkov.main -d terraform --framework terraform --compact
../.venv/Scripts/python.exe evals/run_evals.py --mode offline
```

API y desktop: `pip install -e "audit-pipeline/api[dev]"` + `pytest` en
`audit-pipeline/api`; `pip install -e "desktop[dev]"` + `QT_QPA_PLATFORM=offscreen pytest`
en `desktop`.

## 6. Definición de terminado

Un cambio está terminado cuando, además de cumplir la tarea:

- [ ] `pytest` en `audit-pipeline/` en verde (sin bajar el número de tests
      salvo que la tarea lo pida), y `api`/`desktop` si se tocaron.
- [ ] `ruff check` y `ruff format --check` limpios en lo tocado.
- [ ] `terraform fmt -check` + `init -backend=false` + `validate` en verde
      si se tocó `terraform/`; `checkov-report.md` actualizado si cambió el
      resultado de checkov.
- [ ] `evals/run_evals.py --mode offline` sale con código 0 (y las
      fixtures re-grabadas si cambió el prompt, el modelo o el catálogo).
- [ ] Documentación tocada en el mismo cambio (`TESTING.md`, `SECRETS.md`,
      `evals/README.md`, este archivo) y comentarios en español neutro
      profesional; identificadores de código en inglés.
- [ ] Sin commits ni cambios de estado Git salvo pedido explícito; sin
      `terraform apply`, sin comandos `aws` mutantes.
