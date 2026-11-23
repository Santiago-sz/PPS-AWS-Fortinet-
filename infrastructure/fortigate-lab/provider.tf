# La cuenta de destino se elige con el perfil de AWS CLI, nunca con un id de
# cuenta escrito en el código. Las credenciales se obtienen con
# `aws login --profile <perfil>` y no se guardan en este módulo.
provider "aws" {
  profile = var.aws_profile
  region  = var.aws_region

  default_tags {
    tags = {
      Project     = "PostureGuard"
      Component   = "fortigate-lab"
      Environment = "lab"
      ManagedBy   = "terraform"
    }
  }
}
