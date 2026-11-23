# =============================================================================
# Red privada de la Lambda ejecutora de PostureGuard hacia el laboratorio
# =============================================================================
# Módulo aislado de la cuenta del pipeline: estado local propio (ignorado por
# Git). No modifica infrastructure/pipeline/: solo entrega los ids de subred y
# de grupo de seguridad que ese módulo ya acepta como variables. Ver README.md.
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.44"
    }
  }
}
