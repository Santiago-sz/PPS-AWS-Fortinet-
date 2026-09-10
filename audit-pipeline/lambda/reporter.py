"""
Reporter: formatea el análisis NIST CSF, lo sube a S3 y publica en SNS.

Responsabilidades de este módulo:
  1. Convertir el dict de análisis en un reporte Markdown legible por humanos
  2. Subir ese reporte + el JSON crudo a S3 (historial permanente)
  3. Publicar un resumen ejecutivo en SNS (llega por email/Slack/etc.)

Separar el "qué analizar" (analyzer.py) del "cómo reportar" (este archivo)
permite cambiar el formato de salida sin tocar la lógica de análisis.
"""

import json
import logging
import re
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Emojis de scoring para hacer el reporte más legible en el email.
# Mapea rangos de score (float) a un indicador visual.
SCORE_EMOJI = {
    (4.5, 5.0): "🟢",  # Excelente
    (3.5, 4.5): "🟡",  # Bien, con margen de mejora
    (2.5, 3.5): "🟠",  # Implementado pero requiere trabajo
    (1.0, 2.5): "🔴",  # Crítico
}

# Descripción de cada función NIST CSF 2.0 para incluir en el reporte.
# Le da contexto al lector que no conoce el framework.
NIST_DESCRIPTIONS = {
    "GOVERN": "Establece y monitorea la estrategia, expectativas y políticas de ciberseguridad",
    "IDENTIFY": "Comprensión del contexto organizacional y los activos que requieren protección",
    "PROTECT": "Salvaguardas para limitar el impacto de incidentes de ciberseguridad",
    "DETECT": "Identificación oportuna de eventos de ciberseguridad",
    "RESPOND": "Acciones ante un incidente de ciberseguridad detectado",
    "RECOVER": "Restauración de capacidades y servicios afectados por un incidente",
}


def _score_to_emoji(score: float) -> str:
    """Devuelve el emoji correspondiente al score numérico."""
    for (low, high), emoji in SCORE_EMOJI.items():
        if low <= score <= high:
            return emoji
    return "⚪"


def _score_to_label(score: float) -> str:
    """Convierte el score numérico en una etiqueta textual."""
    if score >= 4.5:
        return "Excelente"
    elif score >= 3.5:
        return "Bueno"
    elif score >= 2.5:
        return "Regular"
    elif score >= 1.5:
        return "Deficiente"
    else:
        return "Crítico"


def _format_list(items: list, indent: str = "  ") -> str:
    """
    Formatea una lista Python como lista Markdown.
    Si la lista está vacía o es None, devuelve un mensaje placeholder
    para que el reporte nunca quede con secciones en blanco.
    """
    if not items:
        return f"{indent}- Sin datos disponibles\n"
    return "".join(f"{indent}- {item}\n" for item in items)


def build_markdown_report(analysis: dict, device_info: dict, timestamp: str) -> str:
    """
    Genera el reporte completo en formato Markdown.

    Markdown fue elegido sobre HTML o PDF porque:
    - Es legible directamente en S3 (con viewer) y en GitHub
    - Se puede convertir a PDF o HTML con pandoc si se necesita
    - No requiere dependencias adicionales en Lambda

    Args:
        analysis:    dict devuelto por analyzer.analyze()
        device_info: dict con host, region, environment del FortiGate
        timestamp:   ISO 8601 string del momento de evaluación

    Returns:
        String con el reporte completo en Markdown.
    """
    # Si el análisis contiene un error, generamos un reporte de error
    # en lugar de fallar con una KeyError silenciosa.
    if "error" in analysis:
        return (
            f"# ⚠️ Error en el Análisis PPS\n\n"
            f"**Timestamp:** {timestamp}\n"
            f"**Dispositivo:** {device_info.get('host', 'desconocido')}\n\n"
            f"**Error:** `{analysis.get('error')}`\n\n"
            f"**Detalle:** {analysis.get('detail', analysis.get('raw', 'Sin detalle'))}\n"
        )

    host = device_info.get("host", "desconocido")
    environment = device_info.get("environment", "production")
    region = device_info.get("region", "desconocida")
    overall = analysis.get("overall_score", 0.0)
    emoji = _score_to_emoji(overall)
    label = _score_to_label(overall)
    functions = analysis.get("functions", {})

    lines = []

    # ─── Encabezado ───────────────────────────────────────────────────────────
    lines.append(f"# {emoji} Reporte de Postura de Seguridad — NIST CSF 2.0\n")
    lines.append("| Campo         | Valor                          |")
    lines.append("|---------------|--------------------------------|")
    lines.append(f"| **Dispositivo**  | `{host}`                    |")
    lines.append(f"| **Ambiente**     | `{environment}`             |")
    lines.append(f"| **Región AWS**   | `{region}`                  |")
    lines.append(f"| **Evaluado**     | {timestamp}                 |")
    lines.append(f"| **Score Global** | {emoji} **{overall:.1f}/5.0** — {label} |")
    lines.append("")

    # ─── Resumen ejecutivo ────────────────────────────────────────────────────
    lines.append("## 📋 Resumen Ejecutivo\n")
    lines.append(analysis.get("executive_summary", "Sin resumen disponible."))
    lines.append("")

    # ─── Problemas críticos ───────────────────────────────────────────────────
    critical = analysis.get("critical_issues", [])
    if critical:
        lines.append("## 🚨 Problemas Críticos\n")
        lines.append("> Requieren atención inmediata.\n")
        lines.append(_format_list(critical))

    # ─── Quick wins ───────────────────────────────────────────────────────────
    quick_wins = analysis.get("quick_wins", [])
    if quick_wins:
        lines.append("## ⚡ Quick Wins\n")
        lines.append("> Mejoras de bajo esfuerzo y alto impacto.\n")
        lines.append(_format_list(quick_wins))

    # ─── Resumen de scores por función ────────────────────────────────────────
    lines.append("## 📊 Scores por Función NIST CSF 2.0\n")
    lines.append("| Función   | Score | Estado   | Descripción |")
    lines.append("|-----------|-------|----------|-------------|")

    for fn_name, fn_data in functions.items():
        fn_score = fn_data.get("score", 0.0) if isinstance(fn_data, dict) else 0.0
        fn_emoji = _score_to_emoji(fn_score)
        fn_label = _score_to_label(fn_score)
        fn_desc = NIST_DESCRIPTIONS.get(fn_name, "")
        lines.append(f"| **{fn_name}** | {fn_emoji} {fn_score:.1f} | {fn_label} | {fn_desc} |")

    lines.append("")

    # ─── Detalle por función ──────────────────────────────────────────────────
    lines.append("## 🔍 Análisis Detallado por Función\n")

    for fn_name, fn_data in functions.items():
        if not isinstance(fn_data, dict):
            continue

        fn_score = fn_data.get("score", 0.0)
        fn_emoji = _score_to_emoji(fn_score)
        findings = fn_data.get("findings", [])
        recommendations = fn_data.get("recommendations", [])

        lines.append(f"### {fn_emoji} {fn_name} — {fn_score:.1f}/5.0\n")
        lines.append(f"_{NIST_DESCRIPTIONS.get(fn_name, '')}_\n")

        lines.append("**Hallazgos:**\n")
        lines.append(_format_list(findings))

        lines.append("**Recomendaciones:**\n")
        lines.append(_format_list(recommendations))

    # ─── Footer ───────────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("_Reporte generado automáticamente por PPS (Posture Assessment System)_")
    lines.append("_Modelo de análisis: Claude — Framework: NIST CSF 2.0_")

    return "\n".join(lines)


def build_sns_message(analysis: dict, device_info: dict, timestamp: str, s3_key: str) -> str:
    """
    Genera el mensaje corto para SNS (email/Slack).

    SNS tiene un límite de 256KB por mensaje, pero los emails son más
    efectivos cuando son concisos. Este mensaje incluye solo el score
    global, los críticos y un link al reporte completo en S3.
    """
    if "error" in analysis:
        host = device_info.get("host", "desconocido")
        return (
            f"⚠️ ERROR en PPS Assessment\n"
            f"Dispositivo: {host}\n"
            f"Timestamp: {timestamp}\n"
            f"Error: {analysis.get('error')}\n"
            f"Detalle: {analysis.get('detail', 'ver logs de CloudWatch')}"
        )

    host = device_info.get("host", "desconocido")
    env = device_info.get("environment", "production")
    overall = analysis.get("overall_score", 0.0)
    emoji = _score_to_emoji(overall)
    label = _score_to_label(overall)
    critical = analysis.get("critical_issues", [])
    functions = analysis.get("functions", {})

    lines = [
        f"{emoji} PPS Security Assessment — {host} ({env})",
        f"Fecha: {timestamp}",
        f"Score Global: {overall:.1f}/5.0 — {label}",
        "",
        "Scores por función:",
    ]

    for fn_name, fn_data in functions.items():
        if isinstance(fn_data, dict):
            fn_score = fn_data.get("score", 0.0)
            fn_emoji = _score_to_emoji(fn_score)
            lines.append(f"  {fn_emoji} {fn_name}: {fn_score:.1f}/5.0")

    if critical:
        lines.append("")
        lines.append(f"🚨 Problemas críticos ({len(critical)}):")
        # Mostramos solo los primeros 3 críticos para no hacer el email enorme
        for issue in critical[:3]:
            lines.append(f"  • {issue}")
        if len(critical) > 3:
            lines.append(f"  • ... y {len(critical) - 3} más (ver reporte completo)")

    lines.append("")
    lines.append(f"📄 Reporte completo en S3: {s3_key}")

    return "\n".join(lines)


def upload_to_s3(
    bucket: str,
    s3_key_prefix: str,
    markdown_report: str,
    analysis: dict,
    timestamp: str,
) -> dict:
    """
    Sube dos archivos a S3:
      - {prefix}/report.md    → reporte Markdown legible
      - {prefix}/analysis.json → JSON crudo del análisis (útil para integraciones)

    Subir ambos formatos permite que:
    - Humanos lean el Markdown directamente en S3
    - Otras herramientas (SIEM, dashboards) consuman el JSON estructurado

    Args:
        bucket:          Nombre del bucket S3 (de la variable de entorno)
        s3_key_prefix:   Prefijo del path en S3. Ej: "reports/192.168.1.1/2025-01-15T10:30:00"
        markdown_report: String con el reporte Markdown
        analysis:        Dict con el análisis crudo
        timestamp:       ISO 8601 para incluir en metadata

    Returns:
        dict con las claves S3 de los archivos subidos.
    """
    s3 = boto3.client("s3")
    uploaded = {}

    # Metadata común para ambos objetos — aparece en S3 y facilita búsquedas
    common_metadata = {
        "generated-by": "pps-lambda",
        "framework": "nist-csf-2.0",
        "assessment-ts": timestamp,
    }

    # ── Reporte Markdown ──────────────────────────────────────────────────────
    md_key = f"{s3_key_prefix}/report.md"
    try:
        s3.put_object(
            Bucket=bucket,
            Key=md_key,
            Body=markdown_report.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
            # ServerSideEncryption: S3 lo aplica automáticamente por el bucket policy
            # que configuramos en storage.tf (BucketEncryption AES256)
            Metadata=common_metadata,
        )
        uploaded["markdown"] = md_key
        logger.info("Reporte Markdown subido: s3://%s/%s", bucket, md_key)
    except ClientError as e:
        # Logueamos pero no abortamos — intentamos subir el JSON de todas formas
        logger.error("Error subiendo Markdown a S3: %s", e.response["Error"]["Message"])

    # ── JSON crudo ────────────────────────────────────────────────────────────
    json_key = f"{s3_key_prefix}/analysis.json"
    try:
        s3.put_object(
            Bucket=bucket,
            Key=json_key,
            Body=json.dumps(analysis, indent=2, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            Metadata=common_metadata,
        )
        uploaded["json"] = json_key
        logger.info("JSON crudo subido: s3://%s/%s", bucket, json_key)
    except ClientError as e:
        logger.error("Error subiendo JSON a S3: %s", e.response["Error"]["Message"])

    return uploaded


def publish_to_sns(topic_arn: str, message: str, subject: str) -> bool:
    """
    Publica el resumen en el topic SNS.

    SNS distribuye el mensaje a todos los suscriptores configurados
    (email, Slack via Lambda, PagerDuty, etc.) sin que este código
    necesite saber quién está suscripto — eso se configura en AWS.

    Args:
        topic_arn: ARN del topic SNS (de la variable de entorno)
        message:   Cuerpo del mensaje
        subject:   Asunto del email (ignorado por suscriptores no-email)

    Returns:
        True si la publicación fue exitosa, False si falló.
    """
    sns = boto3.client("sns")

    try:
        response = sns.publish(
            TopicArn=topic_arn,
            Message=message,
            Subject=subject,
            # MessageAttributes permite filtrar mensajes en suscripciones con FilterPolicy
            # Por ejemplo: solo mandar al PagerDuty cuando severity="critical"
            MessageAttributes={
                "severity": {
                    "DataType": "String",
                    "StringValue": "critical" if "🚨" in message else "info",
                }
            },
        )
        logger.info("SNS publicado — MessageId: %s", response.get("MessageId"))
        return True

    except ClientError as e:
        logger.error("Error publicando en SNS: %s", e.response["Error"]["Message"])
        return False


def generate_s3_key_prefix(host: str, timestamp: str) -> str:
    """
    Genera el prefijo de path en S3 para este assessment.

    Estructura: reports/{host}/{fecha}/{hora}
    Ejemplo:    reports/192.168.1.1/2025-01-15/T103045

    Separar fecha y hora permite listar fácilmente todos los reportes
    de un día con s3.list_objects_v2(Prefix="reports/{host}/2025-01-15/")

    El host se sanitiza para eliminar caracteres inválidos en S3 keys.
    """
    # Sanitizamos el host: reemplazamos puntos y dos puntos por guiones
    # para evitar ambigüedades en paths de S3
    safe_host = re.sub(r"[^a-zA-Z0-9\-_]", "-", host)

    # Parseamos el timestamp ISO 8601 para construir el path
    # datetime.fromisoformat maneja tanto "2025-01-15T10:30:45Z" como sin Z
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("T%H%M%S")
    except ValueError:
        # Fallback si el timestamp tiene formato inesperado
        date_str = timestamp[:10]
        time_str = "T" + timestamp[11:19].replace(":", "")

    return f"reports/{safe_host}/{date_str}/{time_str}"
