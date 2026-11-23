"""
S3 IO helpers para el flujo policy-driven audit script generation.

Cuatro tipos de objeto viven en S3 durante un run:
  - policy   (`policies/...`)      -- PDF/DOCX subido por el usuario, solo lectura
  - script   (`artifacts/{run_id}/script.py`) -- script generado por Claude
  - manifest (`artifacts/{run_id}/manifest.json`) -- RunManifest (design.md)
  - report   (`reports/{run_id}/...`) -- salida final (Markdown/JSON)

`put_script` calcula `script_sha256` a partir de los BYTES EXACTOS escritos
a S3 -- ese hash viaja en el payload puntero generator->executor
(`{run_id, manifest_key, script_key, script_sha256}`, design.md Decision #2)
y en el propio RunManifest, permitiendo que el executor (Fase 8) verifique
integridad byte a byte antes de `exec()`.

Este módulo no atrapa `ClientError` -- sigue la convención fail-loud de
Fase 3/4 (`extractor.py`, `script_validator.py`): un fallo de S3 debe
propagarse, no perderse silenciosamente como un `dict` de error genérico.
"""

import hashlib
import json

import boto3


def get_policy(bucket: str, key: str) -> bytes:
    """Lee el documento de política subido (PDF/DOCX) como bytes crudos."""
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()


def put_script(bucket: str, key: str, source: str) -> str:
    """Escribe el script generado en S3 y devuelve su SHA-256 hexadecimal.

    El hash se calcula sobre los mismos bytes que se envían a S3 -- nunca
    sobre `source` reserializado ni recalculado después -- para que
    `script_sha256` sea una prueba de integridad real, no una convención.
    """
    body = source.encode("utf-8")
    script_sha256 = hashlib.sha256(body).hexdigest()

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="text/x-python; charset=utf-8",
    )
    return script_sha256


def get_script(bucket: str, key: str) -> str:
    """Lee el script generado como texto (UTF-8)."""
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8")


def build_manifest(
    *,
    run_id: str,
    policy_key: str,
    policy_sha256: str,
    script_key: str,
    script_sha256: str,
    checks: list[dict],
    attempts: int,
    model: str,
    generated_at: str,
    knowledge_base: dict | None = None,
    field_catalog: dict | None = None,
) -> dict:
    """Arma un RunManifest según el contrato de design.md (Interfaces/Contracts).

    Argumentos solo por nombre -- son 9 campos del mismo tipo primitivo en
    varios casos (dos `str` que son hashes, dos `str` que son keys); un
    posicional mal ordenado sería un bug silencioso.

    `knowledge_base` es un bloque ADITIVO y opcional: resultado de la
    recuperación de documentación de referencia (si estuvo habilitada, cuántos
    controles obtuvieron referencia, cuántas consultas fallaron y, por
    `check_id`, origen y puntaje de cada fragmento usado; nunca su texto).
    Con `None` la clave no se escribe y el manifest es idéntico al anterior;
    un manifest sin la clave significa recuperación deshabilitada.

    `field_catalog` es otro bloque ADITIVO y opcional: resultado de comparar
    el script entregado con el catálogo de campos del generador (versión de
    FortiOS del catálogo, cantidad de nombres de campo que el script lee y el
    catálogo no lista, las primeras referencias y las llamadas de reduce
    hechas). Solo lleva nombres escritos por el script y claves de endpoint.
    Es informativo: el executor no lo lee y el estado de cada hallazgo lo
    sigue decidiendo `toolkit` al ejecutar.
    """
    manifest = {
        "run_id": run_id,
        "policy_key": policy_key,
        "policy_sha256": policy_sha256,
        "script_key": script_key,
        "script_sha256": script_sha256,
        "checks": checks,
        "attempts": attempts,
        "model": model,
        "generated_at": generated_at,
    }
    if knowledge_base is not None:
        manifest["knowledge_base"] = knowledge_base
    if field_catalog is not None:
        manifest["field_catalog"] = field_catalog
    return manifest


def put_manifest(bucket: str, key: str, manifest: dict) -> None:
    """Escribe el RunManifest como JSON."""
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )


def get_manifest(bucket: str, key: str) -> dict:
    """Lee y parsea el RunManifest JSON."""
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read().decode("utf-8"))


def put_report(bucket: str, key: str, body: str, content_type: str) -> None:
    """Escribe un archivo de reporte (Markdown o JSON) en S3."""
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType=content_type,
    )
