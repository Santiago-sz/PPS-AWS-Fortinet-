"""Credential format regression tests for both independently packaged backends."""

import importlib.util
import json
from pathlib import Path

import pytest

import handler
import handler_executor
import handler_generator


@pytest.fixture(params=["lambda", "audit-pipeline/lambda"])
def decode(request):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "credential_decoder", root / request.param / "secret_values.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.credential_value


@pytest.mark.parametrize("field", ["token", "api_key"])
def test_json_and_legacy_credentials(decode, field):
    assert decode(json.dumps({field: "test-credential", "host": "ignored"}), field) == (
        "test-credential"
    )
    assert decode("legacy-credential", field) == "legacy-credential"


@pytest.mark.parametrize("value", [None, "", " ", 123, [], {}])
def test_invalid_field_does_not_leak_other_values(decode, value):
    with pytest.raises(ValueError) as exc:
        decode(json.dumps({"token": value, "api_key": "private-marker"}), "token")
    assert "private-marker" not in str(exc.value)


@pytest.mark.parametrize(
    "secret",
    [
        None,
        "",
        " ",
        "{}",
        '{"token":"private-marker"',
        "[]",
        '"private-marker"',
        "null",
        "123",
        '{"api_key":"private-marker"}',
        "REEMPLAZAR_CON_TOKEN_REAL",
        '{"token":"REEMPLAZAR_CON_TOKEN_REAL"}',
    ],
)
def test_invalid_secret_is_rejected(decode, secret):
    with pytest.raises(ValueError) as exc:
        decode(secret, "token")
    assert "private-marker" not in str(exc.value)


@pytest.mark.parametrize(
    "module,reader,field",
    [
        (handler, "get_secret", "token"),
        (handler, "get_secret", "api_key"),
        (handler_generator, "_get_secret", "api_key"),
        (handler_executor, "_get_secret", "token"),
    ],
)
def test_aws_reader_extracts_requested_field(mocker, module, reader, field):
    sm = mocker.patch.object(module.boto3, "client").return_value
    sm.get_secret_value.return_value = {
        "SecretString": json.dumps({"token": "fgt-test", "api_key": "claude-test"})
    }
    expected = "fgt-test" if field == "token" else "claude-test"
    assert getattr(module, reader)("test-secret-arn", field) == expected
    sm.get_secret_value.assert_called_once_with(SecretId="test-secret-arn")
