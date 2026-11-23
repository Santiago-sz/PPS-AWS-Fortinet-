# =============================================================================
# Laboratorio FortiGate-VM desechable para la demostración de PostureGuard
# =============================================================================
# Módulo aislado: estado local propio (ignorado por Git) y sin vínculo con
# infrastructure/pipeline/ ni con infrastructure/knowledge-base/. Todo lo que
# crea se elimina con un único `terraform destroy`. Ver README.md.
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.44"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    cloudinit = {
      source  = "hashicorp/cloudinit"
      version = "~> 2.3"
    }
  }
}
