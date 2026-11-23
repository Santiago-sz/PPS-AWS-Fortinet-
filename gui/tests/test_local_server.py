import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import pytest

from pps_desktop import local_server
from pps_desktop.app import Window
from pps_desktop.local_server import LocalApiProcess


class FakeProcess:
    def __init__(self, returncode=None, hangs=False):
        self.returncode, self.hangs = returncode, hangs
        self.calls = []

    def poll(self):
        return self.returncode

    def terminate(self):
        self.calls.append("terminate")
        if not self.hangs:
            self.returncode = 1

    def kill(self):
        self.calls.append("kill")
        self.returncode = 1

    def wait(self, timeout=None):
        self.calls.append("wait")
        if self.returncode is None:
            raise subprocess.TimeoutExpired("pps-api", timeout)
        return self.returncode


class Launcher:
    """Reemplaza la creación de procesos y el sondeo del puerto."""

    def __init__(self, answers=False, processes=None):
        self.answers = answers
        self.processes = list(processes or [FakeProcess()])
        self.started = []

    def popen(self, command, **options):
        self.started.append((command, options))
        return self.processes[len(self.started) - 1]

    def probe(self):
        return self.answers

    def server(self, **options):
        options.setdefault("command", lambda bridge: ["python", "api"] + ["--aws-bridge"] * bridge)
        return LocalApiProcess(popen=self.popen, probe=self.probe, **options)


def test_running_api_is_reused_and_never_stopped():
    launcher = Launcher(answers=True)
    server = launcher.server()
    assert server.ensure_started() == "external"
    server.stop()
    assert launcher.started == []


def test_starts_one_child_with_the_bridge_and_reports_when_it_answers(tmp_path):
    launcher = Launcher()
    server = launcher.server(cwd=tmp_path)
    assert server.ensure_started() == "starting"
    command, options = launcher.started[0]
    assert command == ["python", "api", "--aws-bridge"]
    assert options["cwd"] == str(tmp_path)
    assert options["stdin"] == subprocess.DEVNULL
    assert server.poll() == "starting"
    launcher.answers = True
    assert server.poll() == "running"
    assert server.bridge is True
    # Con el hijo en ejecución no se inicia un segundo proceso.
    assert server.ensure_started() == "running"
    assert len(launcher.started) == 1


def test_missing_aws_configuration_restarts_without_the_bridge():
    launcher = Launcher(processes=[FakeProcess(returncode=2), FakeProcess()])
    server = launcher.server()
    server.ensure_started()
    assert server.poll() == "starting"
    assert [command for command, _ in launcher.started] == [
        ["python", "api", "--aws-bridge"],
        ["python", "api"],
    ]
    launcher.answers = True
    assert server.poll() == "running"
    assert server.bridge is False


def test_other_start_failures_are_reported_without_retrying():
    launcher = Launcher(processes=[FakeProcess(returncode=1)])
    server = launcher.server()
    server.ensure_started()
    assert server.poll() == "failed"
    assert len(launcher.started) == 1


def test_process_creation_error_is_reported():
    def popen(command, **options):
        raise OSError("no se pudo crear")

    server = LocalApiProcess(popen=popen, probe=lambda: False, command=lambda bridge: ["x"])
    assert server.ensure_started() == "failed"


def test_unavailable_when_the_installation_cannot_launch_the_api():
    launcher = Launcher()
    server = launcher.server(command=lambda bridge: None)
    assert server.ensure_started() == "unavailable"
    assert launcher.started == []


def test_stop_terminates_the_child_once():
    process = FakeProcess()
    launcher = Launcher(processes=[process])
    server = launcher.server()
    server.ensure_started()
    server.stop()
    server.stop()
    assert process.calls == ["terminate", "wait"]
    assert server.state == "idle"


def test_stop_kills_a_child_that_does_not_exit():
    process = FakeProcess(hangs=True)
    launcher = Launcher(processes=[process])
    server = launcher.server()
    server.ensure_started()
    server.stop()
    assert process.calls == ["terminate", "wait", "kill", "wait"]


def test_child_output_goes_to_the_log_file_and_the_file_is_closed(tmp_path):
    launcher = Launcher()
    log = tmp_path / "logs" / "local-api.log"
    server = launcher.server(log_path=log)
    server.ensure_started()
    stream = launcher.started[0][1]["stdout"]
    assert log.is_file() and launcher.started[0][1]["stderr"] == subprocess.STDOUT
    server.stop()
    assert stream.closed


def test_command_uses_the_same_interpreter(monkeypatch, tmp_path):
    monkeypatch.setattr(local_server.importlib.util, "find_spec", lambda name: object())
    assert local_server.api_command(True) == [
        sys.executable,
        "-m",
        "pps_api",
        "serve",
        "--port",
        "8765",
        "--aws-bridge",
    ]
    assert "--aws-bridge" not in local_server.api_command(False)
    # Sin el paquete instalado se usa el lanzador del repositorio, si existe.
    monkeypatch.setattr(local_server.importlib.util, "find_spec", lambda name: None)
    launcher = tmp_path / "local-api" / "launch.py"
    launcher.parent.mkdir()
    launcher.write_text("")
    assert local_server.api_command(False, root=tmp_path)[:2] == [sys.executable, str(launcher)]
    assert local_server.api_command(False, root=None) is None
    # Una distribución compilada no tiene intérprete con el que iniciar la API.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert local_server.api_command(True, root=tmp_path) is None


class FakeServer:
    def __init__(self, states, bridge=True):
        self.states, self.bridge = list(states), bridge
        self.state = "idle"
        self.stopped = 0

    def _next(self):
        if len(self.states) > 1:
            self.state = self.states.pop(0)
        else:
            self.state = self.states[0]
        return self.state

    ensure_started = poll = _next

    def stop(self):
        self.stopped += 1


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_window(app, tmp_path, server, monkeypatch):
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    view = Window(demo_mode=True, settings=settings, local_server=server)
    connections = []
    monkeypatch.setattr(view, "_connect_local_now", lambda: connections.append(True))
    return view, connections


def test_window_connects_to_an_api_that_was_already_running(app, tmp_path, monkeypatch):
    server = FakeServer(["external"])
    view, connections = make_window(app, tmp_path, server, monkeypatch)
    view.connect_local()
    assert connections == [True]
    assert "ya estaba en ejecución" in view.local_server_status.text()
    view.close()
    assert server.stopped == 1


def test_window_waits_for_its_child_before_connecting(app, tmp_path, monkeypatch):
    server = FakeServer(["starting", "starting", "running"])
    view, connections = make_window(app, tmp_path, server, monkeypatch)
    view.connect_local()
    assert connections == [] and view.local_server_timer.isActive()
    assert "Iniciando" in view.local_server_status.text()
    view._poll_local_server()
    assert connections == []
    view._poll_local_server()
    assert connections == [True] and not view.local_server_timer.isActive()
    assert "iniciada por la aplicación" in view.local_server_status.text()
    view.close()
    assert server.stopped == 1


def test_window_reports_a_child_started_without_automatic_sending(app, tmp_path, monkeypatch):
    server = FakeServer(["starting", "running"], bridge=False)
    view, connections = make_window(app, tmp_path, server, monkeypatch)
    view.connect_local()
    view._poll_local_server()
    assert connections == [True]
    assert "sin envío automático" in view.local_server_status.text()
    view.close()


def test_window_reports_a_failed_start_and_gives_up_waiting(app, tmp_path, monkeypatch):
    server = FakeServer(["starting", "failed"])
    view, connections = make_window(app, tmp_path, server, monkeypatch)
    view.connect_local()
    view._poll_local_server()
    assert connections == [] and not view.local_server_timer.isActive()
    assert "no pudo iniciarse" in view.local_server_status.text()
    view.close()


def test_window_only_manages_the_default_local_address(app, tmp_path, monkeypatch):
    server = FakeServer(["starting"])
    view, connections = make_window(app, tmp_path, server, monkeypatch)
    view.local_api_url.setText("https://127.0.0.1:9443")
    view.connect_local()
    assert connections == [True] and server.state == "idle"
    view.close()


def test_notice_states_whether_automatic_sending_is_active(app, tmp_path, monkeypatch):
    view, _ = make_window(app, tmp_path, None, monkeypatch)
    view.snapshot["session"]["development"] = True
    view.online = True
    view.render()
    assert "requiere el comando de envío" in view.mode_notice.text()
    view.snapshot["session"]["capabilities"] = {"automatic_dispatch": True}
    view.render()
    assert "Envío automático a AWS activo" in view.mode_notice.text()
    view.close()
