# =============================================================================
# LAMBDA.TF — Función principal + EventBridge + CloudWatch Logs
# =============================================================================
# Este archivo define el corazón del sistema:
#   1. CloudWatch Log Group — donde Lambda escribe sus logs
#   2. Lambda Function — la función Python que ejecuta el assessment
#   3. Lambda Permission — autoriza a EventBridge a invocar Lambda
#   4. EventBridge Rule — el schedule que dispara la ejecución
#   5. EventBridge Target — conecta el schedule con Lambda
#
# El orden de dependencias es:
#   Log Group → Lambda → Lambda Permission ← EventBridge Rule → EventBridge Target
# Terraform resuelve este grafo solo — no hace falta declarar el orden a mano.
# =============================================================================


# -----------------------------------------------------------------------------
# DATA SOURCE — empaquetado del código Python
# Terraform necesita subir el código de Lambda como un archivo .zip.
# archive_file toma la carpeta ../lambda/ y la comprime automáticamente
# cada vez que detecta cambios en los archivos Python.
# No crea ningún recurso en AWS — solo genera el zip localmente.
# -----------------------------------------------------------------------------

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/../lambda.zip"
  # path.module = directorio donde está este archivo (terraform/)
  # source_dir apunta a la carpeta lambda/ que está al mismo nivel
  # output_path es donde Terraform deposita el zip generado
  #
  # Cada vez que modificás handler.py y hacés terraform apply,
  # Terraform detecta que el zip cambió (via output_base64sha256)
  # y sube la nueva versión a Lambda automáticamente.
}


# -----------------------------------------------------------------------------
# CLOUDWATCH LOG GROUP
# Se crea ANTES que Lambda para evitar que AWS lo genere automáticamente
# con configuración por defecto (sin retención → logs infinitos = costo creciente).
# Con esto controlamos cuántos días se retienen los logs.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.prefix}-assessor"
  retention_in_days = 30
  # Por qué 30 días: suficiente para debuggear problemas del último mes
  # sin acumular logs indefinidamente. Podés bajarlo a 7 para reducir costos
  # o subirlo a 90 si necesitás historial para auditoría.
  #
  # El nombre /aws/lambda/<nombre-función> es el formato estándar de AWS.
  # Lambda escribe automáticamente en este grupo si el nombre coincide.
}


# -----------------------------------------------------------------------------
# LAMBDA FUNCTION
# La función principal del sistema. Recibe el evento de EventBridge,
# lee las credenciales de Secrets Manager, consulta FortiGate,
# analiza con Claude y deposita el reporte en S3.
# -----------------------------------------------------------------------------

resource "aws_lambda_function" "assessor" {
  function_name = "${local.prefix}-assessor"
  description   = "PPS Security Posture Assessment — queries FortiGate and analyzes against NIST CSF"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  # source_code_hash es el mecanismo de detección de cambios.
  # Si el hash del zip cambia, Terraform sube el nuevo código.
  # Si el hash es igual, Terraform no toca Lambda — evita deploys innecesarios.

  handler = "handler.lambda_handler"
  # Formato: <nombre_archivo>.<nombre_función>
  # Lambda busca el archivo handler.py y dentro de él la función lambda_handler.
  # Es el punto de entrada — la primera función que se ejecuta al invocarse.

  runtime     = "python3.12"
  timeout     = var.lambda_timeout
  memory_size = var.lambda_memory

  role = aws_iam_role.lambda_execution.arn
  # El rol que Lambda asume al ejecutar. Define qué puede hacer en AWS.
  # Definido en iam.tf.

  environment {
    variables = {
      FORTIGATE_HOST       = var.fortigate_host
      FORTIGATE_SECRET_ARN = aws_secretsmanager_secret.fortigate_token.arn
      CLAUDE_SECRET_ARN    = aws_secretsmanager_secret.claude_api_key.arn
      S3_BUCKET            = aws_s3_bucket.reports.bucket
      SNS_TOPIC_ARN        = aws_sns_topic.notifications.arn
    }
    # Las variables de entorno son la forma en que Terraform le pasa
    # información de infra al código Python sin hardcodear ARNs.
    # En handler.py se leen con os.environ["S3_BUCKET"], os.environ["FORTIGATE_HOST"], etc.
    # Son visibles en texto plano en la consola de Lambda —
    # por eso las credenciales van en Secrets Manager y no acá.
    #
    # NOTA (bug fix): este bloque antes seteaba REPORTS_BUCKET y omitía
    # FORTIGATE_HOST por completo. handler.py._get_required_env() lee S3_BUCKET
    # y FORTIGATE_HOST, así que un deploy real fallaba con statusCode 500 /
    # missing_env_vars pese a que la Lambda estaba "desplegada". Los tests
    # locales nunca lo detectaron porque el fixture required_env setea las
    # env vars directamente, sin pasar por Terraform. Se renombra la key acá
    # (en vez de leer REPORTS_BUCKET en handler.py) porque S3_BUCKET es el
    # nombre que ya usan los tests/fixtures y el resto del código Python.
  }

  depends_on = [
    aws_iam_role_policy.lambda_permissions,
    aws_cloudwatch_log_group.lambda
  ]
  # depends_on explícito porque estas dependencias no son evidentes para Terraform:
  # - La política IAM debe existir antes que Lambda intente ejecutar
  # - El Log Group debe existir antes que Lambda intente escribir logs
}


# -----------------------------------------------------------------------------
# LAMBDA PERMISSION
# Por defecto, nadie puede invocar una Lambda — ni siquiera otros servicios AWS.
# Este recurso le da permiso explícito a EventBridge para invocarla.
# Sin esto, EventBridge dispara el schedule pero Lambda rechaza la invocación.
# -----------------------------------------------------------------------------

resource "aws_lambda_permission" "eventbridge" {
  count = var.enable_legacy_nist_schedule ? 1 : 0

  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.assessor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule[0].arn
  # source_arn restringe el permiso: solo ESTA regla de EventBridge puede invocar Lambda.
  # Sin source_arn, cualquier regla de EventBridge en la cuenta podría invocarla.
  #
  # count gateado por var.enable_legacy_nist_schedule: este permiso solo
  # tiene sentido si la regla existe (ver aws_cloudwatch_event_rule.schedule
  # abajo). Sin este count, apagar el flag rompería el plan/apply porque
  # source_arn intentaría leer schedule[0] cuando count=0 no lo crea.
}


# -----------------------------------------------------------------------------
# EVENTBRIDGE RULE — el schedule (flujo NIST legacy)
# Define CUÁNDO se activa el assessor NIST CSF original. Usa la expresión
# cron de variables.tf. Por defecto: todos los días a las 6am UTC.
#
# Gateado por var.enable_legacy_nist_schedule (tasks.md 2.8, design.md
# decisión #9 "NIST rollback flag"): en true durante la migración al flujo
# policy-driven (policy_generator/audit_executor abajo); pasarlo a false
# borra únicamente esta regla y su target — la Lambda "assessor" y su
# código quedan intactos, solo dejan de dispararse por schedule.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "schedule" {
  count = var.enable_legacy_nist_schedule ? 1 : 0

  name                = "${local.prefix}-schedule"
  description         = "Triggers PPS assessment on schedule"
  schedule_expression = var.schedule_expression
  # La regla solo define el "cuándo". El "qué hacer" lo define el Target abajo.
  # Es la separación de responsabilidades de EventBridge.
}


# -----------------------------------------------------------------------------
# EVENTBRIDGE TARGET — conecta el schedule con Lambda (flujo NIST legacy)
# Le dice a EventBridge: "cuando dispare esta regla, invocá esta Lambda".
# Sin el Target, la regla dispara pero no hace nada.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_event_target" "lambda" {
  count = var.enable_legacy_nist_schedule ? 1 : 0

  rule      = aws_cloudwatch_event_rule.schedule[0].name
  target_id = "PpsAssessorTarget"
  arn       = aws_lambda_function.assessor.arn
  # target_id es un identificador único dentro de la regla.
  # Una regla puede tener múltiples targets (ej: Lambda + SQS al mismo tiempo).
  # En nuestro caso solo tenemos uno.
}


# =============================================================================
# LAMBDA LAYER — pps-doc-parsers
# =============================================================================
# pypdf + python-docx (+lxml), pineados para manylinux2014_x86_64 / Python
# 3.12 (ver design.md, decisión #8). Solo se adjunta a policy_generator —
# audit_executor se mantiene stdlib-only a propósito, para minimizar su
# superficie de dependencias dado que es el rol con acceso real a FortiGate.
#
# El zip lo genera scripts/build_layer.sh — correrlo ANTES de cualquier
# terraform init/plan/apply que toque este recurso, si no filebase64sha256
# falla porque el archivo todavía no existe.
# =============================================================================

resource "aws_lambda_layer_version" "doc_parsers" {
  layer_name  = "${local.prefix}-doc-parsers"
  description = "pypdf + python-docx + lxml (manylinux2014_x86_64) para parsing de políticas PDF/DOCX"

  filename         = "${path.module}/../layers/pps-doc-parsers.zip"
  source_code_hash = filebase64sha256("${path.module}/../layers/pps-doc-parsers.zip")

  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["x86_64"]
}


# =============================================================================
# LAMBDA — POLICY_GENERATOR
# =============================================================================
# Entrypoint disparado por la subida de una política a S3 (ver storage.tf,
# aws_s3_bucket_notification.policies_upload). Extrae texto, arma chunks,
# hace map/reduce con Claude, valida el script resultante, reintenta si
# hace falta, y termina invocando audit_executor de forma asíncrona.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "policy_generator" {
  name              = "/aws/lambda/${local.prefix}-policy-generator"
  retention_in_days = 30
}

resource "aws_lambda_function" "policy_generator" {
  function_name = "${local.prefix}-policy-generator"
  description   = "PPS Policy Generator — extracts+chunks an uploaded policy, generates and validates an audit script via Claude, invokes audit_executor"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  # Reutiliza el mismo zip que "assessor": todos los .py de lambda/ viven
  # sueltos en la misma carpeta y el runtime de Lambda los deposita todos
  # en la raíz del paquete desplegado, así que un único archive_file sirve
  # para las tres funciones — cada una define su propio "handler".

  handler = "handler_generator.lambda_handler"
  runtime = "python3.12"
  timeout = var.generator_timeout
  # 900s — ver variables.tf, generator_timeout.
  memory_size = 1024
  # 1024MB (vs. 512MB del assessor legacy): map/reduce contra chunks de
  # texto largos + parsing de PDF/DOCX vía la layer necesitan más CPU/RAM
  # que el workload I/O-bound del assessor original.

  layers = [aws_lambda_layer_version.doc_parsers.arn]

  role = aws_iam_role.generator.arn
  # Rol de mínimo privilegio definido en iam.tf — NO comparte el rol del
  # assessor legacy ni el de audit_executor.

  environment {
    variables = {
      CLAUDE_SECRET_ARN       = aws_secretsmanager_secret.claude_api_key.arn
      POLICIES_BUCKET         = aws_s3_bucket.policies.bucket
      S3_BUCKET               = aws_s3_bucket.reports.bucket
      EXECUTOR_FUNCTION_NAME  = aws_lambda_function.audit_executor.function_name
      MAX_GENERATION_ATTEMPTS = var.max_generation_attempts
    }
    # S3_BUCKET es el bucket de reports/artifacts (prefijo artifacts/*),
    # mismo nombre de variable que ya usa handler.py, para que s3_io.py
    # (Fase 6) trate policy_generator y audit_executor de forma uniforme.
    # POLICIES_BUCKET es el bucket de entrada — solo lectura para esta
    # función (ver iam.tf, ReadPolicyUploads/ListPolicyUploads).
  }

  depends_on = [
    aws_iam_role_policy.generator_permissions,
    aws_cloudwatch_log_group.policy_generator
  ]
}


# =============================================================================
# LAMBDA — AUDIT_EXECUTOR
# =============================================================================
# Entrypoint invocado de forma asíncrona por policy_generator. Re-valida el
# script recibido de forma independiente, lo ejecuta bajo sandbox con el
# toolkit fgt/report, y publica el reporte final (S3 + SNS).
# Stdlib-only a propósito — sin layer adjunta (ver design.md, decisión #8).
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "audit_executor" {
  name              = "/aws/lambda/${local.prefix}-audit-executor"
  retention_in_days = 30
}

resource "aws_lambda_function" "audit_executor" {
  function_name = "${local.prefix}-audit-executor"
  description   = "PPS Audit Executor — re-validates and sandboxes the generated script, queries FortiGate through the toolkit, publishes the audit report"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  handler = "handler_executor.lambda_handler"
  runtime = "python3.12"
  timeout = var.executor_timeout
  # 300s — ver variables.tf, executor_timeout.
  memory_size = 512

  role = aws_iam_role.executor.arn
  # Rol de mínimo privilegio definido en iam.tf — deliberadamente no es
  # superset ni subset del rol del generador (ver iam.tf).

  environment {
    variables = {
      FORTIGATE_HOST             = var.fortigate_host
      FORTIGATE_SECRET_ARN       = aws_secretsmanager_secret.fortigate_token.arn
      S3_BUCKET                  = aws_s3_bucket.reports.bucket
      SNS_TOPIC_ARN              = aws_sns_topic.notifications.arn
      SANDBOX_WALL_CLOCK_SECONDS = var.sandbox_wall_clock_seconds
      SANDBOX_MAX_FGT_CALLS      = var.sandbox_max_fgt_calls
    }
    # S3_BUCKET es el mismo bucket de reports que usa policy_generator —
    # audit_executor lee artifacts/* y escribe reports/* dentro de él
    # (ver iam.tf, ReadGeneratedArtifacts/WriteAuditReports). Nunca toca
    # el bucket de políticas: su rol no tiene permiso sobre él.
  }

  depends_on = [
    aws_iam_role_policy.executor_permissions,
    aws_cloudwatch_log_group.audit_executor
  ]
}


# -----------------------------------------------------------------------------
# OUTPUTS
# -----------------------------------------------------------------------------

output "lambda_function_name" {
  value       = aws_lambda_function.assessor.function_name
  description = "Name of the Lambda function"
}

output "lambda_function_arn" {
  value       = aws_lambda_function.assessor.arn
  description = "ARN of the Lambda function"
}

output "policy_generator_function_name" {
  value       = aws_lambda_function.policy_generator.function_name
  description = "Name of the policy_generator Lambda function"
}

output "policy_generator_function_arn" {
  value       = aws_lambda_function.policy_generator.arn
  description = "ARN of the policy_generator Lambda function"
}

output "audit_executor_function_name" {
  value       = aws_lambda_function.audit_executor.function_name
  description = "Name of the audit_executor Lambda function"
}

output "audit_executor_function_arn" {
  value       = aws_lambda_function.audit_executor.arn
  description = "ARN of the audit_executor Lambda function"
}
