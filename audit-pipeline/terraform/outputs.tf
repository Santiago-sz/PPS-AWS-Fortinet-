# =============================================================================
# OUTPUTS.TF  - Valores de salida del deployment (set canónico ÚNICO)
# =============================================================================
# Después de un terraform apply exitoso, estos valores se imprimen en la
# terminal. Sirven para tres cosas:
#   1. Verificar que los recursos se crearon con los nombres/ARNs correctos
#   2. Copiar los valores que necesitan los pasos manuales post-deploy y la
#      configuración de `pps-api aws ...` / la app de escritorio
#   3. Referenciar esta infra desde otros módulos Terraform en el futuro
#
# Todos los outputs del módulo viven en ESTE archivo. No declarar outputs
# en los demás .tf (antes había duplicados: reports_bucket vs
# reports_bucket_name, notifications_topic_arn vs sns_topic_arn, etc.).
# =============================================================================


# -----------------------------------------------------------------------------
# S3
# -----------------------------------------------------------------------------

output "reports_bucket" {
  value       = aws_s3_bucket.reports.bucket
  description = "Bucket de salida: artifacts/* (script + manifest generados) y reports/* (report.md / report.json)"
}

output "policies_bucket" {
  value       = aws_s3_bucket.policies.bucket
  description = "Bucket de entrada: subir políticas PDF/DOCX bajo policies/ para disparar policy_generator"
}


# -----------------------------------------------------------------------------
# SNS
# -----------------------------------------------------------------------------

output "notifications_topic_arn" {
  value       = aws_sns_topic.notifications.arn
  description = "Topic SNS que recibe los reportes terminados y las alarmas de CloudWatch"
}


# -----------------------------------------------------------------------------
# LAMBDA
# -----------------------------------------------------------------------------

output "generator_function_name" {
  value       = aws_lambda_function.policy_generator.function_name
  description = "Nombre de la Lambda policy_generator (disparada por S3)"
}

output "generator_function_arn" {
  value       = aws_lambda_function.policy_generator.arn
  description = "ARN de la Lambda policy_generator"
}

output "executor_function_name" {
  value       = aws_lambda_function.audit_executor.function_name
  description = "Nombre de la Lambda audit_executor (la usa `pps-api aws approve` cuando auto_execute=false)"
}

output "executor_function_arn" {
  value       = aws_lambda_function.audit_executor.arn
  description = "ARN de la Lambda audit_executor"
}

output "assessor_function_name" {
  value       = aws_lambda_function.assessor.function_name
  description = "Nombre de la Lambda assessor (flujo NIST legacy; schedule gateado por var.enable_legacy_nist_schedule)"
}

output "assessor_function_arn" {
  value       = aws_lambda_function.assessor.arn
  description = "ARN de la Lambda assessor (flujo NIST legacy)"
}


# -----------------------------------------------------------------------------
# SECRETS MANAGER / BEDROCK / OBSERVABILIDAD
# -----------------------------------------------------------------------------

output "fortigate_secret_arn" {
  value       = aws_secretsmanager_secret.fortigate_token.arn
  description = "ARN del secret con el token de la REST API de FortiGate (cargar el valor real a mano, ver next_steps)"
}

output "bedrock_model_id" {
  value       = var.bedrock_model_id
  description = "Perfil de inferencia de Bedrock inyectado como BEDROCK_MODEL_ID en assessor y policy_generator"
}

output "model_invocation_log_group" {
  value       = try(aws_cloudwatch_log_group.bedrock_invocations[0].name, null)
  description = "Log group con prompt+respuesta de cada invocación al modelo (null si var.enable_bedrock_invocation_logging=false)"
}

output "dead_letter_queue_urls" {
  value       = { for k, q in aws_sqs_queue.dlq : k => q.url }
  description = "URLs de las DLQ de policy_generator y audit_executor  - revisar si llega la alarma *-dlq-messages"
}

output "schedule_rule_name" {
  value       = try(aws_cloudwatch_event_rule.schedule[0].name, null)
  description = "Regla EventBridge del assessor NIST legacy; null cuando var.enable_legacy_nist_schedule=false (default)"
}


# -----------------------------------------------------------------------------
# PASOS POST-DEPLOY
# Checklist impreso en la terminal después del apply, en el orden real del
# flujo policy-driven. Hasta completar 1-3 el sistema no produce reportes.
# -----------------------------------------------------------------------------

output "next_steps" {
  value = <<-EOT

    ============================================================
    DEPLOY EXITOSO  - checklist antes de la primera auditoría
    ============================================================

    1. Confirmar la suscripción SNS: revisar el correo
       ${var.notification_email} y hacer clic en "Confirm subscription".
       Sin esto no llegan ni los reportes ni las alarmas.

    2. Cargar el token de la REST API de FortiGate en el secret
       (Terraform solo creó el contenedor con un placeholder):
       aws secretsmanager put-secret-value \
         --secret-id ${aws_secretsmanager_secret.fortigate_token.name} \
         --secret-string '{"token":"TOKEN_REAL"}' \
         --region ${var.aws_region}

    3. Verificar acceso y cuota al modelo en Amazon Bedrock (una sola vez
       por cuenta/región; el acceso a modelos Anthropic requiere el
       formulario de caso de uso aprobado):
       aws bedrock list-inference-profiles --region ${var.aws_region} \
         --query "inferenceProfileSummaries[?inferenceProfileId=='${var.bedrock_model_id}'].status"
       Debe devolver ["ACTIVE"]. Cuotas: Service Quotas > Amazon Bedrock >
       "On-demand InvokeModel tokens per minute" para ese modelo.

    4. Subir una política (PDF o DOCX) al bucket de entrada; eso dispara
       policy_generator -> audit_executor -> reporte:
       aws s3 cp mi-politica.pdf \
         s3://${aws_s3_bucket.policies.bucket}/policies/mi-politica.pdf
       (equivalente desde la CLI del proyecto: `pps-api aws dispatch`).

    5. Sincronizar los reportes generados hacia la consola local:
       pps-api aws sync
       (con auto_execute=false, antes: `pps-api aws list-pending` y
       `pps-api aws approve <run_id>` para invocar al executor).

    6. Abrir la app de escritorio (desktop/) y revisar el reporte: los
       hallazgos citan la cláusula de la política y las remediaciones son
       PROPUESTAS  - el sistema nunca modifica el FortiGate.

    Diagnóstico: logs en /aws/lambda/${local.prefix}-policy-generator y
    /aws/lambda/${local.prefix}-audit-executor; prompts y respuestas del
    modelo en ${try(aws_cloudwatch_log_group.bedrock_invocations[0].name, "(invocation logging deshabilitado)")}.
    ============================================================
  EOT

  description = "Checklist post-deploy en el orden real del flujo policy-driven"
}
