# =============================================================================
# BEDROCK_LOGGING.TF — Model Invocation Logging de Amazon Bedrock
# =============================================================================
# Registra en CloudWatch Logs el prompt y la respuesta de cada invocación
# al modelo (map, reduce y el análisis NIST legacy). Es la evidencia
# primaria de "qué se le pidió al modelo y qué devolvió" para la tesis, y
# complementa los eventos `llm_call` que emiten las Lambdas (tokens y
# latencia, pero no el texto).
#
# ADVERTENCIA — ALCANCE DE CUENTA: Bedrock admite UNA sola configuración de
# invocation logging por cuenta y región. Este recurso la crea/pisa para
# TODA la cuenta en var.aws_region, no solo para este proyecto. Si la
# cuenta ya tiene otra configuración, poner
# var.enable_bedrock_invocation_logging = false y gestionarla aparte.
#
# El log contiene el texto de las políticas auditadas: tratar el log group
# como información sensible (mismo criterio que el bucket de reports).
#
# Todo gateado por var.enable_bedrock_invocation_logging (count).
# =============================================================================


resource "aws_cloudwatch_log_group" "bedrock_invocations" {
  count = var.enable_bedrock_invocation_logging ? 1 : 0

  name              = "/aws/bedrock/${local.prefix}-model-invocations"
  retention_in_days = var.log_retention_days
}


# -----------------------------------------------------------------------------
# ROL DE SERVICIO — Bedrock escribe en el log group
# Trust policy acotada con aws:SourceAccount + aws:SourceArn (protección
# contra confused deputy): solo el servicio Bedrock, actuando en nombre de
# ESTA cuenta y región, puede asumir el rol.
# -----------------------------------------------------------------------------

resource "aws_iam_role" "bedrock_logging" {
  count = var.enable_bedrock_invocation_logging ? 1 : 0

  name        = "${local.prefix}-bedrock-logging-role"
  description = "Service role used by Amazon Bedrock to deliver model invocation logs to CloudWatch Logs"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "bedrock.amazonaws.com" }
        Action    = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
          ArnLike = {
            "aws:SourceArn" = "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "bedrock_logging" {
  count = var.enable_bedrock_invocation_logging ? 1 : 0

  name = "${local.prefix}-bedrock-logging-policy"
  role = aws_iam_role.bedrock_logging[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "WriteModelInvocationLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        # Bedrock escribe siempre en el log stream fijo
        # `aws/bedrock/modelinvocations` dentro del log group indicado.
        Resource = "${aws_cloudwatch_log_group.bedrock_invocations[0].arn}:log-stream:aws/bedrock/modelinvocations"
      }
    ]
  })
}


# -----------------------------------------------------------------------------
# CONFIGURACIÓN — única por cuenta/región (ver advertencia arriba)
# Solo texto: este proyecto no invoca modelos de embeddings, imagen ni
# video, así que se desactiva su entrega para no registrar payloads
# binarios de otros usos de la cuenta.
# -----------------------------------------------------------------------------

resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  count = var.enable_bedrock_invocation_logging ? 1 : 0

  logging_config {
    text_data_delivery_enabled      = true
    embedding_data_delivery_enabled = false
    image_data_delivery_enabled     = false
    video_data_delivery_enabled     = false

    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock_invocations[0].name
      role_arn       = aws_iam_role.bedrock_logging[0].arn
    }
  }

  depends_on = [aws_iam_role_policy.bedrock_logging]
  # El rol necesita tener la política adjunta ANTES de que Bedrock valide
  # la configuración, si no el apply falla con "role is not authorized".
}
