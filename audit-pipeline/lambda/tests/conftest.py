"""
Fixtures compartidas por la suite de tests de la Lambda PPS.

Todos los tests mockean AWS (boto3/botocore — incluido Bedrock) y el
FortiGate real — nunca se hacen llamadas de red reales.
"""

import json

import pytest


@pytest.fixture
def required_env(monkeypatch):
    """Setea las variables de entorno requeridas por handler.py con valores dummy."""
    env = {
        "FORTIGATE_HOST": "192.168.1.1",
        "FORTIGATE_SECRET_ARN": (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:fortigate-token"
        ),
        "S3_BUCKET": "pps-reports-bucket",
        "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:pps-notifications",
        "ENVIRONMENT": "test",
        "FORTIGATE_VERIFY_SSL": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture
def sample_fortigate_data():
    """Data cruda de FortiGate ya "recolectada" — como la devolvería collect_all()."""
    return {
        "system_global": {"hostname": "FGT-LAB"},
        "interfaces": [{"name": "port1"}],
        "admins": [{"name": "admin"}],
        "dns": {"primary": "8.8.8.8"},
        "firewall_policies": [{"policyid": 1}],
        "vpn_ipsec": None,
        "vpn_ssl": None,
        "local_users": [],
        "ips_sensors": [],
        "av_profiles": [],
        "webfilter_profiles": [],
    }


@pytest.fixture
def sample_device_info():
    return {
        "host": "192.168.1.1",
        "environment": "test",
        "region": "us-east-1",
        "run_ts": "2025-01-15T10:30:00Z",
    }


@pytest.fixture
def sample_claude_analysis():
    """Análisis NIST CSF válido, como lo devolvería analyzer.analyze()."""
    return {
        "executive_summary": "Postura de seguridad aceptable con áreas de mejora.",
        "overall_score": 3.2,
        "functions": {
            "GOVERN": {
                "score": 3.0,
                "findings": ["Sin política formal"],
                "recommendations": ["Redactar política"],
            },
            "IDENTIFY": {"score": 3.5, "findings": [], "recommendations": []},
            "PROTECT": {
                "score": 3.0,
                "findings": ["MFA no habilitado"],
                "recommendations": ["Habilitar MFA"],
            },
            "DETECT": {"score": 3.0, "findings": [], "recommendations": []},
            "RESPOND": {"score": 3.5, "findings": [], "recommendations": []},
            "RECOVER": {"score": 3.0, "findings": [], "recommendations": []},
        },
        "critical_issues": ["MFA no habilitado en admins"],
        "quick_wins": ["Habilitar MFA"],
    }


def bedrock_converse_response(
    text: str,
    *,
    input_tokens: int = 1200,
    output_tokens: int = 400,
    cache_read: int = 0,
    cache_write: int = 1200,
    latency_ms: int = 850,
    stop_reason: str = "end_turn",
) -> dict:
    """Simula la respuesta de `bedrock-runtime.converse()` con `text` como
    contenido del primer bloque de texto del mensaje del asistente."""
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": stop_reason,
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": input_tokens + output_tokens,
            "cacheReadInputTokens": cache_read,
            "cacheWriteInputTokens": cache_write,
        },
        "metrics": {"latencyMs": latency_ms},
    }


def bedrock_json_response(payload: dict) -> dict:
    """Respuesta Converse cuyo texto es `payload` serializado como JSON."""
    return bedrock_converse_response(json.dumps(payload))
