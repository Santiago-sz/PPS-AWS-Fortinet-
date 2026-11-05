"""Contratos TLS y separación del servidor respecto de AWS."""

import hashlib
import importlib
import ipaddress
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pps_api.server import create_server
from pps_desktop.api import ApiClient


@pytest.fixture
def certificate(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PPS test")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def test_https_roundtrip_upload_and_certificate_validation(service, certificate, document):
    cert, key = certificate
    server = create_server(service, 0, tls_cert=cert, tls_key=key)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"https://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(URLError):
            urlopen(origin + "/api/session", timeout=3)
        client = ApiClient(origin, "", development=True, ca_file=cert)
        assert client.snapshot()["session"]["development"] is True
        created = client.upload(
            {
                "name": "TLS",
                "version_label": "1",
                "scope": "Lab",
                "description": "",
                "device_id": "fgt_local",
                "extension": "docx",
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "size": len(document),
                "sha256": hashlib.sha256(document).hexdigest(),
            },
            document,
            "tls-upload",
        )
        assert created["upload"]["url"].startswith(origin + "/uploads/")
        assert service.audit(created["audit_id"])["status"] == "pending"
        assert client.call("/api/policies/" + created["policy_id"])["status"] == "cargada"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("argument", ["tls_cert", "tls_key"])
def test_incomplete_tls_configuration_is_rejected(service, certificate, argument):
    with pytest.raises(ValueError):
        create_server(service, 0, **{argument: certificate[0]})


def test_server_and_service_import_without_aws_or_gui():
    code = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'boto3', 'botocore', 'pps_desktop'}:
            raise RuntimeError('Dependencia prohibida: ' + fullname)
sys.meta_path.insert(0, Block())
from pps_api.server.app import create_server
from pps_api.services import Service
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_aws_modules_have_a_separate_namespace():
    bridge = importlib.import_module("pps_api.aws.bridge")
    config = importlib.import_module("pps_api.aws.config")
    assert callable(bridge.Bridge)
    assert "PPS_EXECUTOR_FUNCTION" in config.KEYS


def test_local_https_cannot_downgrade_upload_transport():
    from pps_desktop.api import request

    with pytest.raises(ValueError):
        request("http://127.0.0.1:8765/uploads/x", local_origin="https://127.0.0.1:8765")


def test_cli_rejects_incomplete_tls_before_creating_database(tmp_path, monkeypatch):
    from pps_api.__main__ import main

    database = tmp_path / "should-not-exist.sqlite3"
    monkeypatch.setattr(
        sys,
        "argv",
        ["pps-api", "--database", str(database), "serve", "--tls-cert", "missing.pem"],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert not database.exists()
