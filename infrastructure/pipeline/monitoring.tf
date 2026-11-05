# =============================================================================
# MONITORING.TF — Dead-letter queues y alarmas de CloudWatch
# =============================================================================
# Red de seguridad operativa del pipeline:
#   1. SQS DLQ por función asíncrona (policy_generator, audit_executor): el
#      evento que no pudo procesarse tras los reintentos de Lambda queda
#      guardado 14 días para diagnóstico o re-ejecución manual.
#   2. Alarmas sobre la métrica `Errors` de las tres Lambdas y sobre la
#      profundidad de cada DLQ, notificando al mismo topic SNS que recibe
#      los reportes (var.notification_email).
#
# Nada de esto cambia el comportamiento funcional de las funciones: solo
# hace visibles los fallos que antes quedaban únicamente en CloudWatch Logs.
# =============================================================================


# -----------------------------------------------------------------------------
# DEAD-LETTER QUEUES
# Una cola por función asíncrona. Cifrado SSE-SQS (clave administrada por
# AWS, sin costo). Las referencian lambda.tf (dead_letter_config) e iam.tf
# (sqs:SendMessage acotado a la cola de cada rol).
# -----------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  for_each = toset(["policy-generator", "audit-executor"])

  name                      = "${local.prefix}-${each.key}-dlq"
  message_retention_seconds = 1209600 # 14 días (máximo de SQS)
  sqs_managed_sse_enabled   = true

  # Cada mensaje es el payload original de la invocación fallida: para el
  # generador, la notificación S3 (bucket + key de la política); para el
  # executor, el puntero {run_id, manifest_key, script_key, script_sha256}.
  # Ninguno contiene secretos. Para re-procesar: leer el mensaje y volver a
  # invocar la función con ese mismo payload.
}


# -----------------------------------------------------------------------------
# ALARMAS — errores de Lambda
# `Errors >= 1` en una ventana de 5 minutos. Sum sobre el período, un solo
# período de evaluación: cualquier invocación fallida dispara la alarma.
# `notBreaching` evita que la alarma quede en INSUFFICIENT_DATA (y mande
# emails espurios) cuando la función simplemente no corrió.
# -----------------------------------------------------------------------------

locals {
  monitored_functions = {
    assessor         = aws_lambda_function.assessor.function_name
    policy_generator = aws_lambda_function.policy_generator.function_name
    audit_executor   = aws_lambda_function.audit_executor.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = local.monitored_functions

  alarm_name          = "${local.prefix}-${replace(each.key, "_", "-")}-errors"
  alarm_description   = "Invocaciones fallidas de la Lambda ${each.value} (Errors >= 1 en 5 min)"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = [aws_sns_topic.notifications.arn]
}


# -----------------------------------------------------------------------------
# ALARMAS — mensajes en las DLQ
# Un mensaje visible en la DLQ significa que Lambda agotó sus reintentos
# para ese evento: alguien tiene que mirarlo. Se evalúa cada 5 minutos.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  for_each = aws_sqs_queue.dlq

  alarm_name          = "${local.prefix}-${each.key}-dlq-messages"
  alarm_description   = "Hay eventos sin procesar en la DLQ ${each.value.name}"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = each.value.name
  }

  alarm_actions = [aws_sns_topic.notifications.arn]
}
