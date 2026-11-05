from unittest.mock import Mock

import pytest
from pps_api.config import aws_options, load_settings


def test_env_literal_values_and_environment_precedence(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        '# config\nAWS_ACCESS_KEY_ID="test-id"\nAWS_SECRET_ACCESS_KEY=literal$VALUE=+/#\n'
        "AWS_SESSION_TOKEN='temporary-token'\nAWS_REGION=us-east-1\n",
        encoding="utf-8-sig",
    )
    values = load_settings(
        path, {"AWS_REGION": "sa-east-1", "PPS_EXECUTOR_FUNCTION": "pps-executor"}
    )
    assert values["PPS_EXECUTOR_FUNCTION"] == "pps-executor"
    assert values["AWS_ACCESS_KEY_ID"] == "test-id"
    assert values["AWS_SECRET_ACCESS_KEY"] == "literal$VALUE=+/#"
    assert values["AWS_SESSION_TOKEN"] == "temporary-token"
    assert values["AWS_REGION"] == "sa-east-1"


@pytest.mark.parametrize("content", ["AWS_SECRET_ACCESS_KEY='private-marker", "BAD=private-marker"])
def test_invalid_env_never_echoes_value(tmp_path, content):
    path = tmp_path / ".env"
    path.write_text(content)
    with pytest.raises(ValueError) as error:
        load_settings(path, {})
    assert "private-marker" not in str(error.value)


def test_profile_and_cli_bucket_override():
    options, policies, reports = aws_options(
        {
            "AWS_PROFILE": "lab",
            "AWS_REGION": "sa-east-1",
            "PPS_POLICIES_BUCKET": "old-policies",
            "PPS_REPORTS_BUCKET": "pps-reports",
        },
        policies_bucket="new-policies",
    )
    assert options == {"profile_name": "lab", "region_name": "sa-east-1"}
    assert (policies, reports) == ("new-policies", "pps-reports")


@pytest.mark.parametrize("values", [{"AWS_ACCESS_KEY_ID": "id"}, {"AWS_SESSION_TOKEN": "token"}])
def test_partial_credentials_rejected(values):
    with pytest.raises(ValueError):
        aws_options(values, "pps-policies", "pps-reports")


def test_missing_env_preserves_default_credential_chain(tmp_path):
    values = load_settings(tmp_path / "absent", {})
    assert aws_options(values, "pps-policies", "pps-reports")[0] == {}


def test_cli_uses_env_credentials_without_real_aws(tmp_path, monkeypatch):
    import boto3
    from pps_api.__main__ import main
    from pps_api.aws_bridge import Bridge

    monkeypatch.chdir(tmp_path)
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "PPS_POLICIES_BUCKET",
        "PPS_REPORTS_BUCKET",
    ):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "AWS_ACCESS_KEY_ID=test-id\nAWS_SECRET_ACCESS_KEY=test-secret\n"
        "AWS_SESSION_TOKEN=test-token\nAWS_REGION=sa-east-1\n"
        "PPS_POLICIES_BUCKET=pps-policies\nPPS_REPORTS_BUCKET=pps-reports\n"
    )
    session = Mock()
    factory = Mock(return_value=session)
    monkeypatch.setattr(boto3, "Session", factory)
    dispatched = []
    monkeypatch.setattr(
        Bridge,
        "dispatch",
        lambda self: dispatched.append((self.policies_bucket, self.reports_bucket)) or 0,
    )
    monkeypatch.setattr("sys.argv", ["pps-api", "aws", "dispatch"])
    main()
    factory.assert_called_once_with(
        aws_access_key_id="test-id",
        aws_secret_access_key="test-secret",
        aws_session_token="test-token",
        region_name="sa-east-1",
    )
    assert dispatched == [("pps-policies", "pps-reports")]


def test_cli_approve_uses_env_executor_and_lambda_client(tmp_path, monkeypatch, capsys):
    import boto3
    from pps_api.__main__ import main
    from pps_api.aws_bridge import Bridge
    from pps_api.config import KEYS

    monkeypatch.chdir(tmp_path)
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "AWS_PROFILE=lab\nPPS_POLICIES_BUCKET=pps-policies\nPPS_REPORTS_BUCKET=pps-reports\n"
        "PPS_EXECUTOR_FUNCTION=pps-executor\n"
    )
    session = Mock()
    monkeypatch.setattr(boto3, "Session", Mock(return_value=session))
    approved = []
    monkeypatch.setattr(
        Bridge,
        "approve",
        lambda self, run_id, function, client: approved.append((run_id, function, client)) or 202,
    )
    monkeypatch.setattr("sys.argv", ["pps-api", "aws", "approve", "run123"])
    main()
    assert approved == [("run123", "pps-executor", session.client.return_value)]
    assert session.client.call_args_list[-1].args == ("lambda",)
    assert "StatusCode 202" in capsys.readouterr().out
    monkeypatch.setattr(
        "sys.argv", ["pps-api", "aws", "approve", "run123", "--executor-function", "x"]
    )
    main()
    assert approved[-1][1] == "x"
    monkeypatch.setattr("sys.argv", ["pps-api", "aws", "approve"])
    with pytest.raises(SystemExit):
        main()
    monkeypatch.setattr("sys.argv", ["pps-api", "aws", "sync", "run123"])
    with pytest.raises(SystemExit):
        main()
