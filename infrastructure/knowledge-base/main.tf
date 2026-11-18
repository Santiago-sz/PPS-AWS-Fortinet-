# =============================================================================
# MAIN.TF — Knowledge Base administrada de Amazon Bedrock (módulo aislado)
# =============================================================================
# Este módulo crea la base para un RAG vectorial: un bucket de documentos, un
# rol de servicio, una Knowledge Base administrada y su data source S3.
#
# Es un módulo SEPARADO de infrastructure/pipeline/ a propósito: las Knowledge
# Bases administradas requieren el provider aws 6.x y el pipeline desplegado
# está fijado en 5.100.0 ("~> 5.0"). Subir el provider del pipeline obligaría
# a revisar todos los recursos ya desplegados; acá el provider y el estado
# son propios, y el único vínculo con el pipeline es el id de la Knowledge
# Base (output knowledge_base_id -> variable knowledge_base_id del pipeline).
# =============================================================================

terraform {

  required_version = ">= 1.5.0"
  # Misma versión mínima que infrastructure/pipeline/.

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
      # 6.73.0 es la versión con la que se validó este módulo (tipo MANAGED
      # en aws_bedrockagent_knowledge_base y conector
      # MANAGED_KNOWLEDGE_BASE_CONNECTOR en aws_bedrockagent_data_source).
      # "~> 6.73" admite 6.73 o superior dentro de la serie 6.x, nunca 7.x.
    }
  }
}


# -----------------------------------------------------------------------------
# PROVIDER AWS
# Las credenciales se toman del entorno, igual que en el pipeline. Los tags
# por defecto son los mismos tres para que los costos se filtren por proyecto.
# -----------------------------------------------------------------------------

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}


# -----------------------------------------------------------------------------
# LOCALS Y DATOS DE LA CUENTA
# -----------------------------------------------------------------------------

locals {
  # Mismo prefijo que el pipeline. Resultado por defecto: "pps-prod".
  prefix = "${var.project_name}-${var.environment}"
}

data "aws_caller_identity" "current" {}
