# =============================================================================
# SECRETS.TF — Gestión de credenciales con AWS Secrets Manager
# =============================================================================
# Este archivo crea los "contenedores" seguros donde se guardan las
# credenciales sensibles del proyecto. Separa los secrets de la infra
# porque tienen un ciclo de vida diferente: la infra se destruye y recrea,
# los secrets se rotan sin tocar Terraform.
#
# IMPORTANTE: Terraform crea los contenedores (aws_secretsmanager_secret)
# pero NO carga los valores. Los valores los cargás vos a mano UNA sola vez
# después del primer terraform apply, usando AWS CLI o la consola.
# Esto es intencional — evita que las credenciales queden en el estado
# de Terraform (.tfstate), que podría ser leído por alguien con acceso al repo.
#
# El único secret del proyecto es el token de FortiGate. El modelo (Claude)
# se alcanza vía Amazon Bedrock con la identidad IAM del rol de cada Lambda
# (ver iam.tf, Sid InvokeBedrockModel) — no existe ninguna API key.
# =============================================================================


# -----------------------------------------------------------------------------
# SECRET — TOKEN DE API DE FORTIGATE
# Almacena el token que Lambda usa para autenticarse contra la REST API
# del FortiGate. Se envía en cada request como header: Authorization: Bearer <token>
# -----------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "fortigate_token" {
  name        = "${local.prefix}-fortigate-token"
  description = "FortiGate REST API token for PPS Lambda authentication"

  recovery_window_in_days = 0
  # Por qué 0: por defecto AWS espera 30 días antes de borrar un secret.
  # Con 0 se borra inmediatamente al hacer terraform destroy.
  # En un entorno de pruebas esto es lo que queremos — sin residuos.
  # En producción real usá 7 o 30 días como red de seguridad.
}

resource "aws_secretsmanager_secret_version" "fortigate_token" {
  secret_id = aws_secretsmanager_secret.fortigate_token.id

  secret_string = jsonencode({
    token = "REEMPLAZAR_CON_TOKEN_REAL"
  })
  # El secret contiene SOLO el token. El destino lo define la variable de
  # entorno FORTIGATE_HOST (var.fortigate_host, ver lambda.tf): los handlers
  # ignoran cualquier campo `host` dentro del secret (ver SECRETS.md), así
  # que guardarlo acá solo generaría una fuente de verdad duplicada.
  #
  # Después del primer apply, actualizá este secret con el token real:
  # aws secretsmanager put-secret-value \
  #   --secret-id pps-prod-fortigate-token \
  #   --secret-string '{"token":"TU_TOKEN_REAL"}'

  lifecycle {
    ignore_changes = [secret_string]
    # Una vez cargado el token real por fuera de Terraform, un apply
    # posterior NO debe volver a pisarlo con el placeholder. Terraform solo
    # crea la versión inicial; el valor vivo lo gobierna Secrets Manager.
  }
}

# El output fortigate_secret_arn vive en outputs.tf (set canónico único).
