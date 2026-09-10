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
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.assessor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
  # source_arn restringe el permiso: solo ESTA regla de EventBridge puede invocar Lambda.
  # Sin source_arn, cualquier regla de EventBridge en la cuenta podría invocarla.
}


# -----------------------------------------------------------------------------
# EVENTBRIDGE RULE — el schedule
# Define CUÁNDO se activa el sistema. Usa la expresión cron de variables.tf.
# Por defecto: todos los días a las 6am UTC.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${local.prefix}-schedule"
  description         = "Triggers PPS assessment on schedule"
  schedule_expression = var.schedule_expression
  # La regla solo define el "cuándo". El "qué hacer" lo define el Target abajo.
  # Es la separación de responsabilidades de EventBridge.
}


# -----------------------------------------------------------------------------
# EVENTBRIDGE TARGET — conecta el schedule con Lambda
# Le dice a EventBridge: "cuando dispare esta regla, invocá esta Lambda".
# Sin el Target, la regla dispara pero no hace nada.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = "PpsAssessorTarget"
  arn       = aws_lambda_function.assessor.arn
  # target_id es un identificador único dentro de la regla.
  # Una regla puede tener múltiples targets (ej: Lambda + SQS al mismo tiempo).
  # En nuestro caso solo tenemos uno.
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
