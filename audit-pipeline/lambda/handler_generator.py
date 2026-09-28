"""
Policy Generator — entrypoint disparado por evento S3 (Fase 8, tasks.md 8.1).

Orquesta el flujo completo descripto en design.md "Data Flow":

    S3 policies/ --evento--> extract -> chunk -> map/reduce (llm_client)
                                              |
                              validate falla -- feedback (<=3, DENTRO de
                              llm_client.generate_script_with_retries)
                                              |
                    S3 artifacts/{run_id}/ --async invoke--> audit_executor

Responsabilidad de este archivo: SOLO orquestación + I/O. Toda la lógica
de negocio (extracción, chunking, generación/validación/reintento) ya vive
en los módulos construidos en Fases 3-5; este handler nunca la repite.

Camino de fallo explícito (spec.md "Bounded Self-Correcting Retry" /
"No-Verifiable-Controls Handling"): reintentos agotados, política sin
controles verificables, o un documento no extraíble producen un reporte
explícito y NUNCA invocan a audit_executor — jamás se ofrece un script
parcial/no confiable para ejecución.

Nota de alcance IAM (desviación deliberada de la redacción literal de
design.md "Retry feedback" — "Exhaustion -> ... report to S3+SNS"): el rol
de policy_generator (terraform/iam.tf, tasks.md 2.2) NO tiene `sns:Publish`
ni recibe `SNS_TOPIC_ARN` como variable de entorno (terraform/lambda.tf,
`aws_lambda_function.policy_generator`) — por diseño de mínimo privilegio.
Los reportes de fallo de ESTE handler se escriben a S3 únicamente, vía
`s3_io.put_report` + `reporter.build_policy_report_*` (nunca vía
`reporter.deliver_policy_report`, que intentaría `publish_to_sns` y
fallaría con AccessDenied en un deploy real). `audit_executor` sí tiene
ambos permisos (S3 write a `reports/*` + `sns:Publish`) y es quien reporta
S3+SNS para sus propios resultados — éxito y fallo de re-validación o
ejecución (ver handler_executor.py).
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

import chunker
import extractor
import fortigate_client
import llm_client
import reporter
import s3_io

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _get_required_env(name: str) -> str:
    """Lee una variable de entorno obligatoria. Falla explícitamente si falta."""
    value = os.environ.get(name)
    if not value:
        raise OSError(
            f"Variable de entorno requerida no configurada: '{name}'. "
            f"Verificar terraform/lambda.tf -> aws_lambda_function.policy_generator"
        )
    return value


def _get_secret(secret_arn: str) -> str:
    """Lee un secret de Secrets Manager. Mismo patrón que handler.py (legacy)."""
    sm = boto3.client("secretsmanager")
    try:
        response = sm.get_secret_value(SecretId=secret_arn)
        secret = response.get("SecretString")
        if not secret:
            raise ValueError(f"El secret {secret_arn} no tiene SecretString")
        return secret
    except ClientError as e:
        logger.error(
            "No se pudo leer el secret %s — código: %s — %s",
            secret_arn,
            e.response["Error"]["Code"],
            e.response["Error"]["Message"],
        )
        raise


def _content_type_for_key(key: str) -> str:
    """Infiere el content_type de extractor.py a partir de la extensión del key.

    Defensivo: el filtro de aws_s3_bucket_notification (storage.tf) ya
    restringe la invocación a `.pdf`/`.docx`, pero este handler no confía
    ciegamente en la infraestructura — una extensión inesperada falla
    explícito acá, igual que cualquier otro ExtractionError.
    """
    lowered = key.lower()
    if lowered.endswith(".pdf"):
        return extractor.PDF_CONTENT_TYPE
    if lowered.endswith(".docx"):
        return extractor.DOCX_CONTENT_TYPE
    raise extractor.ExtractionError(
        "unsupported_content_type",
        f"No se puede inferir el tipo de contenido del objeto S3 '{key}'",
    )


def _endpoint_catalog() -> list[str]:
    return [label for _, label in fortigate_client.ENDPOINTS]


def _extract_event_object(event: dict) -> tuple[str, str]:
    """Extrae (bucket, key) del primer registro de un evento S3 ObjectCreated."""
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]
    return bucket, key


def _write_failure_report(
    *,
    reports_bucket: str,
    run_id: str,
    policy_key: str,
    timestamp: str,
    failure_reason: str,
) -> None:
    """Reporta un fallo del generador SOLO a S3 (ver nota de alcance IAM arriba).

    Nunca invoca reporter.deliver_policy_report -- ese helper también
    publica en SNS, permiso que policy_generator no tiene.
    """
    markdown = reporter.build_policy_report_markdown(
        findings=[],
        notes=[],
        status="could_not_audit",
        run_id=run_id,
        policy_key=policy_key,
        timestamp=timestamp,
        failure_reason=failure_reason,
    )
    payload = reporter.build_policy_report_json(
        findings=[],
        notes=[],
        status="could_not_audit",
        run_id=run_id,
        policy_key=policy_key,
        timestamp=timestamp,
        failure_reason=failure_reason,
    )
    s3_io.put_report(
        reports_bucket,
        f"reports/{run_id}/report.md",
        markdown,
        content_type="text/markdown; charset=utf-8",
    )
    s3_io.put_report(
        reports_bucket,
        f"reports/{run_id}/report.json",
        json.dumps(payload, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
    )


def lambda_handler(event: dict, context) -> dict:
    """Entry point de AWS Lambda para `policy_generator`.

    AWS invoca esta función cuando un `.pdf`/`.docx` se sube a
    `policies/` en el bucket `policies` (ver terraform/storage.tf).
    """
    run_ts = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    run_id = uuid.uuid4().hex
    logger.info("=== Policy Generator iniciado — run_id=%s ts=%s ===", run_id, run_ts)

    claude_secret_arn = _get_required_env("CLAUDE_SECRET_ARN")
    reports_bucket = _get_required_env("S3_BUCKET")
    executor_function_name = _get_required_env("EXECUTOR_FUNCTION_NAME")
    max_attempts = int(
        os.environ.get("MAX_GENERATION_ATTEMPTS", llm_client.MAX_GENERATION_ATTEMPTS)
    )

    policies_bucket, policy_key = _extract_event_object(event)
    logger.info("Política subida: s3://%s/%s", policies_bucket, policy_key)

    policy_bytes = s3_io.get_policy(policies_bucket, policy_key)
    policy_sha256 = hashlib.sha256(policy_bytes).hexdigest()

    # ── 1. Extracción ────────────────────────────────────────────────────────
    try:
        content_type = _content_type_for_key(policy_key)
        text, metadata = extractor.extract(policy_bytes, content_type)
    except extractor.ExtractionError as e:
        failure_reason = f"extraction_error:{e.reason}"
        logger.error("Extracción falló — run_id=%s %s", run_id, failure_reason)
        _write_failure_report(
            reports_bucket=reports_bucket,
            run_id=run_id,
            policy_key=policy_key,
            timestamp=run_ts,
            failure_reason=failure_reason,
        )
        return {"status": "could_not_audit", "run_id": run_id, "failure_reason": failure_reason}

    # ── 2. Chunking ──────────────────────────────────────────────────────────
    chunks = chunker.chunk(text, metadata)
    claude_api_key = _get_secret(claude_secret_arn)
    endpoint_catalog = _endpoint_catalog()

    # ── 3. Map/reduce + retry (llm_client) ──────────────────────────────────
    try:
        result = llm_client.generate_audit_script(
            chunks, endpoint_catalog, claude_api_key, max_attempts=max_attempts
        )
    except (
        llm_client.MapCallBudgetExceededError,
        llm_client.ClaudeCallError,
        llm_client.MapResponseParseError,
    ) as e:
        failure_reason = f"{type(e).__name__}:{e}"
        logger.error("Generación falló — run_id=%s %s", run_id, failure_reason)
        _write_failure_report(
            reports_bucket=reports_bucket,
            run_id=run_id,
            policy_key=policy_key,
            timestamp=run_ts,
            failure_reason=failure_reason,
        )
        return {"status": "could_not_audit", "run_id": run_id, "failure_reason": failure_reason}

    if result["status"] == "no_verifiable_controls":
        logger.warning("Política sin controles verificables — run_id=%s", run_id)
        _write_failure_report(
            reports_bucket=reports_bucket,
            run_id=run_id,
            policy_key=policy_key,
            timestamp=run_ts,
            failure_reason="no_verifiable_controls",
        )
        return {"status": "no_verifiable_controls", "run_id": run_id}

    if result["status"] == "generation_failed":
        logger.error(
            "Reintentos de generación agotados — run_id=%s attempts=%s",
            run_id,
            result["attempts"],
        )
        _write_failure_report(
            reports_bucket=reports_bucket,
            run_id=run_id,
            policy_key=policy_key,
            timestamp=run_ts,
            failure_reason="generation_failed",
        )
        return {
            "status": "generation_failed",
            "run_id": run_id,
            "attempts": result["attempts"],
        }

    # ── 4. status == "ok" -> escribir artifacts + invocar executor ─────────
    script = result["script"]
    checks = result["checks"]
    attempts = result["attempts"]

    script_key = f"artifacts/{run_id}/script.py"
    manifest_key = f"artifacts/{run_id}/manifest.json"

    script_sha256 = s3_io.put_script(reports_bucket, script_key, script)
    manifest = s3_io.build_manifest(
        run_id=run_id,
        policy_key=policy_key,
        policy_sha256=policy_sha256,
        script_key=script_key,
        script_sha256=script_sha256,
        checks=checks,
        attempts=attempts,
        model=llm_client.CLAUDE_MODEL,
        generated_at=run_ts,
    )
    s3_io.put_manifest(reports_bucket, manifest_key, manifest)

    lambda_client = boto3.client("lambda")
    invoke_payload = {
        "run_id": run_id,
        "manifest_key": manifest_key,
        "script_key": script_key,
        "script_sha256": script_sha256,
    }
    lambda_client.invoke(
        FunctionName=executor_function_name,
        InvocationType="Event",
        Payload=json.dumps(invoke_payload).encode("utf-8"),
    )

    logger.info(
        "=== Policy Generator completado — run_id=%s attempts=%d invocando executor ===",
        run_id,
        attempts,
    )
    return {
        "status": "invoked",
        "run_id": run_id,
        "manifest_key": manifest_key,
        "script_key": script_key,
        "script_sha256": script_sha256,
        "attempts": attempts,
    }
