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


# =============================================================================
# S3 — BUCKET DE POLÍTICAS SUBIDAS (entrada del flujo policy-driven)
# =============================================================================
# Bucket separado del de reports/artifacts a propósito — ver design.md,
# decisión #1. Si policy_generator escribiera sus artifacts acá, o
# audit_executor sus reports, cada escritura volvería a disparar la
# notificación de subida de abajo: un loop de auto-invocación. Los
# artifacts y reports van al bucket "reports" existente (prefijos
# artifacts/* y reports/*, ver iam.tf); acá solo llegan los .pdf/.docx
# que sube un humano para ser auditados.
# =============================================================================

resource "aws_s3_bucket" "policies" {
  bucket = "${local.prefix}-policies-${data.aws_caller_identity.current.account_id}"
  # Mismo criterio de nombrado que aws_s3_bucket.reports: account_id
  # garantiza unicidad global sin sufijos aleatorios.
  # Resultado: "pps-prod-policies-123456789012"
}

resource "aws_s3_bucket_versioning" "policies" {
  bucket = aws_s3_bucket.policies.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "policies" {
  bucket = aws_s3_bucket.policies.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
  # Las políticas de la organización subidas acá son tan sensibles como
  # los reportes que generan — mismo bloqueo total de acceso público.
}

resource "aws_s3_bucket_server_side_encryption_configuration" "policies" {
  bucket = aws_s3_bucket.policies.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# -----------------------------------------------------------------------------
# NOTIFICACIÓN DE SUBIDA — dispara policy_generator
# Solo objetos bajo el prefijo policies/ con sufijo .pdf o .docx disparan
# la Lambda. El filtro evita invocaciones espurias por archivos que no son
# políticas (ej. notas .txt subidas al mismo bucket por error).
# aws_s3_bucket_notification no admite múltiples filtros de sufijo en un
# mismo bloque lambda_function, así que van dos bloques — uno por extensión.
# -----------------------------------------------------------------------------

resource "aws_s3_bucket_notification" "policies_upload" {
  bucket = aws_s3_bucket.policies.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.policy_generator.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "policies/"
    filter_suffix       = ".pdf"
  }

  lambda_function {
    lambda_function_arn = aws_lambda_function.policy_generator.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "policies/"
    filter_suffix       = ".docx"
  }

  depends_on = [aws_lambda_permission.s3_invoke]
  # depends_on explícito: S3 exige que el permiso de invocación exista
  # ANTES de aceptar la configuración de notificación, si no falla el
  # apply con "Unable to validate the following destination configurations".
}

# -----------------------------------------------------------------------------
# PERMISO — S3 puede invocar policy_generator
# Por defecto nadie puede invocar una Lambda, ni otros servicios AWS.
# Mismo patrón que aws_lambda_permission.eventbridge en lambda.tf, pero
# para el principal s3.amazonaws.com en vez de events.amazonaws.com.
# -----------------------------------------------------------------------------

resource "aws_lambda_permission" "s3_invoke" {
  statement_id  = "AllowS3InvokePolicyGenerator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.policy_generator.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.policies.arn
  # source_arn restringe el permiso: solo ESTE bucket puede invocar la
  # Lambda. Sin esto, cualquier bucket S3 de la cuenta podría hacerlo.
}


# -----------------------------------------------------------------------------
# OUTPUTS — bucket de políticas
# -----------------------------------------------------------------------------

output "policies_bucket_name" {
  value       = aws_s3_bucket.policies.bucket
  description = "Name of the S3 bucket where policy documents (PDF/DOCX) are uploaded to trigger generation"
}

output "policies_bucket_arn" {
  value       = aws_s3_bucket.policies.arn
  description = "ARN of the policies S3 bucket"
}
