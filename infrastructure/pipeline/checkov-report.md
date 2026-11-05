# Reporte Checkov — Análisis estático de Terraform

Reverificación de la reorganización, 2026-11-05, con Checkov 3.2.379:
pipeline **109 passed / 29 failed / 0 skipped** y laboratorio **18 passed /
9 failed / 0 skipped**, sin errores de parseo. Esta migración no corrige los
hallazgos existentes. Rutas vigentes: `infrastructure/pipeline/` e
`infrastructure/fortigate-lab/`; procedimientos en `audit-engine/TESTING.md`.
Las rutas del resto del informe son referencias históricas.

Generado con `checkov` 3.2.379, análisis de solo lectura (sin `terraform apply`/`plan`,
sin fixes automáticos aplicados). Se corrió por separado sobre los dos directorios
Terraform independientes del proyecto.

Comando usado (desde `audit-pipeline/`, con el `.venv` de la raíz del repo activo):

```bash
PYTHONUTF8=1 python -m checkov.main -d terraform --output json
PYTHONUTF8=1 python -m checkov.main -d ../fortigate-sandbox-2026-06-07 --output json
```

> Nota de entorno: en este equipo hubo que forzar `PYTHONUTF8=1` porque la
> codificación por defecto de Python en Windows (cp1252) no puede leer los
> comentarios en español/UTF-8 de los `.tf` (tildes, emes, guiones largos) y
> checkov rompía con `UnicodeDecodeError`. Ver `TESTING.md` para el detalle.

---

## 0. Corrida 2026-11-04 — `audit-pipeline/terraform/` (hardening Work Unit 3)

Comando (desde `audit-pipeline/`, mismo `checkov` 3.2.379):

```bash
PYTHONUTF8=1 ../.venv/Scripts/python.exe -m checkov.main -d terraform --framework terraform --compact
```

**Passed: 109 | Failed: 29 | Skipped: 0** (la corrida anterior sobre este
mismo directorio daba 29/18 con 17 recursos; ahora hay más recursos — DLQ,
alarmas, lifecycle, logging de Bedrock — y por eso más checks totales).

Resueltos respecto de la corrida anterior:

| Check | Qué se hizo |
|---|---|
| CKV_AWS_338 (retención de logs < 1 año) | `var.log_retention_days` = 365 en los cuatro log groups |
| CKV2_AWS_61 (bucket sin lifecycle) | `aws_s3_bucket_lifecycle_configuration` en `reports` (expiran `artifacts/*` y `reports/*` a 365 d, no-vigentes a 30 d, multipart a 7 d) y en `policies` (no-vigentes a 90 d) |
| CKV_AWS_116 (sin DLQ) en `policy_generator` y `audit_executor` | SQS DLQ por función (`monitoring.tf`) + `dead_letter_config` + `sqs:SendMessage` acotado |
| CKV_AWS_117 (fuera de VPC) en `audit_executor` | `dynamic "vpc_config"` opcional (`executor_subnet_ids` / `executor_security_group_ids`) |
| Cifrado de las colas SQS nuevas | `sqs_managed_sse_enabled = true` (ningún hallazgo nuevo sobre SQS) |

Pendientes (29), agrupados, con la razón de no cerrarlos en esta iteración:

| Check | Recursos | Motivo |
|---|---|---|
| CKV_AWS_26 (SNS sin KMS) | `notifications` | Con la clave administrada `alias/aws/sns` las alarmas de CloudWatch **no pueden publicar** (requiere una CMK con key policy para `cloudwatch.amazonaws.com`). Cerrarlo implica crear y pagar una CMS; diferido. |
| CKV_AWS_115 (sin reserved concurrency) | 3 Lambdas | Reservar concurrencia exige ≥ 100 de concurrencia no reservada libre en la cuenta; en cuentas nuevas (límite 10) el apply falla. Diferido hasta confirmar la cuota. |
| CKV_AWS_116 (sin DLQ) | `assessor` | Flujo legacy, invocación síncrona manual o por schedule; sin reintentos asíncronos que justifiquen DLQ. |
| CKV_AWS_117 (fuera de VPC) | `assessor`, `policy_generator` | `policy_generator` no habla con el FortiGate; `assessor` es legacy. Solo el executor tiene colocación en VPC opcional. |
| CKV_AWS_50 (X-Ray), CKV_AWS_272 (code signing), CKV_AWS_173 (env vars con CMK) | 3 Lambdas | Hardening con costo/complejidad adicional (CMK, perfil de firma); no hay secretos en env vars (van por Secrets Manager). Diferido. |
| CKV_AWS_158 (log groups con KMS), CKV_AWS_145 (S3 con KMS), CKV_AWS_149 (secret con CMK) | log groups, buckets, secret | Todo está cifrado con claves administradas por AWS; pasar a CMK es una decisión de costo/gobierno fuera de alcance. |
| CKV_AWS_18 (access logging), CKV_AWS_144 (replicación cross-region), CKV2_AWS_62 (notificaciones en `reports`) | buckets | `reports` no debe disparar notificaciones (evita el loop generator↔executor, ver storage.tf). Logging/replicación: diferidos. |
| CKV2_AWS_57 (rotación del secret) | `fortigate_token` | El token lo emite el FortiGate; no hay rotador automático. Rotación manual documentada en SECRETS.md. |

---

## 1. `terraform/` (infra del pipeline de auditoría) — corrida anterior

**Passed: 29 | Failed: 18 | Skipped: 0 | Resources: 17**

### Hallazgos FAILED

| Check ID | Descripción | Recurso | Archivo |
|---|---|---|---|
| CKV_AWS_158 | CloudWatch Log Group no cifrado con KMS (usa cifrado por defecto de CloudWatch) | `aws_cloudwatch_log_group.lambda` | lambda.tf:46-55 |
| CKV_AWS_338 | Retención de logs de CloudWatch menor a 1 año (está en 30 días) | `aws_cloudwatch_log_group.lambda` | lambda.tf:46-55 |
| CKV_AWS_272 | Lambda sin code-signing configurado | `aws_lambda_function.assessor` | lambda.tf:65-109 |
| CKV_AWS_116 | Lambda sin Dead Letter Queue (DLQ) configurada | `aws_lambda_function.assessor` | lambda.tf:65-109 |
| CKV_AWS_173 | Variables de entorno de Lambda no cifradas con KMS CMK propia | `aws_lambda_function.assessor` | lambda.tf:65-109 |
| CKV_AWS_115 | Lambda sin límite de concurrencia a nivel función | `aws_lambda_function.assessor` | lambda.tf:65-109 |
| CKV_AWS_117 | Lambda no está dentro de una VPC | `aws_lambda_function.assessor` | lambda.tf:65-109 |
| CKV_AWS_50 | X-Ray tracing no habilitado en Lambda | `aws_lambda_function.assessor` | lambda.tf:65-109 |
| CKV_AWS_149 | Secret de Secrets Manager (FortiGate token) sin KMS CMK propia | `aws_secretsmanager_secret.fortigate_token` | secrets.tf:23-32 |
| CKV_AWS_149 | ~~Secret de Secrets Manager (Claude API key) sin KMS CMK propia~~ — resuelto: el recurso se eliminó al migrar el modelo a Amazon Bedrock (acceso vía IAM, sin API key) | `aws_secretsmanager_secret.claude_api_key` (eliminado) | — |
| CKV_AWS_26 | Topic SNS sin cifrado de datos en reposo | `aws_sns_topic.notifications` | storage.tf:109-112 |
| CKV2_AWS_62 | Bucket S3 sin notificaciones de eventos habilitadas | `aws_s3_bucket.reports` | storage.tf:23-30 |
| CKV2_AWS_57 | Secret FortiGate sin rotación automática | `aws_secretsmanager_secret.fortigate_token` | secrets.tf:23-32 |
| CKV2_AWS_57 | ~~Secret Claude sin rotación automática~~ — resuelto: recurso eliminado (modelo vía Bedrock/IAM) | `aws_secretsmanager_secret.claude_api_key` (eliminado) | — |
| CKV2_AWS_61 | Bucket S3 sin lifecycle configuration | `aws_s3_bucket.reports` | storage.tf:23-30 |
| CKV_AWS_18 | Bucket S3 sin access logging habilitado | `aws_s3_bucket.reports` | storage.tf:23-30 |
| CKV_AWS_144 | Bucket S3 sin cross-region replication | `aws_s3_bucket.reports` | storage.tf:23-30 |
| CKV_AWS_145 | Bucket S3 no cifrado con KMS por defecto (usa AES256 por defecto de S3) | `aws_s3_bucket.reports` | storage.tf:23-30 |

**Lectura general:** ninguno de estos 18 es un hallazgo "sorpresa" grave — son
en su mayoría hardening opcional esperable en un pipeline de auditoría
académico/piloto (KMS CMK propia vs. cifrado gestionado por AWS, DLQ, X-Ray,
rotación de secrets, VPC para la Lambda, lifecycle de S3). Los checks de IAM
(29 PASSED) confirman que el rol de ejecución de la Lambda sigue principio de
mínimo privilegio — no hay `*:*`, no hay `AdministratorAccess`, no hay
escalación de privilegios ni exposición de credenciales.

---

## 2. `fortigate-sandbox-2026-06-07/` (sandbox FortiGate-on-AWS, antes `P-Terraform-Forti-AWS`)

**Passed: 18 | Failed: 9 | Skipped: 0 | Resources: 10**

### Hallazgos FAILED

| Check ID | Descripción | Recurso | Archivo |
|---|---|---|---|
| CKV_AWS_130 | Subnet pública asigna IP pública por defecto | `aws_subnet.public_subnet` | main.tf:12-16 |
| CKV_AWS_23 | Security Group sin descripción en la regla | `aws_security_group.allow_fgt` | main.tf:32-49 |
| CKV_AWS_382 | Egress del Security Group abierto a `0.0.0.0/0` en todos los puertos (`protocol = "-1"`) | `aws_security_group.allow_fgt` | main.tf:32-49 |
| CKV_AWS_126 | Monitoreo detallado no habilitado en la instancia EC2 | `aws_instance.fortigate` | main.tf:64-77 |
| CKV_AWS_135 | Instancia EC2 no es EBS-optimized | `aws_instance.fortigate` | main.tf:64-77 |
| CKV_AWS_79 | IMDSv1 habilitado (debería forzarse IMDSv2) | `aws_instance.fortigate` | main.tf:64-77 |
| CKV_AWS_8 | Volúmenes EBS de la instancia no cifrados | `aws_instance.fortigate` | main.tf:64-77 |
| CKV2_AWS_11 | VPC sin flow logging habilitado | `aws_vpc.sandbox_vpc` | main.tf:2-6 |
| CKV2_AWS_12 | Security Group por defecto de la VPC no restringe todo el tráfico | `aws_vpc.sandbox_vpc` | main.tf:2-6 |

### Sobre el Security Group abierto a `0.0.0.0/0` en el puerto 443

**Confirmado en el código** (`fortigate-sandbox-2026-06-07/main.tf`, recurso
`aws_security_group.allow_fgt`):

```hcl
ingress {
  from_port   = 443
  to_port     = 443
  protocol    = "tcp"
  cidr_blocks = ["0.0.0.0/0"]
}
```

**Checkov NO lo detecta como hallazgo FAILED específico.** El ruleset
open-source de checkov trae checks dedicados de "ingress abierto a
0.0.0.0/0" solo para puertos 22 (CKV_AWS_24), 3389 (CKV_AWS_25), 80
(CKV_AWS_260) y "todos los puertos" con protocolo `-1` (CKV_AWS_277) — los
cuatro **PASARON** para este Security Group porque la única regla de ingress
que tiene es específicamente el puerto 443, no matchea ninguno de esos
cuatro patrones. No existe un check equivalente para 443 en el set gratuito,
probablemente porque HTTPS abierto al mundo es un patrón legítimo y común
(ej. un servidor web público), así que checkov no lo trata como
automáticamente incorrecto sin contexto adicional.

Lo que sí detectó relacionado a este mismo Security Group:
- **CKV_AWS_23**: falta descripción en la regla (no dice *qué* expone ni
  *por qué*).
- **CKV_AWS_382**: el **egress** —no el ingress— está abierto a todo el
  tráfico (`0.0.0.0/0`, todos los puertos), que es la política de egress por
  defecto y normalmente aceptable, pero checkov la marca igual.

Conclusión: el hallazgo que ya conocían (443 abierto al mundo, management
del FortiGate expuesto sin restricción de origen) es real y confirmado
leyendo el `.tf`, pero **checkov no lo señala por nombre** — es una
limitación de cobertura del ruleset gratuito, no una confirmación de que el
diseño esté bien. Otros hallazgos no conocidos previamente y con impacto de
seguridad real para un sandbox expuesto a Internet: IMDSv1 habilitado
(CKV_AWS_79 — permite SSRF más fácil para robar credenciales de rol IAM vía
metadata service) y EBS sin cifrar (CKV_AWS_8).

---

## Resumen ejecutivo

| Directorio | Recursos | Passed | Failed |
|---|---|---|---|
| `terraform/` | 17 | 29 | 18 |
| `fortigate-sandbox-2026-06-07/` | 10 | 18 | 9 |

Ningún FAILED en ninguno de los dos directorios es crítico/bloqueante por sí
solo (no hay `*` en policies IAM, no hay credenciales hardcodeadas, no hay
buckets públicos) — son en su mayoría hardening incremental esperable en
infra de laboratorio/piloto. El más accionable para el sandbox FortiGate es
IMDSv1 habilitado (CKV_AWS_79), por su relación directa con el vector de
robo de credenciales vía metadata service en instancias expuestas a
Internet.
