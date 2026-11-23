"""
Policy Generator — entrypoint disparado por evento S3 (Fase 8, tasks.md 8.1).

Orquesta el flujo completo descripto en design.md "Data Flow":

    S3 policies/ --evento--> extract -> chunk -> map/reduce (llm_client/Bedrock)
                                              |
                              validate falla -- feedback (<=3, DENTRO de
                              llm_client.generate_script_with_retries)
                                              |
                    S3 artifacts/{run_id}/ --async invoke--> audit_executor
                                              (solo si AUTO_EXECUTE=true)

Responsabilidad de este archivo: SOLO orquestación + I/O. Toda la lógica
de negocio (extracción, chunking, generación/validación/reintento) ya vive
en los módulos construidos en Fases 3-5; este handler nunca la repite.

Camino de fallo explícito (spec.md "Bounded Self-Correcting Retry" /
"No-Verifiable-Controls Handling"): reintentos agotados, política sin
controles verificables, o un documento no extraíble producen un reporte
explícito y NUNCA invocan a audit_executor — jamás se ofrece un script
parcial/no confiable para ejecución.

Compuerta humana mínima (`AUTO_EXECUTE`): con `AUTO_EXECUTE=false` el
handler escribe igual script + manifest (firmados con `script_sha256`) pero
NO invoca al executor; devuelve `status="awaiting_approval"` con el puntero
completo para que un operador lo invoque manualmente tras revisarlo.

Nota de alcance IAM (desviación deliberada de la redacción literal de
design.md "Retry feedback" — "Exhaustion -> ... report to S3+SNS"): el rol
de policy_generator (infrastructure/pipeline/iam.tf, tasks.md 2.2) NO tiene
`sns:Publish` ni recibe `SNS_TOPIC_ARN` como variable de entorno
(infrastructure/pipeline/lambda.tf, `aws_lambda_function.policy_generator`)
— por diseño de mínimo privilegio.
Los reportes de fallo de ESTE handler se escriben a S3 únicamente, vía
`s3_io.put_report` + `reporter.build_policy_report_*` (nunca vía
`reporter.deliver_policy_report`, que intentaría `publish_to_sns` y
fallaría con AccessDenied en un deploy real). `audit_executor` sí tiene
ambos permisos (S3 write a `reports/*` + `sns:Publish`) y es quien reporta
S3+SNS para sus propios resultados — éxito y fallo de re-validación o
ejecución (ver handler_executor.py).

El modelo se alcanza vía Amazon Bedrock con la identidad IAM del rol; no
existe ninguna API key que leer de Secrets Manager en este handler.

Documentación de referencia (opcional, apagada por defecto): si
`KNOWLEDGE_BASE_ID` tiene valor, entre map y reduce se consulta la Knowledge
Base una vez por control (`reference_context.collect`) y el resultado se
registra en el bloque `knowledge_base` del manifest. Con la variable vacía o
ausente no se lee ninguna otra variable de la Knowledge Base y la llamada a
`llm_client`, los prompts y el manifest son idénticos a los anteriores.
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from urllib.parse import unquote_plus

import boto3

import chunker
import extractor
import fortigate_client
import knowledge_retriever
import llm_client
import observability
import reference_context
import reporter
import s3_io

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "y", "on"}


def _get_required_env(name: str) -> str:
    """Lee una variable de entorno obligatoria. Falla explícitamente si falta."""
    value = os.environ.get(name)
    if not value:
        raise OSError(
            f"Variable de entorno requerida no configurada: '{name}'. "
            f"Verificar terraform/lambda.tf -> aws_lambda_function.policy_generator"
        )
    return value


def _auto_execute_enabled() -> bool:
    """`AUTO_EXECUTE` (default true): true/1/yes habilitan la invocación
    automática del executor; cualquier otro valor la desactiva."""
    return os.environ.get("AUTO_EXECUTE", "true").strip().lower() in _TRUTHY


def _retrieval_config() -> knowledge_retriever.RetrievalConfig | None:
    """Configuración de la Knowledge Base, o None si está deshabilitada.

    Con `KNOWLEDGE_BASE_ID` vacío o ausente no se interpreta ninguna otra
    variable de la Knowledge Base: el camino deshabilitado no puede fallar ni
    cambiar por ellas. Con el id presente, un valor inválido de
    `KNOWLEDGE_BASE_MAX_RESULTS` levanta `ValueError` (configuración
    explícitamente incorrecta, igual que una variable requerida ausente).
    """
    if not os.environ.get(knowledge_retriever.KNOWLEDGE_BASE_ID_ENV, "").strip():
        return None
    return knowledge_retriever.load_config()


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
    key = unquote_plus(record["s3"]["object"]["key"])
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


def _log_result(
    run_id: str, status: str, *, checks_count: int = 0, map_calls: int = 0, **extra
) -> None:
    """Evento terminal `generator_result` -- uno por invocación, siempre."""
    observability.log_event(
        "generator_result",
        run_id=run_id,
        status=status,
        checks_count=checks_count,
        map_calls=map_calls,
        **extra,
    )


def lambda_handler(event: dict, context) -> dict:
    """Entry point de AWS Lambda para `policy_generator`.

    AWS invoca esta función cuando un `.pdf`/`.docx` se sube a
    `policies/` en el bucket `policies` (ver terraform/storage.tf).
    """
    run_ts = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    run_id = uuid.uuid4().hex
    logger.info("=== Policy Generator iniciado — run_id=%s ts=%s ===", run_id, run_ts)

    reports_bucket = _get_required_env("S3_BUCKET")
    executor_function_name = _get_required_env("EXECUTOR_FUNCTION_NAME")
    max_attempts = int(
        os.environ.get("MAX_GENERATION_ATTEMPTS", llm_client.MAX_GENERATION_ATTEMPTS)
    )
    auto_execute = _auto_execute_enabled()
    retrieval_config = _retrieval_config()

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
        _log_result(run_id, "could_not_audit", failure_reason=failure_reason)
        return {"status": "could_not_audit", "run_id": run_id, "failure_reason": failure_reason}

    # ── 2. Chunking ──────────────────────────────────────────────────────────
    chunks = chunker.chunk(text, metadata)
    endpoint_catalog = _endpoint_catalog()
    # Cantidad de llamadas de map que requiere esta política (agrupación
    # pura, sin I/O) -- solo para observabilidad.
    map_calls = len(llm_client.group_chunks_for_map(chunks))

    # ── 3. Map/reduce + retry (llm_client sobre Bedrock) ────────────────────
    generation_options: dict = {"max_attempts": max_attempts}
    if retrieval_config is not None:
        # Knowledge Base habilitada: una consulta por control, después de map
        # y antes de reduce. Un fallo de recuperación no interrumpe la
        # generación (ver reference_context).
        def reference_provider(checks: list[dict]) -> reference_context.ReferenceContext:
            return reference_context.collect(checks, retrieval_config)

        generation_options["reference_provider"] = reference_provider
    try:
        result = llm_client.generate_audit_script(chunks, endpoint_catalog, **generation_options)
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
        _log_result(run_id, "could_not_audit", map_calls=map_calls, failure_reason=failure_reason)
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
        _log_result(run_id, "no_verifiable_controls", map_calls=map_calls)
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
        _log_result(
            run_id,
            "generation_failed",
            map_calls=map_calls,
            attempts=result["attempts"],
        )
        return {
            "status": "generation_failed",
            "run_id": run_id,
            "attempts": result["attempts"],
        }

    # ── 4. status == "ok" -> escribir artifacts (+ invocar executor) ───────
    script = result["script"]
    checks = result["checks"]
    attempts = result["attempts"]
    field_catalog_block = result.get("field_catalog")

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
        model=llm_client.current_model_id(),
        generated_at=run_ts,
        # None con la Knowledge Base deshabilitada: el manifest no cambia.
        knowledge_base=result.get("knowledge_base"),
        # Comparación del script con el catálogo de campos (informativo).
        field_catalog=field_catalog_block,
    )
    s3_io.put_manifest(reports_bucket, manifest_key, manifest)

    # Cantidad de nombres de campo que el script lee y el catálogo no lista;
    # la clave solo viaja en el evento cuando la generación la informó.
    field_metrics: dict = {}
    if isinstance(field_catalog_block, dict):
        field_metrics["unknown_field_references"] = field_catalog_block.get(
            "unknown_field_references"
        )

    pointer = {
        "run_id": run_id,
        "manifest_key": manifest_key,
        "script_key": script_key,
        "script_sha256": script_sha256,
    }

    if not auto_execute:
        # Compuerta humana: artifacts escritos y firmados, ejecución pendiente
        # de aprobación manual. Nunca se invoca al executor desde acá.
        logger.warning(
            "AUTO_EXECUTE=false — run_id=%s queda pendiente de aprobación (no se invoca executor)",
            run_id,
        )
        observability.log_event("awaiting_approval", **pointer, checks_count=len(checks))
        _log_result(
            run_id,
            "awaiting_approval",
            checks_count=len(checks),
            map_calls=map_calls,
            attempts=attempts,
            **field_metrics,
        )
        return {"status": "awaiting_approval", **pointer, "attempts": attempts}

    lambda_client = boto3.client("lambda")
    lambda_client.invoke(
        FunctionName=executor_function_name,
        InvocationType="Event",
        Payload=json.dumps(pointer).encode("utf-8"),
    )

    logger.info(
        "=== Policy Generator completado — run_id=%s attempts=%d invocando executor ===",
        run_id,
        attempts,
    )
    _log_result(
        run_id,
        "invoked",
        checks_count=len(checks),
        map_calls=map_calls,
        attempts=attempts,
        **field_metrics,
    )
    return {"status": "invoked", **pointer, "attempts": attempts}
