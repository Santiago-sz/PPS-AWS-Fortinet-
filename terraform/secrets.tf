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
    host  = var.fortigate_host
  })
  # Por qué guardamos host acá también: Lambda lee UN solo secret y tiene
  # todo lo que necesita para conectarse — token + destino.
  # Evita que Lambda dependa de variables de entorno para el host.
  #
  # Después del primer apply, actualizá este secret con el token real:
  # aws secretsmanager put-secret-value \
  #   --secret-id pps-prod-fortigate-token \
  #   --secret-string '{"token":"TU_TOKEN_REAL","host":"IP_FORTIGATE"}'
}


# -----------------------------------------------------------------------------
# SECRET — API KEY DE CLAUDE (ANTHROPIC)
# Almacena la API key que Lambda usa para llamar a Claude y analizar
# los datos del FortiGate contra el framework NIST CSF.
# -----------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "claude_api_key" {
  name        = "${local.prefix}-claude-api-key"
  description = "Anthropic Claude API key for NIST CSF analysis"

  recovery_window_in_days = 0
  # Mismo criterio que el secret anterior — entorno de pruebas, borrado inmediato.
}

resource "aws_secretsmanager_secret_version" "claude_api_key" {
  secret_id = aws_secretsmanager_secret.claude_api_key.id

  secret_string = jsonencode({
    api_key = "REEMPLAZAR_CON_API_KEY_REAL"
  })
  # Después del primer apply, actualizá con tu API key real de Anthropic:
  # aws secretsmanager put-secret-value \
  #   --secret-id pps-prod-claude-api-key \
  #   --secret-string '{"api_key":"sk-ant-XXXXXXXX"}'
}


# -----------------------------------------------------------------------------
# OUTPUTS — ARNs de los secrets
# Los ARNs se pasan al IAM role y a Lambda para que sepan exactamente
# a qué secrets tienen permiso de acceder. Sin el ARN exacto, el permiso
# IAM sería demasiado amplio (acceso a TODOS los secrets de la cuenta).
# -----------------------------------------------------------------------------

output "fortigate_secret_arn" {
  value       = aws_secretsmanager_secret.fortigate_token.arn
  description = "ARN of the FortiGate API token secret"
}

output "claude_secret_arn" {
  value       = aws_secretsmanager_secret.claude_api_key.arn
  description = "ARN of the Claude API key secret"
}
