"""La conexión local HTTPS conserva la verificación del certificado."""

import ssl

import pytest

from pps_desktop.api import ApiClient


def test_local_https_uses_system_trust_without_custom_ca():
    client = ApiClient("https://127.0.0.1:8765", "", development=True)
    assert client.base_url == "https://127.0.0.1:8765"


@pytest.mark.parametrize(
    "development,url",
    [
        (False, "https://example.com"),
        (True, "http://127.0.0.1:8765"),
    ],
)
def test_custom_local_ca_cannot_change_other_connection_modes(development, url):
    with pytest.raises(ValueError):
        ApiClient(url, "", development=development, ca_file="missing.pem")


def test_custom_local_ca_keeps_hostname_and_certificate_checks(monkeypatch):
    context = ssl.create_default_context()
    calls = []
    monkeypatch.setattr(
        "pps_desktop.api.ssl.create_default_context",
        lambda **kwargs: calls.append(kwargs) or context,
    )
    client = ApiClient("https://127.0.0.1:8765", "", development=True, ca_file="ca.pem")
    assert calls == [{"cafile": "ca.pem"}]
    assert client.ssl_context.check_hostname
    assert client.ssl_context.verify_mode == ssl.CERT_REQUIRED
