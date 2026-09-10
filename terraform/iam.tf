# =============================================================================
# IAM.TF — Permisos de ejecución de Lambda
# =============================================================================
# Este archivo define QUÉ puede hacer Lambda dentro de AWS.
# IAM es el sistema de permisos de AWS — sin esto, Lambda no puede
# leer secrets, escribir en S3, publicar en SNS ni guardar logs.
#
# Principio de mínimo privilegio: Lambda recibe SOLO los permisos
# que necesita, sobre SOLO los recursos que usa. Nada más.
# Esto limita el daño si la función fuera comprometida.
# =============================================================================


# -----------------------------------------------------------------------------
# ROL DE EJECUCIÓN
# En AWS, una función Lambda no usa credenciales de usuario — asume un ROL.
# El rol es una identidad temporal que AWS le asigna a Lambda al arrancar.
# La "trust policy" define quién puede asumir este rol — en este caso,
# solo el servicio Lambda (lambda.amazonaws.com).
# -----------------------------------------------------------------------------

resource "aws_iam_role" "lambda_execution" {
  name        = "${local.prefix}-lambda-role"
  description = "Execution role for PPS Lambda — grants access to required AWS services"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
        # Esto dice: "el servicio Lambda tiene permitido asumir este rol".
        # Sin este Statement, ningún servicio podría usar el rol —
        # ni siquiera Lambda misma.
      }
    ]
  })
}


# -----------------------------------------------------------------------------
# POLÍTICA DE PERMISOS
# Define las acciones concretas que Lambda puede ejecutar y sobre qué recursos.
# Se adjunta al rol de ejecución creado arriba.
# -----------------------------------------------------------------------------

resource "aws_iam_role_policy" "lambda_permissions" {
  name = "${local.prefix}-lambda-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [

      # ------------------------------------------------------------------
      # SECRETS MANAGER — leer credenciales
      # Lambda necesita leer los dos secrets al inicio de cada ejecución:
      # el token de FortiGate y la API key de Claude.
      # El permiso apunta a los ARNs exactos — no a todos los secrets.
      # ------------------------------------------------------------------
      {
        Sid    = "ReadSecrets"
        Effect = "Allow"
        Action = "secretsmanager:GetSecretValue"
        Resource = [
          aws_secretsmanager_secret.fortigate_token.arn,
          aws_secretsmanager_secret.claude_api_key.arn
        ]
      },

      # ------------------------------------------------------------------
      # S3 — escribir reportes
      # Lambda sube el reporte JSON generado al bucket de S3.
      # Solo necesita PutObject — no puede listar, leer ni borrar objetos.
      # El /* al final del ARN significa "cualquier objeto dentro del bucket".
      # ------------------------------------------------------------------
      {
        Sid    = "WriteReports"
        Effect = "Allow"
        Action = "s3:PutObject"
        Resource = "${aws_s3_bucket.reports.arn}/*"
      },

      # ------------------------------------------------------------------
      # SNS — publicar notificaciones
      # Lambda publica un mensaje al topic cuando termina el assessment.
      # Solo necesita Publish — no puede crear topics ni cambiar suscripciones.
      # ------------------------------------------------------------------
      {
        Sid      = "PublishNotifications"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.notifications.arn
      },

      # ------------------------------------------------------------------
      # CLOUDWATCH LOGS — escribir logs de ejecución
      # Lambda necesita estos tres permisos para poder escribir sus logs.
      # Sin esto, cualquier print() o error en Python desaparece en el vacío.
      # El Resource "*" es necesario porque el Log Group se crea
      # automáticamente la primera vez que Lambda ejecuta.
      # ------------------------------------------------------------------
      {
        Sid    = "WriteLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }

    ]
  })
}
