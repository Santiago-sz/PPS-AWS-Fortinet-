import json

from cryptography.fernet import Fernet
import pytest

from pps_desktop import api
from pps_desktop.storage import SecureCache


def test_cache_encrypted_scoped_expiring_and_clearable(tmp_path):
    clock = [100]
    cache = SecureCache(
        tmp_path, "org1|user1", ttl=10, key=Fernet.generate_key(), clock=lambda: clock[0]
    )
    cache.save({"secret_evidence": "private value"})
    assert b"private value" not in cache.path.read_bytes()
    assert cache.load()["secret_evidence"] == "private value"
    other = SecureCache(tmp_path, "org2|user1", key=Fernet.generate_key())
    assert other.load() is None
    clock[0] = 111
    assert cache.load() is None
    assert not cache.path.exists()


def test_corrupted_cache_not_loaded(tmp_path):
    cache = SecureCache(tmp_path, "org|user", key=Fernet.generate_key())
    cache.path.write_bytes(b"not-encrypted")
    assert cache.load() is None


@pytest.mark.parametrize(
    "url", ["http://example.com", "https://user:pass@example.com", "file:///data", "https:///path"]
)
def test_reject_insecure_endpoints(url):
    with pytest.raises(ValueError):
        api.https_url(url)


def test_pagination_and_auth_header(monkeypatch):
    calls = []

    def fake(url, method, data, headers):
        calls.append((url, headers))
        return json.dumps(
            {
                "items": [2] if "cursor=" in url else [1],
                "next_cursor": None if "cursor=" in url else "opaque/+",
            }
        ).encode()

    monkeypatch.setattr(api, "request", fake)
    client = api.ApiClient("https://example.com", "short-lived")
    assert client.collection("/api/policies") == [1, 2]
    assert calls[0][1]["Authorization"] == "Bearer short-lived"
    assert "cursor=opaque%2F%2B" in calls[1][0]


def test_upload_has_idempotency_but_no_bearer_on_s3(monkeypatch):
    calls = []

    def fake(url, method="GET", data=None, headers=None, **kwargs):
        calls.append((url, method, data, headers))
        if url.endswith("/api/policies"):
            return json.dumps(
                {
                    "policy_id": "p",
                    "version_id": "v",
                    "upload_id": "u",
                    "audit_id": "a",
                    "upload": {
                        "url": "https://storage.example.com/signed",
                        "method": "PUT",
                        "headers": {"Content-Type": "application/pdf"},
                    },
                }
            ).encode()
        return b"{}"

    monkeypatch.setattr(api, "request", fake)
    client = api.ApiClient("https://example.com", "token")
    client.upload({"sha256": "hash", "size": 3}, b"pdf", "stable-key")
    assert calls[0][3]["Idempotency-Key"] == calls[2][3]["Idempotency-Key"] == "stable-key"
    assert "Authorization" not in calls[1][3]
    assert calls[1][2] == b"pdf"


def test_roles_require_server_session(monkeypatch):
    client = api.ApiClient("https://example.com", "token")
    monkeypatch.setattr(client, "call", lambda _: {"role": "invented"})
    with pytest.raises(api.ApiError, match="rol"):
        client.snapshot()


def test_no_redirect_for_credentials():
    assert api.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:8765",
        "http://localhost:8765",
        "http://127.0.0.1.evil:8765",
        "http://127.0.0.1:8765/api",
        "http://user:pass@127.0.0.1:8765",
    ],
)
def test_development_client_is_loopback_only(url):
    with pytest.raises(ValueError):
        api.ApiClient(url, "", development=True)


def test_development_client_requires_opt_in_and_never_sends_token(monkeypatch):
    with pytest.raises(ValueError):
        api.ApiClient("http://127.0.0.1:8765", "")
    with pytest.raises(ValueError):
        api.ApiClient("http://127.0.0.1:8765", "token", development=True)
    calls = []

    def fake(url, method, data, headers, **kwargs):
        calls.append((headers, kwargs))
        return b"{}"

    monkeypatch.setattr(api, "request", fake)
    client = api.ApiClient("http://127.0.0.1:8765", "", development=True)
    client.call("/api/session")
    assert "Authorization" not in calls[0][0]
    assert calls[0][1]["local_origin"] == client.base_url


def test_development_transport_rejects_different_origin():
    with pytest.raises(ValueError):
        api.request("http://127.0.0.1:9999/uploads/x", local_origin="http://127.0.0.1:8765")
