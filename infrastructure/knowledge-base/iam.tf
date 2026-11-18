# =============================================================================
# IAM.TF — Rol de servicio de la Knowledge Base
# =============================================================================
# Bedrock asume este rol para leer los documentos del bucket durante la
# ingesta. Mínimo privilegio: solo listar ese bucket y leer sus objetos.
# No es un rol de Lambda y no lo usa ninguna función del pipeline.
# =============================================================================

resource "aws_iam_role" "knowledge_base" {
  name        = "${local.prefix}-knowledge-base-role"
  description = "Service role for the PPS Bedrock managed knowledge base - reads the knowledge documents bucket"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowBedrockKnowledgeBase"
        Effect    = "Allow"
        Principal = { Service = "bedrock.amazonaws.com" }
        Action    = "sts:AssumeRole"
        # Protección contra confused deputy: solo Knowledge Bases de ESTA
        # cuenta y región pueden asumir el rol. El id de la base todavía no
        # existe cuando se crea el rol, por eso SourceArn usa un patrón.
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
          ArnLike = {
            "aws:SourceArn" = "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:knowledge-base/*"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "knowledge_base" {
  name = "${local.prefix}-knowledge-base-policy"
  role = aws_iam_role.knowledge_base.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListKnowledgeDocuments"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.knowledge.arn
      },
      {
        Sid      = "ReadKnowledgeDocuments"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.knowledge.arn}/*"
      }
    ]
  })
}
