"""Decode Secrets Manager credentials without exposing their contents."""

import json


def credential_value(secret: str, field: str) -> str:
    """Accept a JSON object or a legacy raw credential; reject malformed JSON."""
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("SecretString must contain a non-empty credential")
    try:
        payload = json.loads(secret)
    except json.JSONDecodeError:
        if secret.lstrip().startswith(("{", "[", '\"')):
            raise ValueError("SecretString contains invalid JSON") from None
        value = secret
    else:
        if not isinstance(payload, dict):
            raise ValueError("SecretString JSON must be an object")
        value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"SecretString requires a non-empty string field: {field}")
    if value.startswith("REEMPLAZAR_CON_"):
        raise ValueError("SecretString still contains a deployment placeholder")
    return value
