# 07 — Estado al 2026-11-04 y pendientes

## 1. Qué se hizo (por unidad de trabajo)

Base: clon limpio en `C:\Users\santi\dev\PPS-AWS-Fortinet-`, HEAD `829c101`
("Merge pull request #1 … feature/aws-env-config"). Todo lo siguiente está en
el árbol de trabajo **sin commitear**.

| WU | Alcance | Archivos principales |
|---|---|---|
| 1 — Pipeline sobre Bedrock + remediaciones + observabilidad | `bedrock_client.py` (Converse, `cachePoint`, errores → `BedrockCallError`), `llm_client.py` sobre Bedrock con `remediation` normalizada, `toolkit`/`reporter` con remediación server-side y `remediation_count`, `observability.py` (eventos JSON + EMF), eventos en handlers, `analyzer.py` legacy migrado a Bedrock, `secret_values.py` sin API key | `audit-pipeline/lambda/*.py`, tests nuevos `test_bedrock_client.py`, `test_observability.py`; `SECRETS.md`, `TESTING.md` |
| 2 — Evals + API/desktop | Harness `evals/` (runner offline/live, 3 normativas, fixtures, umbrales, `test_evals_offline.py`), `pps-api aws list-pending|approve`, `summary` en resultados, remediaciones en GUI/Markdown, estado `awaiting_approval` en la app | `audit-pipeline/evals/`, `audit-pipeline/api/`, `desktop/`, `API_CONTRACT.md` |
| 3 — Hardening IaC y repo | `monitoring.tf` (DLQ + alarmas), `bedrock_logging.tf`, lifecycle S3, retención 365 d, VPC opcional del executor, `auto_execute`/`bedrock_model_id`/`enable_bedrock_invocation_logging`, IAM Bedrock por inference-profile, `outputs.tf` único + `next_steps`, `terraform.tfvars.example`, `build_layer.py`, CI `.github/workflows/ci.yml`, `AGENTS.md`/`CLAUDE.md`/`README.md`, `README-LEGACY.md`, `checkov-report.md` | `audit-pipeline/terraform/`, `audit-pipeline/scripts/`, raíz |
| 4 — Documentación y diagramas | `docs/README.md`, `docs/01…07`, `docs/diagrams/*.drawio|png`, informe para la tesis en `G:\Mi unidad\TESIS\FASE1-INFORME-PARA-TESIS.md` | `docs/` |

## 2. Números de verificación

| Verificación | Resultado |
|---|---|
| `pytest` en `audit-pipeline/` (Windows) | 275 passed, 1 skipped (`SIGALRM`) |
| `pytest` en `audit-pipeline/api/` | 30 passed |
| `pytest` en `desktop/` (Qt offscreen) | 45 passed |
| `ruff check` / `ruff format --check` | limpio en lo tocado |
| `terraform fmt -check`, `init -backend=false`, `validate` | OK (Terraform 1.15.9, provider aws 5.100.0) |
| `checkov` sobre `audit-pipeline/terraform` | 109 passed / 29 failed, todos justificados en `checkov-report.md` |
| `evals/run_evals.py --mode offline` | 3/3 ok, first-attempt pass rate 0.67, recall/precisión/remediación 1.00 |

## 3. Hechos de la cuenta AWS

- Cuenta `656051538542`, usuario IAM `SantiUsuarioDePrueba1`
  (AdministratorAccess), perfil local `pps-tesis`, región `us-east-1`.
- Bedrock: formulario de caso de uso enviado y aceptado;
  `us.anthropic.claude-sonnet-4-6` ACTIVE; `claude-sonnet-5-5` no disponible
  para la cuenta; **cuota aplicada 0** → `ThrottlingException: Too many
  tokens per day`.
- Sin FortiGate ni VPN. VPC default `172.31.0.0/16` y
  `vpc-0542264dd516d931e` `10.42.0.0/16`.
- Model Invocation Logging no existía antes; Terraform lo crea con
  `enable_bedrock_invocation_logging=true` (no pisa nada).
- Infra del pipeline: **no desplegada** en esta sesión (solo `validate`).

## 4. Pendientes

| # | Pendiente | Responsable / cómo | Bloquea |
|---|---|---|---|
| P1 | Aumento de cuota Bedrock (`L-15B8E632`, `L-00FF3314`) | Consola Service Quotas o AWS Support (`02-…md` §4.3) | Prueba E2E con modelo real, evals `live`, métricas para la tesis |
| P2 | `terraform apply` del pipeline | Dueño de la cuenta, `02-…md` §6 | Todo lo operativo |
| P3 | Conectar un FortiGate (opción b recomendada para la tesis) | `06-conexion-fortigate.md` | Hallazgos reales (`pass`/`fail`) |
| P4 | Commit y push de los WU 1-4 | `02-…md` §13; borrar/ignorar `audit-pipeline/terraform/tfplan` antes | Respaldo y CI |
| P5 | Extender el catálogo (`system/password-policy`, `system/ntp`, `log.*`) + re-grabar evals | `fortigate_client.ENDPOINTS`, `evals/` | Cobertura de 2 de las 3 normativas |
| P6 | Reevaluar `claude-sonnet-5-5` cuando esté disponible | Cambiar `bedrock_model_id`, re-grabar fixtures, comparar métricas | Mejora opcional |
| P7 | Decidir si el generador debe notificar sus fallos por SNS | Hoy escribe solo en S3 (sin `sns:Publish` por mínimo privilegio). Si se decide que sí: añadir permiso + `SNS_TOPIC_ARN` al generador y usar `deliver_policy_report`; si no, dejar documentado | UX del operador ante `could_not_audit` del generador |
| P8 | Step Functions (Fase 2): compuerta de aprobación con `waitForTaskToken`, map paralelo para normativas largas | `05-decisiones.md` ADR-02 | — |
| P9 | Muro de red: executor en VPC con SG de egreso restringido + endpoints S3/Secrets/SNS | `executor_subnet_ids` / `executor_security_group_ids` | Limitación documentada |
| P10 | Ejecutar y documentar el test del backstop `SIGALRM` en Linux (job `lambda` de CI: 276 passed esperados) | Primer push → CI | Evidencia de la segunda capa de wall-clock |
| P11 | Exponer `FORTIGATE_VERIFY_SSL` como variable Terraform (hoy solo configurable editando `lambda.tf`) | `variables.tf` + `lambda.tf` + test de contrato env | Laboratorios con certificado autofirmado |
| P12 | Correcciones menores de documentación detectadas: `TESTING.md` dice que `enable_legacy_nist_schedule` es `true` por defecto; comentario de `secrets.tf` sugiere que `host` del secret reemplaza a `FORTIGATE_HOST`; `.env.example` no lista `PPS_EXECUTOR_FUNCTION`; `README.md` dice "docs/README.md (en preparación)" | Edición puntual | — |

## 5. Cómo retomar

1. Abrir una terminal en `C:\Users\santi\dev\PPS-AWS-Fortinet-` (nunca en
   Drive). `git status --short` para ver el estado.
2. Releer `AGENTS.md` (reglas) y `docs/README.md` (índice).
3. Verificar el entorno: `audit-pipeline` → `..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`
   (275/1) y `evals\run_evals.py --mode offline`.
4. Consultar la cuota: comando de `02-…md` §4.3. Si ya no es 0, correr
   `evals/run_evals.py --mode live` y guardar el JSON de `results/` como
   evidencia (fecha, `model_id`, tokens).
5. Seguir el runbook `02-…md` desde la sección 5 (layer) en adelante.
6. Publicar (`02-…md` §13) y confirmar CI en verde.

## 6. Actualización (WU 5)

- **Infra desplegada** (`terraform apply`) en la cuenta `656051538542`,
  región `us-east-1`: 42 recursos. Lambdas `pps-prod-policy-generator`,
  `pps-prod-audit-executor` y `pps-prod-assessor`; buckets
  `pps-prod-policies-656051538542` y `pps-prod-reports-656051538542`. La
  suscripción SNS sigue **pendiente de confirmación**. P2 queda cerrado.
- **Prueba E2E** ejecutada dos veces por el camino completo (app de
  escritorio → `pps-api aws dispatch` → S3 → `policy_generator`). Ambas
  terminaron en `status=could_not_audit` / `failure_reason=bedrock_error`
  (`ThrottlingException`, cuota de Bedrock todavía en 0, ver P1); el
  `report.json` de fallo se sincronizó correctamente en la API local con
  `pps-api aws sync`, lo que valida el circuito S3 ↔ API ↔ GUI.
- **Catálogo ampliado** (P5 cerrado): `fortigate_client.ENDPOINTS` pasa de
  11 a 31 labels GET-only (`password_policy`, `ntp`, `log_syslogd`,
  `log_fortianalyzer`, `log_settings`, `log_memory`, `admin_profiles`,
  `api_users`, `ha`, `fortiguard`, `snmp_sysinfo`, `vdom_settings`,
  `central_management`, `firewall_addresses`, `static_routes`, `sdwan`,
  `ldap_servers`, `radius_servers`, `dhcp_servers`, `ssl_ssh_profiles`).
  Las fixtures offline de evals se reescribieron a mano contra el nuevo
  catálogo (contraseñas 5→9 checks, registro/NTP 4→8); re-grabar en modo
  `live` cuando haya cuota.
- **`fortigate_verify_ssl`** expuesta como variable Terraform e inyectada
  como `FORTIGATE_VERIFY_SSL` en executor y assessor (P11 cerrado). P12
  (correcciones de documentación) aplicado, salvo `.env.example`, que se
  edita a mano (ver `02-…md` §9.3).
- **Gotcha IAM**: la descripción de un rol/política IAM rechaza caracteres
  fuera de Latin-1; un guion largo (U+2014) en `description` hacía fallar el
  `apply` con `ValidationError`. Corregido en los `.tf` (solo ASCII/Latin-1
  en descripciones IAM).
