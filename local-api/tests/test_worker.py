import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from pps_api.aws.worker import BridgeWorker, build_bridge_worker
from pps_api.config import KEYS


class FakeBridge:
    def __init__(self, dispatch_error=None, sync_error=None):
        self.calls = []
        self.dispatch_error, self.sync_error = dispatch_error, sync_error
        self.ticked = threading.Event()

    def dispatch(self):
        self.calls.append("dispatch")
        if self.dispatch_error:
            raise self.dispatch_error
        return 0

    def sync(self):
        self.calls.append("sync")
        self.ticked.set()
        if self.sync_error:
            raise self.sync_error
        return 0


def test_tick_dispatches_before_sync():
    bridge = FakeBridge()
    BridgeWorker(bridge, log=lambda message: None).tick()
    assert bridge.calls == ["dispatch", "sync"]


def test_error_does_not_stop_the_cycle_and_is_logged_without_its_message():
    bridge = FakeBridge(
        dispatch_error=RuntimeError("private-marker"), sync_error=OSError("private-marker")
    )
    logged = []
    worker = BridgeWorker(bridge, log=logged.append)
    worker.tick()
    worker.tick()
    # El envío fallido no impide la recuperación del mismo ciclo ni el ciclo siguiente.
    assert bridge.calls == ["dispatch", "sync", "dispatch", "sync"]
    text = "\n".join(logged)
    assert "RuntimeError" in text and "OSError" in text
    assert "private-marker" not in text
    # Un error repetido se informa una sola vez.
    assert len(logged) == 2


def test_recovery_after_an_error_is_logged_and_counts_are_reported():
    bridge = FakeBridge(dispatch_error=RuntimeError("x"))
    logged = []
    worker = BridgeWorker(bridge, log=logged.append)
    worker.tick()
    bridge.dispatch_error = None
    bridge.dispatch = lambda: 2
    worker.tick()
    assert any("2" in line for line in logged[1:])


def test_error_code_from_aws_is_logged_without_the_message():
    error = Exception("private-marker")
    error.response = {"Error": {"Code": "ExpiredToken", "Message": "private-marker"}}
    logged = []
    BridgeWorker(FakeBridge(dispatch_error=error), log=logged.append).tick()
    assert "ExpiredToken" in logged[0] and "private-marker" not in logged[0]


def test_start_runs_cycles_and_stop_ends_the_thread():
    bridge = FakeBridge()
    worker = BridgeWorker(bridge, interval=0.01, log=lambda message: None)
    worker.start()
    assert bridge.ticked.wait(3)
    worker.stop()
    assert not worker.running
    count = len(bridge.calls)
    assert count >= 2 and bridge.calls[:2] == ["dispatch", "sync"]
    threading.Event().wait(0.05)
    assert len(bridge.calls) == count


def test_stop_interrupts_a_long_wait():
    bridge = FakeBridge()
    worker = BridgeWorker(bridge, interval=3600, log=lambda message: None)
    worker.start()
    assert bridge.ticked.wait(3)
    worker.stop(timeout=3)
    assert not worker.running


def test_stop_without_start_is_harmless():
    BridgeWorker(FakeBridge(), log=lambda message: None).stop()


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def test_build_requires_buckets(clean_env, service):
    with pytest.raises(ValueError, match="PPS_POLICIES_BUCKET"):
        build_bridge_worker(service, Path(".env"), 15)


def test_build_requires_credentials(clean_env, service, monkeypatch):
    import boto3

    (clean_env / ".env").write_text(
        "PPS_POLICIES_BUCKET=pps-policies\nPPS_REPORTS_BUCKET=pps-reports\n"
    )
    session = Mock()
    session.get_credentials.return_value = None
    monkeypatch.setattr(boto3, "Session", Mock(return_value=session))
    with pytest.raises(ValueError, match="credenciales"):
        build_bridge_worker(service, Path(".env"), 15)


def test_build_rejects_short_interval(clean_env, service):
    with pytest.raises(ValueError, match="intervalo"):
        build_bridge_worker(service, Path(".env"), 1)


def test_build_uses_env_without_real_aws(clean_env, service, monkeypatch):
    import boto3

    (clean_env / ".env").write_text(
        "AWS_PROFILE=lab\nAWS_REGION=us-east-1\n"
        "PPS_POLICIES_BUCKET=pps-policies\nPPS_REPORTS_BUCKET=pps-reports\n"
    )
    session = Mock()
    factory = Mock(return_value=session)
    monkeypatch.setattr(boto3, "Session", factory)
    worker = build_bridge_worker(service, Path(".env"), 20)
    factory.assert_called_once_with(profile_name="lab", region_name="us-east-1")
    assert worker.interval == 20 and not worker.running
    assert (worker.bridge.policies_bucket, worker.bridge.reports_bucket) == (
        "pps-policies",
        "pps-reports",
    )
    # Igual que en los comandos explícitos: sin reintentos automáticos del SDK.
    config = session.client.call_args.kwargs["config"]
    assert session.client.call_args.args == ("s3",)
    assert config.retries == {"total_max_attempts": 1}


def test_serve_without_flag_never_touches_aws(clean_env, monkeypatch):
    from pps_api import __main__ as entry

    server = Mock(scheme="http", server_port=8765)
    monkeypatch.setattr("pps_api.server.create_server", Mock(return_value=server))
    built = Mock()
    monkeypatch.setattr("pps_api.aws.worker.build_bridge_worker", built)
    monkeypatch.setattr("sys.argv", ["pps-api", "--database", "api.sqlite3", "serve"])
    entry.main()
    built.assert_not_called()
    server.serve_forever.assert_called_once()


def test_serve_with_bridge_fails_at_startup_without_configuration(clean_env, monkeypatch, capsys):
    from pps_api import __main__ as entry

    created = Mock()
    monkeypatch.setattr("pps_api.server.create_server", created)
    monkeypatch.setattr(
        "sys.argv", ["pps-api", "--database", "api.sqlite3", "serve", "--aws-bridge"]
    )
    with pytest.raises(SystemExit) as exit_info:
        entry.main()
    assert exit_info.value.code == 2
    assert "PPS_POLICIES_BUCKET" in capsys.readouterr().err
    created.assert_not_called()


def test_serve_with_bridge_starts_and_stops_the_worker(clean_env, monkeypatch):
    from pps_api import __main__ as entry

    events = []
    worker = Mock(interval=30.0)
    worker.start.side_effect = lambda: events.append("start")
    worker.stop.side_effect = lambda: events.append("stop")
    seen = {}

    def build(service, env_file, interval):
        seen.update(service=service, interval=interval)
        return worker

    server = Mock(scheme="http", server_port=8765)
    server.serve_forever.side_effect = lambda: events.append(
        ("serving", seen["service"].automatic_dispatch)
    )
    server.server_close.side_effect = lambda: events.append("closed")
    monkeypatch.setattr("pps_api.aws.worker.build_bridge_worker", build)
    monkeypatch.setattr("pps_api.server.create_server", Mock(return_value=server))
    monkeypatch.setattr(
        "sys.argv",
        [
            "pps-api",
            "--database",
            "api.sqlite3",
            "serve",
            "--aws-bridge",
            "--aws-bridge-interval",
            "30",
        ],
    )
    entry.main()
    assert seen["interval"] == 30
    assert events == ["start", ("serving", True), "stop", "closed"]


def test_session_reports_automatic_dispatch(service):
    assert service.session()["capabilities"]["automatic_dispatch"] is False
    service.automatic_dispatch = True
    assert service.session()["capabilities"]["automatic_dispatch"] is True
