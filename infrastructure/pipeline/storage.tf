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
# CICLO DE VIDA
# artifacts/* (script + manifest) y reports/* (report.md/json) expiran
# tras var.artifact_retention_days / var.report_retention_days; las
# versiones no vigentes (versioning habilitado) se purgan a los 30 días y
# los multipart uploads abandonados a los 7. Evita que el bucket crezca
# sin límite con cada corrida.
# -----------------------------------------------------------------------------

resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    id     = "expire-generated-artifacts"
    status = "Enabled"

    filter {
      prefix = "artifacts/"
    }

    expiration {
      days = var.artifact_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "expire-audit-reports"
    status = "Enabled"

    filter {
      prefix = "reports/"
    }

    expiration {
      days = var.report_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.reports]
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

# Los outputs (bucket de reports, topic SNS) viven en outputs.tf.


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

resource "aws_s3_bucket_lifecycle_configuration" "policies" {
  bucket = aws_s3_bucket.policies.id

  # Las políticas vigentes NO expiran (son la entrada del sistema y el
  # operador decide cuándo borrarlas); solo se purgan versiones viejas de
  # re-subidas y multipart uploads abandonados.
  rule {
    id     = "expire-noncurrent-policy-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.policies]
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

# El output del bucket de políticas (policies_bucket) vive en outputs.tf.
