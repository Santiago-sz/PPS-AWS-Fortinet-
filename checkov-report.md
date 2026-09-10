# Reporte Checkov — Análisis estático de Terraform

Generado con `checkov` 3.2.379, análisis de solo lectura (sin `terraform apply`/`plan`,
sin fixes automáticos aplicados). Se corrió por separado sobre los dos directorios
Terraform independientes del proyecto.

Comando usado (desde `G:\Mi unidad\TESIS\PPS prueba\`, con `.venv` activo):

```bash
PYTHONUTF8=1 python -m checkov.main -d terraform --output json
PYTHONUTF8=1 python -m checkov.main -d P-Terraform-Forti-AWS --output json
```

> Nota de entorno: en este equipo hubo que forzar `PYTHONUTF8=1` porque la
> codificación por defecto de Python en Windows (cp1252) no puede leer los
> comentarios en español/UTF-8 de los `.tf` (tildes, emes, guiones largos) y
> checkov rompía con `UnicodeDecodeError`. Ver `TESTING.md` para el detalle.

---

## 1. `terraform/` (infra del pipeline de auditoría)

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
| CKV_AWS_149 | Secret de Secrets Manager (Claude API key) sin KMS CMK propia | `aws_secretsmanager_secret.claude_api_key` | secrets.tf:58-64 |
| CKV_AWS_26 | Topic SNS sin cifrado de datos en reposo | `aws_sns_topic.notifications` | storage.tf:109-112 |
| CKV2_AWS_62 | Bucket S3 sin notificaciones de eventos habilitadas | `aws_s3_bucket.reports` | storage.tf:23-30 |
| CKV2_AWS_57 | Secret FortiGate sin rotación automática | `aws_secretsmanager_secret.fortigate_token` | secrets.tf:23-32 |
| CKV2_AWS_57 | Secret Claude sin rotación automática | `aws_secretsmanager_secret.claude_api_key` | secrets.tf:58-64 |
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

## 2. `P-Terraform-Forti-AWS/` (sandbox FortiGate-on-AWS)

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

**Confirmado en el código** (`P-Terraform-Forti-AWS/main.tf`, recurso
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
| `P-Terraform-Forti-AWS/` | 10 | 18 | 9 |

Ningún FAILED en ninguno de los dos directorios es crítico/bloqueante por sí
solo (no hay `*` en policies IAM, no hay credenciales hardcodeadas, no hay
buckets públicos) — son en su mayoría hardening incremental esperable en
infra de laboratorio/piloto. El más accionable para el sandbox FortiGate es
IMDSv1 habilitado (CKV_AWS_79), por su relación directa con el vector de
robo de credenciales vía metadata service en instancias expuestas a
Internet.
