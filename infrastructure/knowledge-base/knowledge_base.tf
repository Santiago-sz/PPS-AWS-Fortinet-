# =============================================================================
# KNOWLEDGE_BASE.TF — Knowledge Base administrada y su data source
# =============================================================================
# Tipo MANAGED: Bedrock administra el almacén vectorial, el parsing y los
# embeddings. Por eso no hay un bloque de almacenamiento propio (no se admite
# en este tipo) ni un almacén vectorial que crear o pagar por separado.
# =============================================================================

resource "aws_bedrockagent_knowledge_base" "this" {
  name        = "${local.prefix}-knowledge-base"
  description = "PPS managed knowledge base - reference documents for policy-driven audit generation"
  role_arn    = aws_iam_role.knowledge_base.arn

  knowledge_base_configuration {
    type = "MANAGED"

    managed_knowledge_base_configuration {
      embedding_model_type = "MANAGED"
    }
  }

  depends_on = [aws_iam_role_policy.knowledge_base]
  # La política debe existir antes de crear la base: Bedrock valida el
  # acceso del rol al crear y al sincronizar.
}

# -----------------------------------------------------------------------------
# DATA SOURCE — conector S3 administrado sobre el bucket de este módulo
# connector_parameters es un JSON propio del conector (estructura tomada de
# la documentación del provider, ejemplo "Managed Knowledge Base Connector -
# S3"). La ingesta no es automática: la inicia el operador (ver README.md).
# -----------------------------------------------------------------------------

resource "aws_bedrockagent_data_source" "documents" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.this.id
  name              = "${local.prefix}-knowledge-documents"
  description       = "PPS knowledge documents stored in the module S3 bucket"

  data_source_configuration {
    type = "MANAGED_KNOWLEDGE_BASE_CONNECTOR"

    managed_knowledge_base_connector_configuration {
      connector_parameters = jsonencode({
        type    = "S3"
        version = "1"
        connectionConfiguration = {
          bucketName           = aws_s3_bucket.knowledge.bucket
          bucketOwnerAccountId = data.aws_caller_identity.current.account_id
        }
        filterConfiguration = {
          maxFileSizeInMegaBytes = "500"
        }
        aclEnabled = false
      })

      # Valores que el servicio aplica por defecto al crear el conector
      # (comprobado en el despliegue del 2026-11-18). Se declaran de forma
      # explícita porque, si se omiten, el provider detecta una diferencia
      # entre lo enviado y lo devuelto y marca el recurso para reemplazo.
      media_extraction_configuration {
        image_extraction_configuration {
          image_extraction_status = "ENABLED"
        }
      }
    }
  }
}
