"""
Fixtures compartidas por la suite de tests de la Lambda PPS.

Todos los tests mockean AWS (boto3/botocore), el FortiGate real y la API
de Claude — nunca se hacen llamadas de red reales.
"""

import json
from urllib.error import HTTPError

import pytest


@pytest.fixture
def required_env(monkeypatch):
    """Setea las variables de entorno requeridas por handler.py con valores dummy."""
    env = {
        "FORTIGATE_HOST": "192.168.1.1",
        "FORTIGATE_SECRET_ARN": (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:fortigate-token"
        ),
        "CLAUDE_SECRET_ARN": (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:claude-api-key"
        ),
        "S3_BUCKET": "pps-reports-bucket",
        "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:pps-notifications",
        "ENVIRONMENT": "test",
        "FORTIGATE_VERIFY_SSL": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


def make_http_error(url: str, code: int, reason: str, body: bytes = b"") -> HTTPError:
    """Construye un urllib.error.HTTPError utilizable en tests, con .read() funcional."""
    import io

    err = HTTPError(url=url, code=code, msg=reason, hdrs=None, fp=io.BytesIO(body))
    return err


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


def claude_http_response_body(analysis: dict) -> bytes:
    """Simula el body JSON que devuelve la API de Claude (response.content[0].text)."""
    payload = {
        "content": [{"type": "text", "text": json.dumps(analysis)}],
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 400,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 1200,
        },
    }
    return json.dumps(payload).encode("utf-8")
