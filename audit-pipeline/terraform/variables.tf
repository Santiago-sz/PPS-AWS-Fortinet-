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
  # y donde el perfil de inferencia cross-region de Amazon Bedrock
  # (`us.anthropic.*`, ver bedrock_model_id) tiene capacidad para Claude.
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
  # IMPORTANTE: el certificado del FortiGate suele ser autofirmado. El
  # cliente Python verifica TLS por defecto (FORTIGATE_VERIFY_SSL=true);
  # solo en laboratorios con certificado self-signed poner
  # fortigate_verify_ssl=false. En producción instalar un certificado válido.
}

variable "fortigate_verify_ssl" {
  description = "Verificar el certificado TLS del FortiGate en audit_executor y assessor (env FORTIGATE_VERIFY_SSL). Poner false SOLO en laboratorios con certificado autofirmado; en producción dejar true"
  type        = bool
  default     = true
  # Se inyecta como env FORTIGATE_VERIFY_SSL (string "true"/"false") en las
  # dos Lambdas que hablan con el FortiGate. Con false el cliente ignora el
  # certificado (CERT_NONE), lo que habilita un MITM: nunca en producción.
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
  description = "Habilita el schedule EventBridge legacy que dispara el assessor NIST CSF original (handler.py/analyzer.py). false por defecto: el flujo policy-driven es el camino de Fase 1; la Lambda assessor sigue desplegada y puede invocarse a mano o re-habilitarse con true"
  type        = bool
  default     = false
  # false por defecto: la regla/target de EventBridge no se crean, pero la
  # Lambda "assessor" y su rol siguen existiendo (deployables, invocables a
  # mano con `aws lambda invoke`). Pasar a true restituye el schedule diario
  # sin tocar código — es el camino de rollback documentado en design.md,
  # decisión #9 y "Migration/Rollout".
}

variable "log_retention_days" {
  description = "Retención (días) de todos los log groups de CloudWatch del proyecto: las tres Lambdas y el log de invocaciones de Bedrock"
  type        = number
  default     = 365
  # 365 por defecto: los logs son la evidencia de ejecución de cada
  # auditoría (eventos JSON `generator_result`/`executor_result`, métricas
  # EMF) y su volumen es bajo. Valores válidos: los que acepta CloudWatch
  # (1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, ...).
}

variable "artifact_retention_days" {
  description = "Días tras los cuales expiran los objetos artifacts/* (script + manifest generados) del bucket de reports"
  type        = number
  default     = 365
}

variable "report_retention_days" {
  description = "Días tras los cuales expiran los objetos reports/* (report.md/report.json) del bucket de reports"
  type        = number
  default     = 365
  # Los reportes son el entregable de cada auditoría: si se necesita
  # conservarlos como evidencia a largo plazo, subir este valor o exportarlos
  # antes de que expiren (la app de escritorio los sincroniza localmente
  # con `pps-api aws sync`).
}

variable "executor_subnet_ids" {
  description = "Subnets (privadas) donde colocar audit_executor para alcanzar un FortiGate por IP privada/VPN. Vacío (default) = sin VPC. Debe definirse junto con executor_security_group_ids"
  type        = list(string)
  default     = []
}

variable "executor_security_group_ids" {
  description = "Security groups de audit_executor cuando corre dentro de una VPC (egress HTTPS hacia el FortiGate + hacia los endpoints de AWS). Vacío (default) = sin VPC"
  type        = list(string)
  default     = []
}

variable "enable_bedrock_invocation_logging" {
  description = "Crea la configuración de Model Invocation Logging de Amazon Bedrock hacia CloudWatch Logs (/aws/bedrock/<prefix>-model-invocations). ATENCIÓN: esta configuración es ÚNICA por cuenta y región (account-wide): si la cuenta ya tiene una, este recurso la pisa. Poner en false para no tocarla"
  type        = bool
  default     = true
  # Registra prompt + respuesta de CADA invocación del modelo en la cuenta/
  # región (no solo las de este proyecto). Es la evidencia primaria para la
  # tesis (qué se le pidió al modelo y qué devolvió), pero el log contiene
  # el texto de las políticas auditadas: tratar el log group como dato
  # sensible. Ver bedrock_logging.tf.
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

variable "bedrock_model_id" {
  description = "Id del modelo/perfil de inferencia de Amazon Bedrock que usan assessor y policy_generator (env BEDROCK_MODEL_ID). Es un INFERENCE PROFILE cross-region, no un foundation-model id: verificar que exista y tenga acceso habilitado en la cuenta/región con `aws bedrock list-inference-profiles --region <aws_region>`"
  type        = string
  default     = "us.anthropic.claude-sonnet-4-6"
  # El prefijo `us.` indica un perfil de inferencia cross-region (enruta a
  # las regiones US donde el modelo tenga capacidad). Para desplegar en
  # otra geografía usar el prefijo correspondiente (`eu.`, `apac.`) o un
  # perfil de aplicación propio. El acceso al modelo se habilita una sola
  # vez por cuenta/región en la consola de Bedrock ("Model access"); sin
  # eso la Lambda falla con AccessDeniedException aunque IAM esté bien.
}

variable "auto_execute" {
  description = "Si es true, policy_generator invoca automáticamente a audit_executor tras generar y firmar el script. Si es false, deja script+manifest en S3 y devuelve status=awaiting_approval para que un operador invoque al executor manualmente (compuerta humana)"
  type        = bool
  default     = true
  # Se inyecta como env AUTO_EXECUTE (string "true"/"false"). Útil para
  # revisar el script generado antes de que toque el FortiGate.
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
