"""
Handler principal de la Lambda PPS (Posture Assessment System).

Este es el entry point que AWS invoca cuando EventBridge dispara la función.
Su única responsabilidad es orquestar el flujo completo:

  1. Leer configuración desde variables de entorno
  2. Obtener credenciales desde Secrets Manager
  3. Recolectar datos del FortiGate
  4. Analizar contra NIST CSF 2.0 usando Claude
  5. Generar reporte, subir a S3, publicar en SNS
  6. Devolver resultado estructurado a Lambda

Principio: este archivo no contiene lógica de negocio.
Cada paso está delegado a su módulo correspondiente.
"""

import logging
import os
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from analyzer import analyze
from fortigate_client import FortiGateClient
from reporter import (
    build_markdown_report,
    build_sns_message,
    generate_s3_key_prefix,
    publish_to_sns,
    upload_to_s3,
)

# ─── Logging ──────────────────────────────────────────────────────────────────
# Lambda captura stdout/stderr y los manda a CloudWatch Logs automáticamente.
# Configuramos el nivel desde una variable de entorno para poder activar DEBUG
# en producción sin redesplegar — útil cuando hay que diagnosticar un problema.
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Variables de entorno ─────────────────────────────────────────────────────
# Todas las configuraciones vienen de variables de entorno — nunca hardcodeadas.
# Terraform las inyecta en lambda.tf via environment { variables = { ... } }.
# Fallar rápido (KeyError) en el módulo load es mejor que fallar a mitad del
# flujo cuando ya gastamos tokens de Claude.
def _get_required_env(name: str) -> str:
    """Lee una variable de entorno obligatoria. Falla explícitamente si falta."""
    value = os.environ.get(name)
    if not value:
        raise OSError(
            f"Variable de entorno requerida no configurada: '{name}'. "
            f"Verificar lambda.tf → environment.variables"
        )
    return value


# ─── Secrets Manager ─────────────────────────────────────────────────────────
def get_secret(secret_arn: str) -> str:
    """
    Lee un secret de AWS Secrets Manager y devuelve su valor como string.

    Por qué Secrets Manager en lugar de variables de entorno para credenciales:
    - Las env vars de Lambda son visibles en la consola AWS para cualquiera
      con permisos de DescribeFunction
    - Secrets Manager cifra en reposo con KMS, tiene rotación automática
      y registro de cada acceso en CloudTrail
    - El IAM role de la Lambda solo tiene GetSecretValue para estos ARNs
      específicos — principio de mínimo privilegio

    El cliente boto3 se crea dentro de la función y no a nivel de módulo
    para facilitar el mocking en tests unitarios.
    """
    sm = boto3.client("secretsmanager")

    try:
        response = sm.get_secret_value(SecretId=secret_arn)
        # Secrets Manager puede devolver el valor en SecretString (texto/JSON)
        # o SecretBinary (binario cifrado). Nosotros siempre usamos SecretString.
        secret = response.get("SecretString")
        if not secret:
            raise ValueError(f"El secret {secret_arn} no tiene SecretString")
        return secret

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        # ResourceNotFoundException: el ARN no existe — Terraform no lo creó
        # AccessDeniedException: el IAM role no tiene permiso — revisar iam.tf
        logger.error(
            "No se pudo leer el secret %s — código: %s — %s",
            secret_arn,
            error_code,
            e.response["Error"]["Message"],
        )
        raise


# ─── Handler principal ────────────────────────────────────────────────────────
def lambda_handler(event: dict, context) -> dict:
    """
    Entry point de AWS Lambda.

    AWS invoca esta función con:
      event:   dict con el payload del evento (EventBridge manda metadatos del schedule)
      context: objeto con info del runtime (función, versión, tiempo restante, etc.)

    Siempre devuelve un dict con statusCode para que EventBridge pueda
    registrar si la ejecución fue exitosa o fallida.
    """
    # Timestamp de inicio — lo usamos en el nombre del reporte y los logs
    run_ts = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    logger.info("=== PPS Assessment iniciado — %s ===", run_ts)
    logger.info("Lambda RequestId: %s", context.aws_request_id)

    # ── 1. Leer configuración ─────────────────────────────────────────────────
    try:
        fortigate_host = _get_required_env("FORTIGATE_HOST")
        fortigate_secret_arn = _get_required_env("FORTIGATE_SECRET_ARN")
        claude_secret_arn = _get_required_env("CLAUDE_SECRET_ARN")
        s3_bucket = _get_required_env("S3_BUCKET")
        sns_topic_arn = _get_required_env("SNS_TOPIC_ARN")
        environment = os.environ.get("ENVIRONMENT", "production")
        # verify_ssl puede desactivarse en labs con certificados self-signed
        verify_ssl = os.environ.get("FORTIGATE_VERIFY_SSL", "true").lower() == "true"
    except OSError as e:
        logger.critical("Configuración incompleta: %s", str(e))
        return {"statusCode": 500, "error": "missing_env_vars", "detail": str(e)}

    device_info = {
        "host": fortigate_host,
        "environment": environment,
        "region": os.environ.get("AWS_REGION", "us-east-1"),
        "run_ts": run_ts,
    }

    # ── 2. Obtener credenciales ───────────────────────────────────────────────
    logger.info("Leyendo credenciales desde Secrets Manager")
    try:
        fortigate_token = get_secret(fortigate_secret_arn)
        claude_api_key = get_secret(claude_secret_arn)
    except (ClientError, ValueError) as e:
        logger.critical("No se pudieron obtener las credenciales: %s", str(e))
        return {"statusCode": 500, "error": "secrets_error", "detail": str(e)}

    # ── 3. Recolectar datos del FortiGate ─────────────────────────────────────
    logger.info("Conectando al FortiGate: %s", fortigate_host)
    try:
        client = FortiGateClient(
            host=fortigate_host,
            token=fortigate_token,
            verify_ssl=verify_ssl,
        )
        fortigate_data = client.collect_all()
    except Exception as e:
        logger.critical("Error crítico recolectando datos del FortiGate: %s", str(e))
        return {"statusCode": 500, "error": "fortigate_collection_error", "detail": str(e)}

    # Validamos que al menos algunos endpoints respondieron.
    # Si todos son None, probablemente el FortiGate no es alcanzable
    # y no tiene sentido gastar tokens de Claude en datos vacíos.
    populated_endpoints = sum(1 for v in fortigate_data.values() if v is not None)
    if populated_endpoints == 0:
        logger.critical(
            "Ningún endpoint del FortiGate respondió. "
            "Verificar conectividad de red, token de API y Security Groups."
        )
        return {
            "statusCode": 503,
            "error": "fortigate_unreachable",
            "detail": f"0/{len(fortigate_data)} endpoints con datos — host: {fortigate_host}",
        }

    logger.info("%d/%d endpoints con datos", populated_endpoints, len(fortigate_data))

    # ── 4. Analizar con Claude ────────────────────────────────────────────────
    logger.info("Enviando datos a Claude para análisis NIST CSF 2.0")
    analysis = analyze(
        fortigate_data=fortigate_data,
        device_info=device_info,
        claude_api_key=claude_api_key,
    )

    analysis_ok = "error" not in analysis
    if not analysis_ok:
        logger.error("El análisis de Claude devolvió un error: %s", analysis.get("error"))
        # No abortamos — generamos igualmente un reporte de error y lo subimos a S3
        # para que haya registro del fallo. El equipo puede investigar en CloudWatch.

    # ── 5. Generar reporte ────────────────────────────────────────────────────
    logger.info("Generando reporte Markdown")
    markdown_report = build_markdown_report(
        analysis=analysis,
        device_info=device_info,
        timestamp=run_ts,
    )

    # ── 6. Subir a S3 ─────────────────────────────────────────────────────────
    s3_prefix = generate_s3_key_prefix(host=fortigate_host, timestamp=run_ts)
    logger.info("Subiendo reporte a S3 — prefijo: %s", s3_prefix)

    uploaded_keys = upload_to_s3(
        bucket=s3_bucket,
        s3_key_prefix=s3_prefix,
        markdown_report=markdown_report,
        analysis=analysis,
        timestamp=run_ts,
    )

    if not uploaded_keys:
        # Seguimos aunque S3 falle — al menos intentamos notificar por SNS
        logger.error("No se pudo subir ningún archivo a S3")

    # ── 7. Publicar en SNS ────────────────────────────────────────────────────
    overall_score = analysis.get("overall_score", 0.0) if analysis_ok else 0.0
    emoji = "🚨" if overall_score < 2.5 else ("🟡" if overall_score < 3.5 else "🟢")
    subject = (
        f"{emoji} PPS Assessment [{environment}] — "
        f"{fortigate_host} — Score: {overall_score:.1f}/5.0"
        if analysis_ok
        else f"⚠️ PPS Assessment FALLIDO [{environment}] — {fortigate_host}"
    )

    sns_message = build_sns_message(
        analysis=analysis,
        device_info=device_info,
        timestamp=run_ts,
        s3_key=uploaded_keys.get("markdown", s3_prefix),
    )

    logger.info("Publicando notificación en SNS")
    sns_ok = publish_to_sns(
        topic_arn=sns_topic_arn,
        message=sns_message,
        subject=subject,
    )

    # ── 8. Resultado final ────────────────────────────────────────────────────
    result = {
        "statusCode": 200 if (analysis_ok and sns_ok) else 207,
        # 207 Multi-Status: el assessment corrió pero algo falló parcialmente
        "run_ts": run_ts,
        "fortigate_host": fortigate_host,
        "endpoints_collected": populated_endpoints,
        "analysis_ok": analysis_ok,
        "overall_score": overall_score if analysis_ok else None,
        "s3_keys": uploaded_keys,
        "sns_published": sns_ok,
    }

    logger.info(
        "=== PPS Assessment completado — score: %s/5.0 | S3: %s | SNS: %s ===",
        f"{overall_score:.1f}" if analysis_ok else "N/A",
        "ok" if uploaded_keys else "error",
        "ok" if sns_ok else "error",
    )

    return result
