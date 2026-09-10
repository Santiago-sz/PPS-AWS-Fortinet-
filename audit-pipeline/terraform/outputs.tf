# =============================================================================
# OUTPUTS.TF — Valores de salida del deployment
# =============================================================================
# Después de un terraform apply exitoso, estos valores se imprimen en la terminal.
# Sirven para tres cosas:
#   1. Verificar que los recursos se crearon con los nombres/ARNs correctos
#   2. Copiar los valores que necesitás para los pasos manuales post-deploy
#   3. Referenciar esta infra desde otros módulos Terraform en el futuro
#
# Los outputs individuales ya están en cada archivo (.tf) donde se define
# el recurso. Este archivo agrupa los más importantes en un solo lugar
# para tenerlos a mano después del apply.
# =============================================================================


# -----------------------------------------------------------------------------
# LAMBDA
# -----------------------------------------------------------------------------

output "assessor_function_name" {
  value       = aws_lambda_function.assessor.function_name
  description = "Lambda function name — use this to invoke manually or check logs"
}

output "assessor_function_arn" {
  value       = aws_lambda_function.assessor.arn
  description = "Lambda function ARN"
}


# -----------------------------------------------------------------------------
# S3
# -----------------------------------------------------------------------------

output "reports_bucket" {
  value       = aws_s3_bucket.reports.bucket
  description = "S3 bucket name where assessment reports are stored"
}


# -----------------------------------------------------------------------------
# SNS
# -----------------------------------------------------------------------------

output "notifications_topic_arn" {
  value       = aws_sns_topic.notifications.arn
  description = "SNS topic ARN — publish here to send a manual notification"
}


# -----------------------------------------------------------------------------
# SECRETS MANAGER
# Los outputs de los ARNs de los secrets viven en secrets.tf, junto al
# recurso que definen (fortigate_secret_arn, claude_secret_arn) — Terraform
# no permite declarar el mismo nombre de output en dos archivos, así que no
# se repiten acá. Ver secrets.tf.
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# EVENTBRIDGE
# -----------------------------------------------------------------------------

output "schedule_rule_name" {
  value       = try(aws_cloudwatch_event_rule.schedule[0].name, null)
  description = "EventBridge rule name — disable this to pause automated assessments. null when var.enable_legacy_nist_schedule=false"
  # aws_cloudwatch_event_rule.schedule ahora está gateado por count (ver
  # lambda.tf, tasks.md 2.8) — try()+índice [0] en vez de acceso directo
  # porque con count=0 el recurso no existe y .name fallaría el validate.
}


# -----------------------------------------------------------------------------
# PASOS POST-DEPLOY
# Instrucciones impresas en la terminal después del apply.
# Recordatorio de los pasos manuales obligatorios antes de que el sistema funcione.
# -----------------------------------------------------------------------------

output "next_steps" {
  value = <<-EOT

    ============================================================
    DEPLOY EXITOSO — Pasos obligatorios antes de usar el sistema
    ============================================================

    1. Confirmar suscripción SNS:
       Revisá tu email (${var.notification_email}) y hacé click
       en "Confirm subscription" para activar las notificaciones.

    2. Cargar token de FortiGate:
       aws secretsmanager put-secret-value \
         --secret-id ${aws_secretsmanager_secret.fortigate_token.name} \
         --secret-string '{"token":"TU_TOKEN_REAL","host":"${var.fortigate_host}"}'

    3. Cargar API key de Claude:
       aws secretsmanager put-secret-value \
         --secret-id ${aws_secretsmanager_secret.claude_api_key.name} \
         --secret-string '{"api_key":"sk-ant-XXXXXXXX"}'

    4. Probar la Lambda manualmente:
       aws lambda invoke \
         --function-name ${aws_lambda_function.assessor.function_name} \
         --payload '{}' \
         response.json && cat response.json

    ============================================================
  EOT

  description = "Post-deployment checklist"
}
