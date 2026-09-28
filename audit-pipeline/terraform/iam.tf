# =============================================================================
# IAM.TF — Permisos de ejecución de Lambda
# =============================================================================
# Este archivo define QUÉ puede hacer Lambda dentro de AWS.
# IAM es el sistema de permisos de AWS — sin esto, Lambda no puede
# leer secrets, escribir en S3, publicar en SNS ni guardar logs.
#
# Principio de mínimo privilegio: Lambda recibe SOLO los permisos
# que necesita, sobre SOLO los recursos que usa. Nada más.
# Esto limita el daño si la función fuera comprometida.
# =============================================================================


# -----------------------------------------------------------------------------
# ROL DE EJECUCIÓN
# En AWS, una función Lambda no usa credenciales de usuario — asume un ROL.
# El rol es una identidad temporal que AWS le asigna a Lambda al arrancar.
# La "trust policy" define quién puede asumir este rol — en este caso,
# solo el servicio Lambda (lambda.amazonaws.com).
# -----------------------------------------------------------------------------

resource "aws_iam_role" "lambda_execution" {
  name        = "${local.prefix}-lambda-role"
  description = "Execution role for PPS Lambda — grants access to required AWS services"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
        # Esto dice: "el servicio Lambda tiene permitido asumir este rol".
        # Sin este Statement, ningún servicio podría usar el rol —
        # ni siquiera Lambda misma.
      }
    ]
  })
}


# -----------------------------------------------------------------------------
# POLÍTICA DE PERMISOS
# Define las acciones concretas que Lambda puede ejecutar y sobre qué recursos.
# Se adjunta al rol de ejecución creado arriba.
# -----------------------------------------------------------------------------

resource "aws_iam_role_policy" "lambda_permissions" {
  name = "${local.prefix}-lambda-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [

      # ------------------------------------------------------------------
      # SECRETS MANAGER — leer credenciales
      # Lambda necesita leer los dos secrets al inicio de cada ejecución:
      # el token de FortiGate y la API key de Claude.
      # El permiso apunta a los ARNs exactos — no a todos los secrets.
      # ------------------------------------------------------------------
      {
        Sid    = "ReadSecrets"
        Effect = "Allow"
        Action = "secretsmanager:GetSecretValue"
        Resource = [
          aws_secretsmanager_secret.fortigate_token.arn,
          aws_secretsmanager_secret.claude_api_key.arn
        ]
      },

      # ------------------------------------------------------------------
      # S3 — escribir reportes
      # Lambda sube el reporte JSON generado al bucket de S3.
      # Solo necesita PutObject — no puede listar, leer ni borrar objetos.
      # El /* al final del ARN significa "cualquier objeto dentro del bucket".
      # ------------------------------------------------------------------
      {
        Sid    = "WriteReports"
        Effect = "Allow"
        Action = "s3:PutObject"
        Resource = "${aws_s3_bucket.reports.arn}/*"
      },

      # NOTA: este bloque es el rol del assessor NIST legacy (handler.py),
      # gateado por var.enable_legacy_nist_schedule en lambda.tf. Los roles
      # del flujo policy-driven (generator/executor) están más abajo, cada
      # uno con su propio principio de mínimo privilegio — no comparten
      # este rol a propósito.

      # ------------------------------------------------------------------
      # SNS — publicar notificaciones
      # Lambda publica un mensaje al topic cuando termina el assessment.
      # Solo necesita Publish — no puede crear topics ni cambiar suscripciones.
      # ------------------------------------------------------------------
      {
        Sid      = "PublishNotifications"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.notifications.arn
      },

      # ------------------------------------------------------------------
      # CLOUDWATCH LOGS — escribir logs de ejecución
      # Lambda necesita estos tres permisos para poder escribir sus logs.
      # Sin esto, cualquier print() o error en Python desaparece en el vacío.
      # El Resource "*" es necesario porque el Log Group se crea
      # automáticamente la primera vez que Lambda ejecuta.
      # ------------------------------------------------------------------
      {
        Sid    = "WriteLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }

    ]
  })
}


# =============================================================================
# ROL — POLICY_GENERATOR
# =============================================================================
# Extrae texto de la política subida, arma prompts para Claude (map/reduce),
# valida el script generado y lo escribe en el bucket de reports (prefijo
# artifacts/*). Termina invocando audit_executor de forma asíncrona.
#
# NO tiene acceso al secret de FortiGate: el generador nunca llama al
# firewall, solo genera código (ver design.md, decisiones #5 y #7). Si este
# rol se viera comprometido, no podría alcanzar la red del FortiGate.
# =============================================================================

resource "aws_iam_role" "generator" {
  name        = "${local.prefix}-generator-role"
  description = "Execution role for policy_generator Lambda — reads policy uploads, calls Claude, writes generated scripts, invokes audit_executor"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "generator_permissions" {
  name = "${local.prefix}-generator-policy"
  role = aws_iam_role.generator.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [

      # ------------------------------------------------------------------
      # SECRETS MANAGER — leer solo el secret de Claude
      # El generador llama a Claude para el map/reduce de generación de
      # scripts. No lee (ni tiene permiso de leer) el secret de FortiGate.
      # ------------------------------------------------------------------
      {
        Sid      = "ReadClaudeSecret"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_secretsmanager_secret.claude_api_key.arn
      },

      # ------------------------------------------------------------------
      # S3 — leer políticas subidas
      # GetObject para bajar el PDF/DOCX que disparó la invocación;
      # ListBucket para poder resolver claves cuando hace falta.
      # ------------------------------------------------------------------
      {
        Sid      = "ReadPolicyUploads"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.policies.arn}/*"
      },
      {
        Sid      = "ListPolicyUploads"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.policies.arn
      },

      # ------------------------------------------------------------------
      # S3 — escribir artifacts generados
      # Script + manifest van al bucket de reports, prefijo artifacts/*.
      # Nunca escribe en el bucket de políticas — evita el loop de
      # notificación descripto en storage.tf.
      # ------------------------------------------------------------------
      {
        Sid      = "WriteGeneratedArtifacts"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.reports.arn}/artifacts/*"
      },

      # ------------------------------------------------------------------
      # LAMBDA — invocar audit_executor
      # Invocación asíncrona (InvocationType=Event) con el puntero
      # {run_id, manifest_key, script_key, script_sha256} — ver design.md.
      # ------------------------------------------------------------------
      {
        Sid      = "InvokeAuditExecutor"
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.audit_executor.arn
      },

      # ------------------------------------------------------------------
      # CLOUDWATCH LOGS
      # ------------------------------------------------------------------
      {
        Sid    = "WriteLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }

    ]
  })
}


# =============================================================================
# ROL — AUDIT_EXECUTOR
# =============================================================================
# Re-valida el script (independiente de la validación que ya hizo el
# generador), lo ejecuta bajo el sandbox con el toolkit fgt/report, y
# publica el reporte final. Es el único rol con acceso real a FortiGate.
#
# Deliberadamente NO es un superset del rol del generador, ni al revés
# (tasks.md 2.3): no tiene el secret de Claude, no puede leer el bucket de
# políticas ni invocar otras Lambdas. Si este rol se viera comprometido,
# no podría generar ni modificar scripts — solo ejecutar el que ya fue
# validado y firmado (script_sha256) por el generador.
# =============================================================================

resource "aws_iam_role" "executor" {
  name        = "${local.prefix}-executor-role"
  description = "Execution role for audit_executor Lambda — re-validates and runs the generated script under sandbox, reads FortiGate, writes the audit report"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "executor_permissions" {
  name = "${local.prefix}-executor-policy"
  role = aws_iam_role.executor.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [

      # ------------------------------------------------------------------
      # SECRETS MANAGER — leer solo el secret de FortiGate
      # ------------------------------------------------------------------
      {
        Sid      = "ReadFortiGateSecret"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_secretsmanager_secret.fortigate_token.arn
      },

      # ------------------------------------------------------------------
      # S3 — leer el artifact generado (script + manifest)
      # ------------------------------------------------------------------
      {
        Sid      = "ReadGeneratedArtifacts"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.reports.arn}/artifacts/*"
      },

      # ------------------------------------------------------------------
      # S3 — escribir el reporte final
      # ------------------------------------------------------------------
      {
        Sid      = "WriteAuditReports"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.reports.arn}/reports/*"
      },

      # ------------------------------------------------------------------
      # SNS — notificar que el reporte terminó
      # ------------------------------------------------------------------
      {
        Sid      = "PublishNotifications"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.notifications.arn
      },

      # ------------------------------------------------------------------
      # CLOUDWATCH LOGS
      # ------------------------------------------------------------------
      {
        Sid    = "WriteLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }

    ]
  })
}
