# =============================================================================
# VARIABLES DE CONFIGURACIÓN — PPS (Posture Assessment System)
# =============================================================================
# Este archivo centraliza toda la configuración del proyecto.
# Ningún otro archivo de Terraform debe tener valores hardcodeados —
# todo pasa por acá. Si necesitás cambiar algo, cambialo una sola vez aquí.
# =============================================================================


# -----------------------------------------------------------------------------
# REGIÓN Y ENTORNO
# -----------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region where all resources will be deployed"
  type        = string
  default     = "us-east-1"
  # Por qué us-east-1: es la región con mayor disponibilidad de servicios AWS
  # y menor latencia hacia la API de Anthropic (Claude), que está en US.
  # Si tu FortiGate está en otra región geográfica, evaluá cambiarla.
}

variable "project_name" {
  description = "Project name used as prefix for all resource names"
  type        = string
  default     = "pps"
  # Se usa como prefijo en TODOS los recursos: pps-lambda, pps-bucket, pps-topic, etc.
  # Esto permite identificar visualmente en la consola de AWS qué pertenece a este proyecto
  # y evita colisiones de nombres con otros proyectos en la misma cuenta.
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
  # Valores esperados: prod | dev | staging
  # Se usa como tag en los recursos. Permite filtrar en la consola y en billing
  # para saber cuánto cuesta cada entorno por separado.
}


# -----------------------------------------------------------------------------
# PROGRAMACIÓN DEL ASSESSMENT
# -----------------------------------------------------------------------------

variable "schedule_expression" {
  description = "EventBridge cron expression for assessment schedule"
  type        = string
  default     = "cron(0 6 * * ? *)"
  # Define CUÁNDO se ejecuta automáticamente el assessment.
  # El formato es cron de AWS (diferente al cron de Linux — tiene 6 campos).
  # "cron(0 6 * * ? *)" = todos los días a las 6:00 AM UTC.
  #
  # Ejemplos útiles:
  #   cron(0 6 * * ? *)     → diario a las 6am UTC
  #   cron(0 6 ? * MON *)   → cada lunes a las 6am UTC
  #   cron(0 6 1 * ? *)     → el primer día de cada mes a las 6am UTC
}


# -----------------------------------------------------------------------------
# NOTIFICACIONES
# -----------------------------------------------------------------------------

variable "notification_email" {
  description = "Email address to receive assessment notifications via SNS"
  type        = string
  # SIN default — tenés que proveerlo explícitamente.
  # Este email recibe una notificación cada vez que termina un assessment,
  # con el resumen del score NIST y el link al reporte en S3.
  #
  # IMPORTANTE: AWS SNS requiere que confirmes la suscripción haciendo click
  # en un email que te manda la primera vez que hacés terraform apply.
  # Hasta que no confirmés, los mensajes no llegan.
}


# -----------------------------------------------------------------------------
# CONECTIVIDAD CON FORTIGATE
# -----------------------------------------------------------------------------

variable "fortigate_host" {
  description = "FortiGate public IP or hostname (HTTPS, port 443)"
  type        = string
  # SIN default — tenés que proveerlo explícitamente.
  # Es la IP pública o dominio del FortiGate al que Lambda va a conectarse.
  # Lambda lo llama por HTTPS en el puerto 443 usando la REST API de FortiOS.
  #
  # Ejemplos válidos:
  #   "203.0.113.45"          → IP pública directa
  #   "firewall.miempresa.com" → hostname con DNS
  #
  # IMPORTANTE: el certificado del FortiGate suele ser autofirmado.
  # El cliente Python usa verify=False para no fallar por eso.
  # En producción real considerá instalar un certificado válido.
}


# -----------------------------------------------------------------------------
# PERFORMANCE DE LAMBDA
# -----------------------------------------------------------------------------

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 300
  # 300 segundos = 5 minutos. Límite máximo de Lambda: 900 segundos (15 min).
  # El assessment hace varias llamadas HTTP en secuencia:
  #   1. Secrets Manager (rápido ~100ms)
  #   2. FortiGate REST API (~500ms por endpoint, ~10 endpoints = ~5s)
  #   3. Claude API (puede tardar 10-30s dependiendo del prompt)
  #   4. S3 PutObject (~200ms)
  #   5. SNS Publish (~100ms)
  # Total estimado: 30-60 segundos. 300 deja margen amplio para reintentos.
}

variable "lambda_memory" {
  description = "Lambda function memory in MB"
  type        = number
  default     = 512
  # 512 MB es más que suficiente para Python + boto3 + requests.
  # En AWS Lambda, más memoria = más CPU asignada (están acoplados).
  # Con 512MB tenés ~0.5 vCPU equivalente, suficiente para I/O bound como este.
  # Subir a 1024MB no mejora este workload — las esperas son de red, no de CPU.
}


# -----------------------------------------------------------------------------
# FLUJO POLICY-DRIVEN (policy_generator + audit_executor)
# -----------------------------------------------------------------------------
# Variables específicas del nuevo flujo de generación de scripts de
# auditoría a partir de políticas subidas (PDF/DOCX). Ver design.md para
# el detalle de arquitectura — acá solo se centraliza lo configurable.
# -----------------------------------------------------------------------------

variable "enable_legacy_nist_schedule" {
  description = "Kill switch de migración: habilita el schedule EventBridge legacy que dispara el assessor NIST CSF original (handler.py/analyzer.py)"
  type        = bool
  default     = true
  # true por defecto durante la migración — el flujo legacy sigue corriendo
  # sin cambios en paralelo al nuevo flujo policy-driven. Una vez validado
  # el flujo nuevo, pasar a false (borra la regla/target de EventBridge sin
  # tocar la Lambda "assessor" ni su código) y eventualmente eliminar la
  # variable y el bloque legacy. Ver design.md, decisión #9 y "Migration/Rollout".
}

variable "generator_timeout" {
  description = "Timeout en segundos de la Lambda policy_generator (extract + chunk + map/reduce con Claude + validate + retry)"
  type        = number
  default     = 900
  # 900s = techo máximo de Lambda (15 min). El presupuesto de tiempo del
  # generador es el más ajustado de las dos funciones — ver design.md,
  # tabla "Time Budget": extract ≤60s, chunk ≤30s, map ≤240s,
  # reduce+validate 3×≤180s, write ≤20s.
}

variable "executor_timeout" {
  description = "Timeout en segundos de la Lambda audit_executor (re-validate + exec sandboxed + FortiGate + report)"
  type        = number
  default     = 300
  # 300s — re-validate ≤5s, exec hard cutoff 120s (ver sandbox_wall_clock_seconds),
  # FortiGate ocurre dentro de ese exec, report+SNS ≤30s. Deja margen sobre
  # el cutoff interno del sandbox.
}

variable "sandbox_wall_clock_seconds" {
  description = "Corte de tiempo real para el exec() del script generado dentro del sandbox (signal.setitimer)"
  type        = number
  default     = 120
  # Ver design.md, "Runtime caps": MAX_WALL_CLOCK_S. Denegar While/Try en
  # el AST hace que este corte sea imposible de capturar/ignorar desde el
  # script generado.
}

variable "sandbox_max_fgt_calls" {
  description = "Cantidad máxima de llamadas a fgt.get() permitidas por ejecución del script dentro del sandbox, antes de abortar con SandboxBudgetExceeded"
  type        = number
  default     = 40
  # Ver design.md, "Runtime caps": MAX_FGT_CALLS. Protege al FortiGate de
  # un script generado que quede en loop consultando el mismo endpoint.
}

variable "max_generation_attempts" {
  description = "Cantidad máxima de intentos de generación (map/reduce + validate) antes de reportar status=generation_failed"
  type        = number
  default     = 3
  # Ver design.md, decisión #7 y "Retry feedback": cada intento fallido
  # reenvía el script previo + feedback estructurado de la validación.
  # Agotado el presupuesto, se reporta el fallo explícitamente — nunca un
  # audit parcial.
}
