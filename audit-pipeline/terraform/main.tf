# =============================================================================
# MAIN.TF — Punto de entrada de Terraform
# =============================================================================
# Este archivo hace tres cosas:
#   1. Declara qué versión de Terraform y qué providers se necesitan
#   2. Configura el provider de AWS (región, tags globales)
#   3. Define locals — valores calculados que se reutilizan en todos los archivos
# =============================================================================


# -----------------------------------------------------------------------------
# BLOQUE TERRAFORM
# Define las dependencias del proyecto antes de hacer cualquier cosa.
# Terraform lo lee primero para descargar los plugins necesarios (terraform init).
# -----------------------------------------------------------------------------

terraform {

  required_version = ">= 1.5.0"
  # Por qué 1.5.0: es la versión mínima que soporta todas las features que usamos.
  # Esto evita que alguien con Terraform 0.14 rompa el deploy por sintaxis incompatible.

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
      # "~> 5.0" significa: cualquier versión 5.x pero NO la 6.x.
      # Esto te protege de breaking changes en versiones mayores
      # pero te permite recibir bugfixes y mejoras menores automáticamente.
    }
  }
}


# -----------------------------------------------------------------------------
# PROVIDER AWS
# Le dice a Terraform cómo conectarse a AWS: en qué región operar
# y qué tags aplicar automáticamente a TODOS los recursos.
# -----------------------------------------------------------------------------

provider "aws" {
  region = var.aws_region
  # Usa la variable definida en variables.tf.
  # Las credenciales (access key / secret key) NO van acá —
  # Terraform las toma del ambiente: variables de entorno AWS_ACCESS_KEY_ID
  # y AWS_SECRET_ACCESS_KEY, o del archivo ~/.aws/credentials.
  # Nunca hardcodees credenciales en código.

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      # Estos tres tags se aplican automáticamente a TODOS los recursos de AWS
      # que crea este proyecto. Sirven para:
      #   - Identificar en la consola qué es de este proyecto
      #   - Filtrar costos en AWS Cost Explorer por proyecto/entorno
      #   - Saber que un recurso fue creado por Terraform y no a mano
    }
  }
}


# -----------------------------------------------------------------------------
# LOCALS
# Valores calculados una sola vez y reutilizados en todos los archivos.
# La diferencia con variables: locals no los ingresa el usuario,
# los calcula Terraform a partir de otras variables o expresiones.
# -----------------------------------------------------------------------------

locals {

  # Prefijo estándar para nombrar recursos.
  # Resultado: "pps-prod"
  # Se usa así: "${local.prefix}-lambda", "${local.prefix}-bucket", etc.
  # Garantiza nombres consistentes en toda la infra.
  prefix = "${var.project_name}-${var.environment}"

  # Tags comunes adicionales para recursos que lo necesiten.
  # Se mergean con los default_tags del provider cuando se requiere
  # información extra en algún recurso específico.
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
