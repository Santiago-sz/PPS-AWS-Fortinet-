import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import pytest

from pps_desktop.app import Window


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    view = Window(demo_mode=True, settings=settings)
    view.show()
    app.processEvents()
    yield view
    view.close()
    app.processEvents()


def test_demo_has_real_computed_metrics_and_no_remote_writes(window):
    assert "DEMOSTRACIÓN" in window.mode_notice.text()
    assert window.current["counts"]["expected"] == 12
    assert window.coverage_bar.value() == 75
    assert "PARCIAL" in window.warning.text()
    assert window.dashboard_table.rowCount() == 3
    assert not window.upload_button.isEnabled()
    assert not window.reaudit_button.isEnabled()


def test_filter_results_and_keyboard_navigation(window, app):
    window.navigation.setFocus()
    QTest.keyClick(window.navigation, Qt.Key.Key_Down)
    assert window.pages.currentIndex() == 1
    window.navigation.setCurrentRow(3)
    window.result_status.setCurrentIndex(window.result_status.findData("fail"))
    assert window.result_table.rowCount() == 2
    window.result_search.setText("contraseñas")
    assert window.result_table.rowCount() == 1
    window.result_search.clear()
    window.result_status.setCurrentIndex(0)
    assert window.result_table.rowCount() == 12


def test_narrow_window_reflows_cards(window, app):
    window.resize(790, 720)
    app.processEvents()
    assert window.cards.getItemPosition(window.cards.indexOf(window.card_widgets[2]))[:2] == (2, 0)
    window.resize(1420, 960)
    app.processEvents()
    assert window.cards.getItemPosition(window.cards.indexOf(window.card_widgets[2]))[:2] == (0, 2)


def test_reader_and_offline_modes_block_mutations(window):
    window.client = object()
    window.online = True
    window.snapshot["session"]["role"] = "reader"
    window.update_permissions()
    assert not window.upload_button.isEnabled()
    window.snapshot["session"]["role"] = "analyst"
    window.update_permissions()
    assert window.upload_button.isEnabled()
    window.online = False
    window.update_permissions()
    assert not window.upload_button.isEnabled()


def test_empty_after_logout_has_no_false_success(window):
    window.sign_out()
    assert window.current is None
    assert "Sin datos" in window.mode_notice.text()
    assert window.dashboard_table.rowCount() == 0
    assert window.ratio.text() == "Sin datos suficientes"


def wait_task(window, app):
    import time

    deadline = time.monotonic() + 3
    while window.workers and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert not window.workers


def test_connection_loss_recovery_and_revocation(window, app):
    from copy import deepcopy
    from pps_desktop.api import ApiError

    remote = deepcopy(window.snapshot)
    remote["audits"][0]["status"] = "running"

    class Client:
        failure = True

        def snapshot(self):
            if self.failure:
                raise ApiError("Offline")
            return deepcopy(remote)

    client = Client()
    window.client, window.online, window.mode = client, True, "connected"
    window.refresh()
    wait_task(window, app)
    assert window.mode == "offline"
    assert "DATOS SIN ACTUALIZAR" in window.mode_notice.text()
    assert not window.upload_button.isEnabled()
    assert window.timer.isActive()

    client.failure = False
    window.refresh()
    wait_task(window, app)
    assert window.online
    assert window.mode == "connected"
    assert window.upload_button.isEnabled()
    window.timer.stop()

    def revoked():
        raise ApiError("Forbidden", "403")

    client.snapshot = revoked
    window.show_error = lambda exc: None
    window.refresh()
    wait_task(window, app)
    assert window.mode == "empty"
    assert window.snapshot["results"] == {}


def test_pending_audit_restored_from_encrypted_cache(window, app, tmp_path):
    from cryptography.fernet import Fernet
    from pps_desktop.storage import SecureCache

    window.mode = "connected"
    window.cache = SecureCache(tmp_path / "cache", "org|user", key=Fernet.generate_key())
    window.snapshot["audits"][0]["status"] = "running"
    window.save_cache()
    restored = Window(settings=QSettings(str(tmp_path / "second.ini"), QSettings.Format.IniFormat))
    restored.snapshot = window.cache.load()
    restored.mode = "offline"
    restored.render()
    assert restored.snapshot["audits"][0]["status"] == "running"
    assert "Sin evento confirmado" in [
        restored.timeline.item(i, 2).text() for i in range(restored.timeline.rowCount())
    ]
    assert not restored.upload_button.isEnabled()
    restored.close()


def test_late_worker_cannot_restore_data_after_logout(window, app):
    import time

    calls = []
    window.run_task(lambda: (time.sleep(0.05), "stale")[1], calls.append)
    window.sign_out()
    wait_task(window, app)
    assert calls == []
    assert window.mode == "empty"
