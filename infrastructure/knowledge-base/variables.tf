# =============================================================================
# VARIABLES — Knowledge Base administrada
# =============================================================================
# Mismos nombres y valores por defecto que infrastructure/pipeline/variables.tf
# para que ambos módulos produzcan el mismo prefijo de nombres y los mismos
# tags sin configuración adicional.
# =============================================================================

variable "aws_region" {
  description = "AWS region where the knowledge base resources will be deployed"
  type        = string
  default     = "us-east-1"
  # Debe coincidir con la región del pipeline: el permiso bedrock:Retrieve
  # del generador apunta a la Knowledge Base de su propia región.
}

variable "project_name" {
  description = "Project name used as prefix for all resource names"
  type        = string
  default     = "pps"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}

variable "noncurrent_document_retention_days" {
  description = "Días tras los cuales se purgan las versiones no vigentes de los documentos del bucket de conocimiento"
  type        = number
  default     = 90
  # Los documentos vigentes no expiran: son el corpus de la Knowledge Base y
  # el operador decide cuándo retirarlos.
}
