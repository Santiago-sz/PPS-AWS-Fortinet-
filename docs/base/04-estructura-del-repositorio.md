# 04 — Estructura del repositorio

Diagrama: `diagrams/05-componentes-y-repositorio.png`. Repositorio:
https://github.com/Santiago-sz/PPS-AWS-Fortinet- (rama `master`).

```text
PPS-AWS-Fortinet-/
├── .github/workflows/ci.yml        CI: lambda (ruff+pytest), api, desktop (Qt offscreen),
│                                   terraform (layer+fmt+validate+checkov soft-fail), evals-offline
├── .env.example                    Plantilla de .env para `pps-api aws ...` (perfil/buckets)
├── .gitignore                      desktop.ini, .venv*, .pps-api, layers/, *.tfvars, .env, …
├── AGENTS.md                       Contrato para agentes/colaboradores: mapa, reglas del harness,
│                                   contrato env/IAM, comandos, definición de terminado
├── CLAUDE.md                       Redirige a AGENTS.md
├── README.md                       Presentación del proyecto y enlaces
├── SPEC_GUI_PPS_AWS_FORTINET.md    Especificación funcional de la GUI (v1.1)
│
├── audit-pipeline/                 ★ CÓDIGO CANÓNICO del pipeline
│   ├── lambda/                     Código de las tres Lambdas (archivos planos, un zip común)
│   │   ├── handler_generator.py    Entrypoint policy_generator (S3 → extract → chunk → map/reduce → firmar → invocar)
│   │   ├── handler_executor.py     Entrypoint audit_executor (integridad → re-validar → sandbox → reporte)
│   │   ├── handler.py              Entrypoint assessor NIST legacy (schedule apagado por defecto)
│   │   ├── extractor.py            PDF/DOCX → texto + metadata (pypdf, python-docx); falla explícita
│   │   ├── chunker.py              Chunks por cláusula + retrieval TF-IDF de respaldo
│   │   ├── llm_client.py           Prompts MAP/REDUCE, map/reduce, reintento con feedback (≤3), MAX_MAP_CALLS=12
│   │   ├── bedrock_client.py       Transporte Converse sobre Bedrock (cachePoint, maxTokens, eventos llm_call)
│   │   ├── script_validator.py     Allowlist AST + caps estáticas + contrato de check_id
│   │   ├── sandbox.py              Namespace restringido + presupuestos (120 s / 40 calls / 500 findings)
│   │   ├── toolkit.py              Capabilities `fgt` y `report` (clause_ref/remediation server-side)
│   │   ├── fortigate_client.py     Cliente REST GET-only sobre ENDPOINTS (31 labels, /api/v2/cmdb)
│   │   ├── reporter.py             Reporte Markdown/JSON/SNS (legacy NIST + policy-agnostic)
│   │   ├── s3_io.py                get/put de policy, script (SHA-256), manifest, report
│   │   ├── observability.py        log_event (JSON), emit_metric (EMF), Timer
│   │   ├── analyzer.py             Análisis NIST legacy (sin cambios funcionales)
│   │   ├── secret_values.py        Parseo del SecretString ({"token": ...})
│   │   ├── requirements.txt        pypdf / python-docx / lxml pineados = layer
│   │   └── tests/                  275 tests (Windows: 275 passed, 1 skipped)
│   ├── api/                        API HTTP local (loopback) + puente AWS
│   │   ├── pps_api/__main__.py     CLI `pps-api`: serve | import-result | aws dispatch|sync|list-pending|approve
│   │   ├── pps_api/server.py       Servidor HTTP (127.0.0.1, sin OIDC) — contrato desktop/API_CONTRACT.md
│   │   ├── pps_api/service.py      Dominio + SQLite (.pps-api/development.sqlite3), saneado, summary
│   │   ├── pps_api/aws_bridge.py   dispatch (PutObject policies/), sync (reports/ → SQLite), list-pending, approve
│   │   ├── pps_api/config.py       Lector literal de .env (claves permitidas)
│   │   ├── launch.py, pyproject.toml, README.md
│   │   └── tests/                  30 tests (HTTP real en loopback, Moto para S3)
│   ├── terraform/                  Infra AWS canónica (TF ≥ 1.5, provider aws ~> 5.0)
│   │   ├── main.tf                 providers, default_tags, local.prefix = "${project_name}-${environment}"
│   │   ├── variables.tf            notification_email, fortigate_host, bedrock_model_id, auto_execute,
│   │   │                           executor_subnet_ids/security_group_ids, enable_bedrock_invocation_logging,
│   │   │                           retenciones, timeouts, presupuestos del sandbox, enable_legacy_nist_schedule
│   │   ├── lambda.tf               archive_file, layer doc_parsers, 3 Lambdas + log groups, schedule legacy (count)
│   │   ├── iam.tf                  3 roles de mínimo privilegio (lambda_execution, generator, executor) + VPC opcional
│   │   ├── storage.tf              buckets reports/policies (versioning, PAB, SSE, lifecycle), notificación S3, SNS
│   │   ├── secrets.tf              Secret del token FortiGate (placeholder + ignore_changes)
│   │   ├── monitoring.tf           DLQ SQS por función + alarmas Errors/DLQ
│   │   ├── bedrock_logging.tf      Model Invocation Logging (único por cuenta/región)
│   │   ├── outputs.tf              Set único de outputs + next_steps
│   │   ├── terraform.tfvars.example
│   │   └── .terraform.lock.hcl     (tfplan sin seguimiento: no commitear)
│   ├── evals/                      Harness de evaluación del generador
│   │   ├── run_evals.py            Runner offline/live/--record; métricas; umbrales
│   │   ├── policies/*.md           3 normativas sintéticas
│   │   ├── expected/*.json         Checks esperados (keywords, endpoints_any, min/max_checks)
│   │   ├── recorded/*.json         Respuestas grabadas del modelo (fixtures offline)
│   │   ├── thresholds.json, results/ (ignorado), README.md
│   ├── scripts/                    build_layer.py (recomendado en Windows) / build_layer.sh / layer-requirements.txt
│   ├── layers/                     (generado, ignorado) pps-doc-parsers.zip
│   ├── pyproject.toml              ruff + pytest (pythonpath = lambda)
│   ├── requirements-dev.txt
│   ├── TESTING.md, SECRETS.md, checkov-report.md
│
├── desktop/                        App de escritorio PySide6 (consola de auditorías, sin credenciales AWS)
│   ├── pps_desktop/app.py          UI principal (Resumen, Políticas, Análisis, Resultados, Configuración)
│   ├── pps_desktop/domain.py       Cálculos (cobertura, cumplimiento, estados, remediaciones), etiquetas de estado
│   ├── pps_desktop/api.py          Cliente HTTP del contrato (OIDC+PKCE o API local)
│   ├── pps_desktop/storage.py      Caché cifrada (Fernet + keyring), QSettings
│   ├── pps_desktop/widgets.py, demo.py, assets/
│   ├── scripts/Build-Windows.ps1, Install-PPS.ps1, capture.py
│   ├── docs/VALIDATION.md, *.png   Evidencia de validación de la GUI
│   ├── tests/                      45 tests (Qt offscreen)
│   ├── API_CONTRACT.md             Contrato REST que la API local implementa
│   ├── PPS-Desktop.spec, pyproject.toml, README.md, launch.py
│
├── docs/                           Esta documentación + diagrams/*.drawio|png
│
├── fortigate-sandbox-2026-06-07/   Terraform independiente: FortiGate-VM64 on-demand en AWS
│   ├── main.tf                     VPC 10.0.0.0/16 (UNNE-Sandbox-VPC), subnet pública, SG 443, EC2 c5.large
│   ├── iam.tf                      Rol ReadOnlyAccess para Fabric Connector
│   ├── provider.tf                 Región sa-east-1 (distinta de la del pipeline)
│   ├── outputs.tf, README.md, .terraform.lock.hcl
│
├── lambda/                         ⚠ LEGACY (copia obsoleta del assessor NIST). Ver lambda/README-LEGACY.md.
│                                   No editar, no borrar; ningún Terraform la empaqueta.
└── terraform/                      ⚠ LEGACY (Terraform original de una sola Lambda). Ver terraform/README-LEGACY.md.
```

## Reglas de ubicación

| Necesidad | Dónde |
|---|---|
| Cambiar comportamiento de las Lambdas | `audit-pipeline/lambda/` + tests en `audit-pipeline/lambda/tests/` |
| Cambiar infraestructura | `audit-pipeline/terraform/` (+ `checkov-report.md` si cambia el resultado) |
| Cambiar el contrato GUI ↔ API | `desktop/API_CONTRACT.md` y, en el mismo cambio, `audit-pipeline/api/` y `desktop/` |
| Agregar un endpoint FortiGate auditable | `fortigate_client.ENDPOINTS` (y re-grabar evals) — nunca el validador ni el sandbox |
| Agregar una normativa de prueba | `audit-pipeline/evals/{policies,expected,recorded}/` |
| Documentación operativa | `docs/` (esta carpeta); `TESTING.md`/`SECRETS.md`/`evals/README.md` siguen siendo canónicos para su tema |

## Copias obsoletas fuera del repositorio

`G:\Mi unidad\TESIS\PPS prueba\` (carpetas `lambda`, `terraform`, `scripts`,
`P-Terraform-Forti-AWS`, `.venv`) es el prototipo anterior a la fusión en
GitHub y **no contiene** el trabajo de 2026-11-04. Se conserva solo como
historial; el clon de trabajo es `C:\Users\santi\dev\PPS-AWS-Fortinet-`.
