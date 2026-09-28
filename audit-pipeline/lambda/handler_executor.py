"""
Audit Executor — entrypoint invocado de forma asíncrona (Fase 8, tasks.md 8.3).

Invocado por `policy_generator` (`lambda:InvokeFunction`,
`InvocationType=Event`) con el puntero
`{run_id, manifest_key, script_key, script_sha256}` (design.md Decision #2).

DEFENSA EN PROFUNDIDAD (contexto crítico de seguridad, no negociable): este
módulo NUNCA confía en que `policy_generator` ya validó el script. Repite
TODO desde cero, en el orden exacto que pide design.md ("Gate order":
"Executor repeats all three against script_sha256"):

  1. **Integridad**: recalcula `sha256(script)` sobre los bytes leídos de
     S3 y lo compara contra `manifest["script_sha256"]` (Fase 6) — ANTES
     de siquiera intentar `ast.parse()`. Un script mutado en S3 entre que
     el generador lo escribió y este handler lo lee se rechaza acá, sin
     llegar a tocar el AST. También se cruza contra el `script_sha256`
     recibido en el payload de invocación, por si el puntero mismo fue
     alterado en tránsito.
  2. **Re-validación independiente**: `script_validator.validate()` se
     corre de nuevo acá, desde cero — nunca se reutiliza ni se confía en
     un resultado que ya calculó (y descartó) `policy_generator`.
  3. Solo si ambos gates pasan: `sandbox.execute()`.

Cualquier rechazo en (1) o (2) escribe un reporte explícito de fallo
(S3+SNS, vía `reporter.deliver_policy_report`) y el script JAMÁS se
ejecuta.
"""

import hashlib
import logging
import os
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

import reporter
import s3_io
import sandbox
import script_validator
from fortigate_client import FortiGateClient

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
            f"Verificar terraform/lambda.tf -> aws_lambda_function.audit_executor"
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


def _report_failure(
    *,
    reports_bucket: str,
    topic_arn: str,
    run_id: str,
    policy_key: str,
    timestamp: str,
    failure_reason: str,
) -> dict:
    """Reporta un fallo del executor a S3+SNS (el executor SÍ tiene ambos
    permisos — a diferencia de policy_generator, ver handler_generator.py)."""
    return reporter.deliver_policy_report(
        bucket=reports_bucket,
        topic_arn=topic_arn,
        run_id=run_id,
        policy_key=policy_key,
        findings=[],
        notes=[],
        status="could_not_audit",
        timestamp=timestamp,
        failure_reason=failure_reason,
    )


def lambda_handler(event: dict, context) -> dict:
    """Entry point de AWS Lambda para `audit_executor`.

    `event` es el puntero exacto que envía policy_generator:
    `{run_id, manifest_key, script_key, script_sha256}`.
    """
    run_ts = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    run_id = event["run_id"]
    manifest_key = event["manifest_key"]
    script_key = event["script_key"]
    payload_script_sha256 = event["script_sha256"]

    logger.info("=== Audit Executor iniciado — run_id=%s ===", run_id)

    fortigate_host = _get_required_env("FORTIGATE_HOST")
    fortigate_secret_arn = _get_required_env("FORTIGATE_SECRET_ARN")
    reports_bucket = _get_required_env("S3_BUCKET")
    sns_topic_arn = _get_required_env("SNS_TOPIC_ARN")
    verify_ssl = os.environ.get("FORTIGATE_VERIFY_SSL", "true").lower() == "true"
    max_wall_clock_s = float(
        os.environ.get("SANDBOX_WALL_CLOCK_SECONDS", sandbox.DEFAULT_BUDGET.max_wall_clock_s)
    )
    max_fgt_calls = int(
        os.environ.get("SANDBOX_MAX_FGT_CALLS", sandbox.DEFAULT_BUDGET.max_fgt_calls)
    )
    budget = sandbox.SandboxBudget(max_wall_clock_s=max_wall_clock_s, max_fgt_calls=max_fgt_calls)

    manifest = s3_io.get_manifest(reports_bucket, manifest_key)
    script = s3_io.get_script(reports_bucket, script_key)
    policy_key = manifest.get("policy_key", "desconocida")

    # ── 1. Integridad — ANTES de tocar el AST ───────────────────────────────
    actual_sha256 = hashlib.sha256(script.encode("utf-8")).hexdigest()
    manifest_sha256 = manifest.get("script_sha256")
    if actual_sha256 != manifest_sha256 or actual_sha256 != payload_script_sha256:
        logger.critical(
            "Integridad de script violada — run_id=%s manifest=%s payload=%s actual=%s",
            run_id,
            manifest_sha256,
            payload_script_sha256,
            actual_sha256,
        )
        delivery = _report_failure(
            reports_bucket=reports_bucket,
            topic_arn=sns_topic_arn,
            run_id=run_id,
            policy_key=policy_key,
            timestamp=run_ts,
            failure_reason="integrity_check_failed",
        )
        return {
            "status": "could_not_audit",
            "run_id": run_id,
            "failure_reason": "integrity_check_failed",
            **delivery,
        }

    # ── 2. Re-validación INDEPENDIENTE — desde cero, nunca cacheada ─────────
    validation = script_validator.validate(script, manifest)
    if not validation.valid:
        first_error = validation.errors[0]
        failure_reason = f"revalidation_failed:{first_error.rule_id}"
        logger.error("Re-validación falló — run_id=%s %s", run_id, failure_reason)
        delivery = _report_failure(
            reports_bucket=reports_bucket,
            topic_arn=sns_topic_arn,
            run_id=run_id,
            policy_key=policy_key,
            timestamp=run_ts,
            failure_reason=failure_reason,
        )
        return {
            "status": "could_not_audit",
            "run_id": run_id,
            "failure_reason": failure_reason,
            **delivery,
        }

    # ── 3. Ejecución bajo sandbox ────────────────────────────────────────────
    fortigate_token = _get_secret(fortigate_secret_arn)
    fgt_client = FortiGateClient(host=fortigate_host, token=fortigate_token, verify_ssl=verify_ssl)

    try:
        sandbox_result = sandbox.execute(script, manifest, fgt_client, budget=budget)
        findings, notes = sandbox_result.findings, sandbox_result.notes
    except sandbox.SandboxBudgetExceeded as e:
        # Findings/notes parciales SIEMPRE se preservan y se reportan (spec.md
        # "Script exceeds wall-clock cutoff": "partial findings collected so
        # far MUST be preserved and reported") — pero un corte de presupuesto
        # NO es una auditoría completa. Reportarlo como "completed" le daría
        # al consumidor del reporte una falsa sensación de auditoría íntegra
        # (mismo valor que una corrida que sí terminó de revisar todo). Por
        # eso usa el status distinto "truncated": ni "completed" (no fue
        # completa) ni "could_not_audit" (sí se recolectó evidencia parcial
        # utilizable). La razón de terminación queda registrada como nota Y
        # como failure_reason de primer nivel.
        logger.warning("Sandbox terminado por presupuesto — run_id=%s reason=%s", run_id, e.reason)
        findings = e.findings
        notes = [
            *e.notes,
            {
                "check_id": "_sandbox",
                "message": f"execution terminated early: {e.reason} — {e}",
            },
        ]
        delivery = reporter.deliver_policy_report(
            bucket=reports_bucket,
            topic_arn=sns_topic_arn,
            run_id=run_id,
            policy_key=policy_key,
            findings=findings,
            notes=notes,
            status="truncated",
            timestamp=run_ts,
            failure_reason=e.reason,
        )
        return {
            "status": "truncated",
            "run_id": run_id,
            "budget_exceeded": e.reason,
            "findings_count": len(findings),
            **delivery,
        }
    except Exception as e:
        # Cualquier otra excepción (ej. AttributeError de una capability
        # inexistente, NameError de un builtin no inyectado) NUNCA debe
        # crashear sin dejar reporte — se reporta como fallo explícito.
        logger.exception("Error inesperado ejecutando el script — run_id=%s", run_id)
        failure_reason = f"execution_error:{type(e).__name__}:{e}"
        delivery = _report_failure(
            reports_bucket=reports_bucket,
            topic_arn=sns_topic_arn,
            run_id=run_id,
            policy_key=policy_key,
            timestamp=run_ts,
            failure_reason=failure_reason,
        )
        return {
            "status": "could_not_audit",
            "run_id": run_id,
            "failure_reason": failure_reason,
            **delivery,
        }

    delivery = reporter.deliver_policy_report(
        bucket=reports_bucket,
        topic_arn=sns_topic_arn,
        run_id=run_id,
        policy_key=policy_key,
        findings=findings,
        notes=notes,
        status="completed",
        timestamp=run_ts,
        failure_reason=None,
    )
    logger.info("=== Audit Executor completado — run_id=%s findings=%d ===", run_id, len(findings))
    return {
        "status": "completed",
        "run_id": run_id,
        "findings_count": len(findings),
        **delivery,
    }
