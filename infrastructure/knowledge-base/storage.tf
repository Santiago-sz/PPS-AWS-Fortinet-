# =============================================================================
# STORAGE.TF — Bucket de documentos de la Knowledge Base
# =============================================================================
# Bucket propio, separado de los buckets de políticas y de reportes del
# pipeline: acá solo van los documentos de referencia que la Knowledge Base
# indexa. Mismo endurecimiento que infrastructure/pipeline/storage.tf:
# versionado, bloqueo total de acceso público, cifrado en reposo y ciclo de
# vida.
# =============================================================================

resource "aws_s3_bucket" "knowledge" {
  bucket = "${local.prefix}-knowledge-${data.aws_caller_identity.current.account_id}"
  # Mismo criterio de nombrado que los buckets del pipeline: el account_id
  # garantiza unicidad global sin sufijos aleatorios.
}

resource "aws_s3_bucket_versioning" "knowledge" {
  bucket = aws_s3_bucket.knowledge.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "knowledge" {
  bucket = aws_s3_bucket.knowledge.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "knowledge" {
  bucket = aws_s3_bucket.knowledge.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
      # SSE-S3, igual que el pipeline. Con una clave KMS propia el rol de
      # servicio necesitaría además kms:Decrypt sobre esa clave.
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "knowledge" {
  bucket = aws_s3_bucket.knowledge.id

  # Los documentos vigentes no expiran; solo se purgan versiones anteriores
  # y cargas multiparte abandonadas.
  rule {
    id     = "expire-noncurrent-knowledge-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_document_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.knowledge]
}
