# =============================================================================
# STORAGE.TF — Almacenamiento y notificaciones
# =============================================================================
# Este archivo crea dos recursos de salida del sistema:
#   1. S3 Bucket — donde Lambda deposita los reportes de assessment
#   2. SNS Topic — por donde Lambda notifica que el assessment terminó
#
# Son los dos destinos finales del flujo. Todo lo que Lambda procesa
# termina acá: el reporte completo en S3 y el resumen por email via SNS.
# =============================================================================


# =============================================================================
# S3 — ALMACENAMIENTO DE REPORTES
# =============================================================================

# -----------------------------------------------------------------------------
# BUCKET PRINCIPAL
# El bucket donde se guardan todos los reportes generados por Lambda.
# Cada assessment produce un archivo JSON con el análisis NIST CSF completo.
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "reports" {
  bucket = "${local.prefix}-reports-${data.aws_caller_identity.current.account_id}"
  # Por qué incluimos el account_id: los nombres de S3 son GLOBALES en AWS —
  # no pueden repetirse en ninguna cuenta del mundo. Agregar el account_id
  # garantiza unicidad sin necesidad de sufijos aleatorios que son difíciles
  # de recordar y referenciar.
  # Resultado: "pps-prod-reports-123456789012"
}

# -----------------------------------------------------------------------------
# VERSIONING
# Guarda el historial de cada reporte. Si Lambda sobreescribe un archivo,
# la versión anterior queda disponible para recuperar.
# Útil para auditoría: podés ver cómo evolucionó el posture a lo largo del tiempo.
# -----------------------------------------------------------------------------

resource "aws_s3_bucket_versioning" "reports" {
  bucket = aws_s3_bucket.reports.id

  versioning_configuration {
    status = "Enabled"
    # Con versioning habilitado, cada terraform apply que sobrescriba
    # un reporte crea una nueva versión — la anterior no se pierde.
    # Podés acceder a versiones anteriores desde la consola de S3
    # o con: aws s3api list-object-versions --bucket <nombre>
  }
}

# -----------------------------------------------------------------------------
# BLOQUEO DE ACCESO PÚBLICO
# Por defecto, S3 puede exponer objetos públicamente si se configura mal.
# Este recurso bloquea TODAS las formas de acceso público al bucket.
# Los reportes de seguridad NUNCA deben ser públicos.
# -----------------------------------------------------------------------------

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket = aws_s3_bucket.reports.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
  # Los cuatro en true = acceso público completamente bloqueado.
  # Solo Lambda (via IAM role) puede escribir. Nadie puede leer sin credenciales.
}

# -----------------------------------------------------------------------------
# CIFRADO EN REPOSO
# Los reportes contienen información de seguridad sensible — configuración
# del firewall, vulnerabilidades detectadas, scores de compliance.
# Se cifran automáticamente con la clave administrada por AWS (SSE-S3).
# -----------------------------------------------------------------------------

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
      # AES256 = SSE-S3: AWS maneja las claves, sin costo adicional.
      # Alternativa más segura: "aws:kms" con una KMS key propia,
      # pero agrega complejidad y costo. Para este proyecto AES256 es suficiente.
    }
  }
}

# -----------------------------------------------------------------------------
# DATA SOURCE — cuenta de AWS actual
# Necesario para construir el nombre del bucket con el account_id.
# No crea ningún recurso — solo consulta información de la cuenta.
# -----------------------------------------------------------------------------

data "aws_caller_identity" "current" {}


# =============================================================================
# SNS — NOTIFICACIONES
# =============================================================================

# -----------------------------------------------------------------------------
# TOPIC
# El canal de mensajería. Lambda publica un mensaje acá cuando termina
# el assessment. SNS lo distribuye a todos los suscriptores del topic.
# En este caso, un suscriptor: el email configurado en variables.tf.
# -----------------------------------------------------------------------------

resource "aws_sns_topic" "notifications" {
  name = "${local.prefix}-notifications"
  # Nombre resultado: "pps-prod-notifications"
}

# -----------------------------------------------------------------------------
# SUSCRIPCIÓN DE EMAIL
# Conecta el topic con el email del destinatario.
# Cuando Lambda publique en el topic, SNS manda el mensaje a este email.
#
# IMPORTANTE: después del primer terraform apply, AWS manda un email
# de confirmación a esta dirección. Hasta que el destinatario haga click
# en "Confirm subscription", los mensajes NO llegan.
# -----------------------------------------------------------------------------

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.notifications.arn
  protocol  = "email"
  endpoint  = var.notification_email
  # protocol = "email" → entrega como email plano (texto).
  # Otras opciones posibles: "email-json" (JSON), "sqs", "lambda", "https".
  # Para notificaciones humanas, "email" es el más directo.
}


# -----------------------------------------------------------------------------
# OUTPUTS
# Exponen los ARNs y nombre del bucket para que otros archivos los referencien.
# El bucket name lo necesita Lambda para saber dónde subir los reportes.
# Los ARNs los usa iam.tf para construir los permisos exactos.
# -----------------------------------------------------------------------------

output "reports_bucket_name" {
  value       = aws_s3_bucket.reports.bucket
  description = "Name of the S3 bucket where assessment reports are stored"
}

output "reports_bucket_arn" {
  value       = aws_s3_bucket.reports.arn
  description = "ARN of the reports S3 bucket"
}

output "sns_topic_arn" {
  value       = aws_sns_topic.notifications.arn
  description = "ARN of the SNS notifications topic"
}
