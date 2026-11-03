"""Read a small, literal .env configuration without executing or expanding values."""

import os
import re
from pathlib import Path

KEYS = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "PPS_POLICIES_BUCKET",
    "PPS_REPORTS_BUCKET",
}


def load_settings(path, environ=None):
    values = {}
    path = Path(path)
    if path.exists():
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not separator or key not in KEYS:
                raise ValueError(f"Configuración .env inválida en línea {number}.")
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError(f"Comillas sin cerrar en .env, línea {number}.")
                value = value[1:-1]
            if value:
                values[key] = value
    environment = os.environ if environ is None else environ
    values.update({key: environment[key] for key in KEYS if environment.get(key)})
    return values


def aws_options(settings, policies_bucket=None, reports_bucket=None):
    policies = policies_bucket or settings.get("PPS_POLICIES_BUCKET")
    reports = reports_bucket or settings.get("PPS_REPORTS_BUCKET")
    for key, bucket in (("PPS_POLICIES_BUCKET", policies), ("PPS_REPORTS_BUCKET", reports)):
        if not bucket or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise ValueError(f"Completá {key} con el nombre del bucket, sin s3:// ni rutas.")
    if policies == reports:
        raise ValueError("Políticas y reportes requieren buckets distintos.")
    access = settings.get("AWS_ACCESS_KEY_ID")
    secret = settings.get("AWS_SECRET_ACCESS_KEY")
    token = settings.get("AWS_SESSION_TOKEN")
    if bool(access) != bool(secret) or (token and not access):
        raise ValueError("Configurá AWS_ACCESS_KEY_ID y AWS_SECRET_ACCESS_KEY juntos.")
    options = {}
    if access:
        options.update(aws_access_key_id=access, aws_secret_access_key=secret)
        if token:
            options["aws_session_token"] = token
    elif settings.get("AWS_PROFILE"):
        options["profile_name"] = settings["AWS_PROFILE"]
    region = settings.get("AWS_REGION") or settings.get("AWS_DEFAULT_REGION")
    if region:
        options["region_name"] = region
    return options, policies, reports
