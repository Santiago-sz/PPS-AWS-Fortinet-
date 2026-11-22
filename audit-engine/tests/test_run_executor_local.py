"""
Tests for scripts/run_executor_local.py: the local runner of the executor stage.

The runner exists for the first real test, where the FortiGate is reachable
only through a user VPN on the operator's workstation. It must keep the same
gate order as `handler_executor` (integrity, independent re-validation, then
the sandbox), add a connectivity preflight, and write the report to a local
directory only: no S3 put, no SNS publish, no Secrets Manager call.

S3 is a real moto backend; the FortiGate client is a fake. No real AWS or
FortiGate call is ever made.
"""

import hashlib
import importlib.util
import json
import logging
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

import sandbox

RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_executor_local.py"

BUCKET = "pps-reports-bucket"
RUN_ID = "0123456789abcdef0123456789abcdef"
HOST = "192.0.2.10"
TOKEN = "tkn-SENTINEL-do-not-leak-7f3a9c"

VALID_SCRIPT = (
    "data = fgt.get('admins')\n"
    "if data:\n"
    "    report.finding('chk-0001', 'fail', 'admins: ' + str(data))\n"
    "else:\n"
    "    report.finding('chk-0001', 'pass', 'no admins configured')\n"
)

FORBIDDEN_SCRIPT = "import os\nreport.finding('chk-0001', 'pass', 'x')\n"


def _manifest(script: str, **overrides) -> dict:
    manifest = {
        "run_id": RUN_ID,
        "policy_key": "policies/norma.pdf",
        "policy_sha256": "a" * 64,
        "script_key": f"artifacts/{RUN_ID}/script.py",
        "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "checks": [
            {
                "check_id": "chk-0001",
                "title": "Admin accounts",
                "clause_ref": {
                    "chunk_id": "chunk-0001",
                    "heading_path": ["Art 1"],
                    "page": 1,
                    "quote": "Administrators must be reviewed.",
                },
                "endpoints": ["admins"],
                "severity": "high",
                "intent": "verify",
            }
        ],
        "attempts": 1,
        "model": "test-model",
        "generated_at": "2026-11-21T12:00:00Z",
    }
    manifest.update(overrides)
    return manifest


class FakeFortiGateClient:
    """Stands in for `FortiGateClient`; records how it was built and used."""

    instances: list = []
    responses: dict = {}
    log_on_get: str | None = None

    def __init__(self, host, token, verify_ssl=True):
        self.host = host
        self.token = token
        self.verify_ssl = verify_ssl
        self.calls: list[str] = []
        FakeFortiGateClient.instances.append(self)

    def get(self, endpoint_key):
        self.calls.append(endpoint_key)
        if FakeFortiGateClient.log_on_get:
            logging.getLogger("fortigate_client").error(
                "Error inesperado: %s", FakeFortiGateClient.log_on_get
            )
        return FakeFortiGateClient.responses.get(endpoint_key)


@pytest.fixture
def runner():
    spec = importlib.util.spec_from_file_location("run_executor_local", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def base_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    monkeypatch.setenv("FORTIGATE_HOST", HOST)
    monkeypatch.setenv("FORTIGATE_TOKEN", TOKEN)
    for name in ("FORTIGATE_VERIFY_SSL", "SANDBOX_WALL_CLOCK_SECONDS", "SANDBOX_MAX_FGT_CALLS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    FakeFortiGateClient.instances = []
    FakeFortiGateClient.responses = {
        "system_global": {"hostname": "FGT-TEST"},
        "admins": [{"name": "admin"}],
    }
    FakeFortiGateClient.log_on_get = None
    return FakeFortiGateClient


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def _store_run(s3, script=VALID_SCRIPT, manifest=None, stored_script=None):
    manifest = manifest if manifest is not None else _manifest(script)
    s3.put_object(
        Bucket=BUCKET,
        Key=f"artifacts/{RUN_ID}/manifest.json",
        Body=json.dumps(manifest).encode("utf-8"),
    )
    body = stored_script if stored_script is not None else script
    s3.put_object(Bucket=BUCKET, Key=f"artifacts/{RUN_ID}/script.py", Body=body.encode("utf-8"))


def _bucket_keys(s3) -> list[str]:
    listing = s3.list_objects_v2(Bucket=BUCKET)
    return sorted(obj["Key"] for obj in listing.get("Contents", []))


def _run(runner, monkeypatch, tmp_path, *extra_args):
    monkeypatch.setattr(runner, "FortiGateClient", FakeFortiGateClient)
    return runner.main([RUN_ID, "--output-dir", str(tmp_path), *extra_args])


def _report_files(tmp_path) -> tuple[Path, Path]:
    json_files = list(tmp_path.rglob("report.json"))
    md_files = list(tmp_path.rglob("report.md"))
    assert len(json_files) == 1, json_files
    assert len(md_files) == 1, md_files
    assert json_files[0].parent == md_files[0].parent
    return json_files[0], md_files[0]


class TestHappyPath:
    def test_writes_local_json_and_markdown(self, runner, s3, monkeypatch, tmp_path):
        _store_run(s3)

        exit_code = _run(runner, monkeypatch, tmp_path)

        assert exit_code == 0
        json_path, md_path = _report_files(tmp_path)
        assert RUN_ID in json_path.parts
        report = json.loads(json_path.read_text(encoding="utf-8"))
        assert report["run_id"] == RUN_ID
        assert report["status"] == "completed"
        assert report["truncated"] is False
        assert [f["check_id"] for f in report["findings"]] == ["chk-0001"]
        assert report["findings"][0]["status"] == "fail"
        assert report["findings"][0]["traceable"] is True
        assert "chk-0001" in md_path.read_text(encoding="utf-8")

    def test_local_report_is_marked_as_a_local_run(self, runner, s3, monkeypatch, tmp_path):
        _store_run(s3)

        _run(runner, monkeypatch, tmp_path)

        json_path, md_path = _report_files(tmp_path)
        report = json.loads(json_path.read_text(encoding="utf-8"))
        assert report["execution"]["mode"] == "local"
        assert report["execution"]["published"] is False
        assert "local" in md_path.read_text(encoding="utf-8").lower()

    def test_does_not_write_to_s3_nor_use_sns_or_secrets_manager(
        self, runner, s3, monkeypatch, tmp_path, mocker
    ):
        _store_run(s3)
        keys_before = _bucket_keys(s3)
        put_report = mocker.patch("s3_io.put_report")
        publish = mocker.patch("reporter.publish_to_sns")
        deliver = mocker.patch("reporter.deliver_policy_report")
        created_services = []
        real_client = boto3.client

        def recording_client(service_name, *args, **kwargs):
            created_services.append(service_name)
            return real_client(service_name, *args, **kwargs)

        mocker.patch("boto3.client", side_effect=recording_client)

        exit_code = _run(runner, monkeypatch, tmp_path)

        assert exit_code == 0
        assert set(created_services) == {"s3"}
        put_report.assert_not_called()
        publish.assert_not_called()
        deliver.assert_not_called()
        assert _bucket_keys(s3) == keys_before
        assert not any(key.startswith("reports/") for key in _bucket_keys(s3))

    def test_client_is_built_from_the_environment(self, runner, s3, monkeypatch, tmp_path):
        _store_run(s3)

        _run(runner, monkeypatch, tmp_path)

        (client,) = FakeFortiGateClient.instances
        assert client.host == HOST
        assert client.token == TOKEN
        assert client.verify_ssl is True

    def test_verify_ssl_false_is_honoured(self, runner, s3, monkeypatch, tmp_path):
        _store_run(s3)
        monkeypatch.setenv("FORTIGATE_VERIFY_SSL", "false")

        _run(runner, monkeypatch, tmp_path)

        (client,) = FakeFortiGateClient.instances
        assert client.verify_ssl is False

    def test_bucket_argument_overrides_the_environment(self, runner, s3, monkeypatch, tmp_path):
        _store_run(s3)
        monkeypatch.setenv("S3_BUCKET", "another-bucket-that-does-not-exist")

        exit_code = _run(runner, monkeypatch, tmp_path, "--bucket", BUCKET)

        assert exit_code == 0

    def test_sandbox_budget_env_is_honoured_and_reports_truncated(
        self, runner, s3, monkeypatch, tmp_path
    ):
        _store_run(s3)
        monkeypatch.setenv("SANDBOX_MAX_FGT_CALLS", "0")

        exit_code = _run(runner, monkeypatch, tmp_path)

        assert exit_code == 1
        json_path, _ = _report_files(tmp_path)
        report = json.loads(json_path.read_text(encoding="utf-8"))
        assert report["status"] == "truncated"
        assert report["truncated"] is True
        assert report["failure_reason"] == "call_count_exceeded"

    def test_two_runs_do_not_overwrite_each_other(self, runner, s3, monkeypatch, tmp_path):
        _store_run(s3)
        stamps = iter(["20261121T120000Z", "20261121T120500Z"])
        monkeypatch.setattr(runner, "_run_stamp", lambda: next(stamps))

        assert _run(runner, monkeypatch, tmp_path) == 0
        assert _run(runner, monkeypatch, tmp_path) == 0

        assert len(list(tmp_path.rglob("report.json"))) == 2


class TestGatesBeforeExecution:
    def test_sha256_mismatch_aborts_before_execution(
        self, runner, s3, monkeypatch, tmp_path, mocker
    ):
        _store_run(s3, stored_script=VALID_SCRIPT + "report.note('chk-0001', 'tampered')\n")
        validate = mocker.spy(runner.script_validator, "validate")
        execute = mocker.spy(sandbox, "execute")

        exit_code = _run(runner, monkeypatch, tmp_path)

        assert exit_code == 1
        validate.assert_not_called()
        execute.assert_not_called()
        assert FakeFortiGateClient.instances == []
        json_path, _ = _report_files(tmp_path)
        report = json.loads(json_path.read_text(encoding="utf-8"))
        assert report["status"] == "could_not_audit"
        assert report["failure_reason"] == "integrity_check_failed"
        assert report["findings"] == []

    def test_validator_rejection_aborts_before_execution(
        self, runner, s3, monkeypatch, tmp_path, mocker
    ):
        _store_run(s3, script=FORBIDDEN_SCRIPT)
        execute = mocker.spy(sandbox, "execute")

        exit_code = _run(runner, monkeypatch, tmp_path)

        assert exit_code == 1
        execute.assert_not_called()
        assert FakeFortiGateClient.instances == []
        json_path, _ = _report_files(tmp_path)
        report = json.loads(json_path.read_text(encoding="utf-8"))
        assert report["status"] == "could_not_audit"
        assert report["failure_reason"].startswith("revalidation_failed:")

    def test_validation_runs_from_scratch_on_the_script_read_from_s3(
        self, runner, s3, monkeypatch, tmp_path, mocker
    ):
        _store_run(s3)
        validate = mocker.spy(runner.script_validator, "validate")

        _run(runner, monkeypatch, tmp_path)

        validate.assert_called_once()
        assert validate.call_args.args[0] == VALID_SCRIPT

    def test_manifest_of_another_run_is_refused(self, runner, s3, monkeypatch, tmp_path, mocker):
        _store_run(s3, manifest=_manifest(VALID_SCRIPT, run_id="ffffffffffffffffffffffffffffffff"))
        execute = mocker.spy(sandbox, "execute")

        exit_code = _run(runner, monkeypatch, tmp_path)

        assert exit_code == 2
        execute.assert_not_called()

    def test_script_key_outside_the_run_prefix_is_refused(
        self, runner, s3, monkeypatch, tmp_path, mocker
    ):
        _store_run(s3, manifest=_manifest(VALID_SCRIPT, script_key="artifacts/other/script.py"))
        execute = mocker.spy(sandbox, "execute")

        exit_code = _run(runner, monkeypatch, tmp_path)

        assert exit_code == 2
        execute.assert_not_called()

    def test_missing_run_fails_clearly(self, runner, s3, monkeypatch, tmp_path, capsys):
        exit_code = _run(runner, monkeypatch, tmp_path)

        assert exit_code == 2
        assert "manifest" in capsys.readouterr().err.lower()
        assert list(tmp_path.rglob("report.json")) == []


class TestPreflight:
    def test_preflight_failure_aborts_without_running_the_sandbox(
        self, runner, s3, monkeypatch, tmp_path, mocker, capsys
    ):
        _store_run(s3)
        FakeFortiGateClient.responses = {}
        execute = mocker.spy(sandbox, "execute")

        exit_code = _run(runner, monkeypatch, tmp_path)

        assert exit_code == 3
        execute.assert_not_called()
        (client,) = FakeFortiGateClient.instances
        assert client.calls == ["system_global"]
        assert list(tmp_path.rglob("report.*")) == []
        err = capsys.readouterr().err
        assert "VPN" in err
        assert "trusted host" in err.lower()
        assert "port" in err.lower()
        assert "FORTIGATE_VERIFY_SSL" in err

    def test_preflight_exception_is_treated_as_a_failure(
        self, runner, s3, monkeypatch, tmp_path, mocker
    ):
        _store_run(s3)
        execute = mocker.spy(sandbox, "execute")

        class ExplodingClient(FakeFortiGateClient):
            def get(self, endpoint_key):
                raise RuntimeError("boom")

        monkeypatch.setattr(runner, "FortiGateClient", ExplodingClient)
        exit_code = runner.main([RUN_ID, "--output-dir", str(tmp_path)])

        assert exit_code == 3
        execute.assert_not_called()

    def test_preflight_runs_before_the_sandbox(self, runner, s3, monkeypatch, tmp_path):
        _store_run(s3)

        _run(runner, monkeypatch, tmp_path)

        (client,) = FakeFortiGateClient.instances
        assert client.calls[0] == "system_global"
        assert "admins" in client.calls[1:]


class TestConfiguration:
    @pytest.mark.parametrize("missing", ["S3_BUCKET", "FORTIGATE_HOST", "FORTIGATE_TOKEN"])
    def test_missing_env_var_fails_with_a_clear_message(
        self, runner, monkeypatch, tmp_path, mocker, capsys, missing
    ):
        monkeypatch.delenv(missing)
        boto_client = mocker.patch("boto3.client")

        exit_code = _run(runner, monkeypatch, tmp_path)

        assert exit_code == 2
        assert missing in capsys.readouterr().err
        boto_client.assert_not_called()
        assert FakeFortiGateClient.instances == []

    def test_all_missing_env_vars_are_listed_at_once(self, runner, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("FORTIGATE_HOST")
        monkeypatch.delenv("FORTIGATE_TOKEN")

        exit_code = _run(runner, monkeypatch, tmp_path)

        err = capsys.readouterr().err
        assert exit_code == 2
        assert "FORTIGATE_HOST" in err
        assert "FORTIGATE_TOKEN" in err

    def test_token_cannot_be_passed_as_an_argument(self, runner, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "FortiGateClient", FakeFortiGateClient)

        with pytest.raises(SystemExit) as excinfo:
            runner.main([RUN_ID, "--output-dir", str(tmp_path), "--token", "x"])

        assert excinfo.value.code == 2

    def test_token_with_inner_whitespace_is_rejected_without_echo(
        self, runner, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setenv("FORTIGATE_TOKEN", "abc\ndef-SECRETPART")

        exit_code = _run(runner, monkeypatch, tmp_path)

        captured = capsys.readouterr()
        assert exit_code == 2
        assert "FORTIGATE_TOKEN" in captured.err
        assert "SECRETPART" not in captured.err + captured.out
        assert FakeFortiGateClient.instances == []

    @pytest.mark.parametrize("bad_run_id", ["../etc", "run/1", "", "a b", "."])
    def test_invalid_run_id_is_rejected(self, runner, monkeypatch, tmp_path, mocker, bad_run_id):
        monkeypatch.setattr(runner, "FortiGateClient", FakeFortiGateClient)
        boto_client = mocker.patch("boto3.client")

        exit_code = runner.main([bad_run_id, "--output-dir", str(tmp_path)])

        assert exit_code == 2
        boto_client.assert_not_called()

    def test_default_output_directory_is_git_ignored(self, runner):
        engine_dir = RUNNER_PATH.parents[1]
        assert runner.DEFAULT_OUTPUT_DIR == engine_dir / "local-runs"
        root_ignore = (engine_dir.parent / ".gitignore").read_text(encoding="utf-8")
        engine_ignore = (engine_dir / ".gitignore").read_text(encoding="utf-8")
        assert "audit-engine/local-runs/" in root_ignore.splitlines()
        assert "local-runs/" in engine_ignore.splitlines()


class TestPackaging:
    def test_runner_is_not_part_of_the_lambda_package(self):
        engine_dir = RUNNER_PATH.parents[1]
        packaged_areas = ("generator", "executor", "contracts", "legacy")
        assert RUNNER_PATH.parent == engine_dir / "scripts"
        for area in packaged_areas:
            assert not (engine_dir / area / RUNNER_PATH.name).exists(), area
        terraform = (engine_dir.parent / "infrastructure/pipeline/lambda.tf").read_text(
            encoding="utf-8"
        )
        assert 'for area in ["generator", "executor", "contracts", "legacy"]' in terraform
        assert 'fileset("${path.module}/../../audit-engine/${area}", "*.py")' in terraform

    def test_runner_does_not_import_the_lambda_handler_or_model_clients(self):
        source = RUNNER_PATH.read_text(encoding="utf-8")
        for forbidden in ("handler_executor", "llm_client", "bedrock_client", "secretsmanager"):
            assert f"import {forbidden}" not in source
            assert f'client("{forbidden}")' not in source


class TestPlatformWarning:
    def test_warns_when_the_wall_clock_backstop_is_unavailable(
        self, runner, s3, monkeypatch, tmp_path, capsys
    ):
        _store_run(s3)
        monkeypatch.delattr(runner.signal, "setitimer", raising=False)

        _run(runner, monkeypatch, tmp_path)

        err = capsys.readouterr().err
        assert "WARNING" in err
        assert "wall-clock backstop" in err


class TestTokenNeverLeaks:
    def _assert_token_absent(self, tmp_path, capsys, caplog):
        captured = capsys.readouterr()
        assert TOKEN not in captured.out
        assert TOKEN not in captured.err
        assert TOKEN not in caplog.text
        for record in caplog.records:
            assert TOKEN not in record.getMessage()
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert TOKEN not in path.read_text(encoding="utf-8"), path

    def test_happy_path(self, runner, s3, monkeypatch, tmp_path, capsys, caplog):
        _store_run(s3)
        caplog.set_level(logging.DEBUG)

        assert _run(runner, monkeypatch, tmp_path) == 0

        _report_files(tmp_path)
        self._assert_token_absent(tmp_path, capsys, caplog)

    def test_preflight_failure(self, runner, s3, monkeypatch, tmp_path, capsys, caplog):
        _store_run(s3)
        FakeFortiGateClient.responses = {}
        caplog.set_level(logging.DEBUG)

        assert _run(runner, monkeypatch, tmp_path) == 3

        self._assert_token_absent(tmp_path, capsys, caplog)

    def test_token_logged_by_a_dependency_is_redacted(
        self, runner, s3, monkeypatch, tmp_path, capsys, caplog
    ):
        # http.client embeds the header value in the error it raises for a
        # malformed header, and the client logs that error text.
        _store_run(s3)
        FakeFortiGateClient.log_on_get = f"Invalid header value b'Bearer {TOKEN}'"
        caplog.set_level(logging.DEBUG)

        assert _run(runner, monkeypatch, tmp_path) == 0

        assert "Invalid header value" in caplog.text
        self._assert_token_absent(tmp_path, capsys, caplog)

    def test_token_returned_by_the_device_is_redacted_in_the_report(
        self, runner, s3, monkeypatch, tmp_path, capsys, caplog
    ):
        _store_run(s3)
        FakeFortiGateClient.responses["admins"] = [{"name": "admin", "leak": TOKEN}]
        caplog.set_level(logging.DEBUG)

        assert _run(runner, monkeypatch, tmp_path) == 0

        json_path, _ = _report_files(tmp_path)
        assert "REDACTED" in json_path.read_text(encoding="utf-8")
        self._assert_token_absent(tmp_path, capsys, caplog)

    def test_redaction_filter_is_removed_after_the_run(self, runner, s3, monkeypatch, tmp_path):
        _store_run(s3)
        root = logging.getLogger()
        handlers_before = list(root.handlers)
        filters_before = [list(h.filters) for h in handlers_before]

        _run(runner, monkeypatch, tmp_path)

        assert list(root.handlers) == handlers_before
        assert [list(h.filters) for h in handlers_before] == filters_before
