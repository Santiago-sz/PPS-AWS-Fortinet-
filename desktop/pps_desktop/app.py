import argparse
import json
from pathlib import Path
import sys
from urllib.parse import quote
import uuid

from PySide6.QtCore import Qt, QDate, QSettings, QStandardPaths, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QPixmap, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFrame,
    QListWidget,
    QStackedWidget,
    QScrollArea,
    QComboBox,
    QLineEdit,
    QDateEdit,
    QCheckBox,
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QDialog,
    QFormLayout,
    QPlainTextEdit,
    QSpinBox,
)

from . import api, demo
from .domain import (
    STATUSES,
    RUN_STATUSES,
    TERMINAL,
    PHASES,
    local_time,
    normalize,
    load_pair,
    inspect_policy,
    export_local,
    redact,
)
from .storage import SecureCache
from .widgets import COLORS, STYLE, Donut, label, button, card, row, table, fill_table


class Worker(QThread):
    success = Signal(object)
    failure = Signal(object)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.success.emit(self.operation())
        except Exception as exc:
            self.failure.emit(exc)


class UploadDialog(QDialog):
    def __init__(self, session, parent):
        super().__init__(parent)
        self.setWindowTitle("Cargar política e iniciar auditoría")
        self.resize(610, 610)
        self.setAcceptDrops(True)
        self.max_bytes = int(session.get("max_upload_bytes", 20 * 1048576))
        self.path = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(label("Nueva política", "title"))
        layout.addWidget(
            label(
                "La carga inicia automáticamente la generación y la evaluación.", "subtitle", True
            )
        )
        self.file_label = label(
            f"Arrastrá un PDF o DOCX · máximo {self.max_bytes / 1048576:g} MB", "notice", True
        )
        layout.addWidget(self.file_label)
        layout.addWidget(button("Seleccionar &archivo…", self.choose))
        form = QFormLayout()
        self.name, self.version, self.scope = QLineEdit(), QLineEdit(), QLineEdit()
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(80)
        self.device = QComboBox()
        for device in session.get("devices", []):
            self.device.addItem(device["name"], device["id"])
        for text, widget in [
            ("Nombre", self.name),
            ("Versión", self.version),
            ("Descripción", self.description),
            ("Alcance", self.scope),
            ("FortiGate objetivo", self.device),
        ]:
            widget.setAccessibleName(text)
            form.addRow(text, widget)
        layout.addLayout(form)
        layout.addWidget(
            label(
                "El texto de la política se envía a Claude para proponer controles. "
                "Las propuestas de IA no implican aprobación humana. AWS realiza "
                "la validación final del documento y consulta FortiGate.",
                "warning",
                True,
            )
        )
        self.consent = QCheckBox("Confirmo que el documento está autorizado para este tratamiento.")
        layout.addWidget(self.consent)
        self.error = label("", "subtitle", True)
        layout.addWidget(self.error)
        self.submit = button("Cargar e iniciar", self.validate, True)
        layout.addWidget(row(button("Cancelar", self.reject), self.submit))

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar política", "", "Políticas (*.pdf *.docx)"
        )
        if path:
            self.set_file(path)

    def set_file(self, path):
        self.path = path
        self.file_label.setText(Path(path).name)
        if not self.name.text():
            self.name.setText(Path(path).stem)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.set_file(urls[0].toLocalFile())

    def validate(self):
        if not self.path or not all(
            w.text().strip() for w in (self.name, self.version, self.scope)
        ):
            self.error.setText("Seleccioná un archivo y completá nombre, versión y alcance.")
            return
        if not self.device.currentData() or not self.consent.isChecked():
            self.error.setText("Seleccioná el dispositivo y confirmá el tratamiento del documento.")
            return
        self.accept()


class Window(QMainWindow):
    def __init__(self, demo_mode=False, settings=None):
        super().__init__()
        self.setWindowTitle("PostureGuard")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "FaviconPostureGuard.png")))
        self.resize(1420, 960)
        self.setMinimumSize(760, 650)
        self.settings = settings or QSettings("PPS", "Desktop")
        self.cache_root = (
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
            )
            / "cache"
        )
        self.cache = None
        self.client = None
        self.mode = "empty"
        self.online = False
        self.busy = False
        self.workers = set()
        self.generation = 0
        self.snapshot = {"session": {}, "policies": [], "audits": [], "results": {}}
        self.current = None
        self.backoff = 4000
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        self._build()
        if demo_mode:
            self.load_demo()
        else:
            self.restore_cache()
            self.render()
        QShortcut(QKeySequence("Ctrl+O"), self, self.import_report)
        QShortcut(QKeySequence("F5"), self, self.refresh)

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(17, 27, 17, 20)
        logo = label("")
        logo.setAccessibleName("PostureGuard")
        logo.setToolTip("PostureGuard")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedHeight(68)
        logo.setPixmap(
            QPixmap(str(Path(__file__).parent / "assets" / "LogoPostureGuard.png")).scaled(
                148,
                56,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        side.addWidget(logo)
        side.addSpacing(32)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setAccessibleName("Navegación principal")
        self.navigation.addItems(
            ["◫   Resumen", "▤   Políticas", "◎   Análisis", "≡   Resultados", "⚙   Configuración"]
        )
        self.navigation.currentRowChanged.connect(self.navigate)
        side.addWidget(self.navigation, 1)
        side.addWidget(label("AWS / FORTINET", "eyebrow"))
        side.addWidget(label("Evaluación de FortiGate\nSolo observación", wrap=True))
        side.addSpacing(15)
        side.addWidget(label("DESKTOP  /  0.1.0", "eyebrow"))
        shell.addWidget(sidebar)
        body = QVBoxLayout()
        body.setContentsMargins(26, 20, 26, 18)
        body.setSpacing(14)
        shell.addLayout(body, 1)
        self.header = label("PPS · Sin organización autenticada", "cardTitle", True)
        self.connection = label("Sin conexión", "subtitle")
        self.refresh_button = button("↻  Actualizar", self.refresh)
        self.refresh_button.setMaximumWidth(140)
        body.addWidget(row(self.header, self.connection, self.refresh_button))
        self.context = label("", "subtitle", True)
        body.addWidget(self.context)
        self.mode_notice = label("", "notice", True)
        body.addWidget(self.mode_notice)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        self._dashboard_page()
        self._policies_page()
        self._audits_page()
        self._results_page()
        self._settings_page()
        self.statusBar().showMessage("Listo")
        self.navigation.setCurrentRow(0)

    def page(self, title, subtitle):
        content = QWidget()
        content.setObjectName("page")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(16)
        layout.addWidget(label(title, "title"))
        layout.addWidget(label(subtitle, "subtitle", True))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.pages.addWidget(scroll)
        return layout

    def _dashboard_page(self):
        layout = self.page(
            "Postura de seguridad",
            "Una vista trazable de las políticas y la configuración de tu FortiGate.",
        )
        self.audit_filter = QComboBox()
        self.audit_filter.setAccessibleName("Política, versión y ejecución")
        self.audit_filter.setMinimumContentsLength(12)
        self.audit_filter.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.audit_filter.currentIndexChanged.connect(self.select_audit)
        self.device_filter = QComboBox()
        self.device_filter.setAccessibleName("Filtrar por dispositivo")
        self.device_filter.currentIndexChanged.connect(self.filter_audits)
        self.use_dates = QCheckBox("Fechas")
        self.use_dates.toggled.connect(self.filter_audits)
        self.from_date, self.to_date = QDateEdit(), QDateEdit()
        for date in (self.from_date, self.to_date):
            date.setDisplayFormat("dd/MM/yyyy")
            date.setCalendarPopup(True)
            date.setDate(QDate.currentDate())
        self.from_date.setAccessibleName("Desde")
        self.to_date.setAccessibleName("Hasta")
        self.from_date.setDate(QDate.currentDate().addMonths(-1))
        self.from_date.dateChanged.connect(self.filter_audits)
        self.to_date.dateChanged.connect(self.filter_audits)
        filters = QGridLayout()
        filters.addWidget(self.audit_filter, 0, 0, 1, 2)
        filters.addWidget(self.device_filter, 0, 2)
        filters.addWidget(button("Exportar…", self.export), 0, 3)
        filters.addWidget(self.use_dates, 1, 0)
        filters.addWidget(self.from_date, 1, 1)
        filters.addWidget(self.to_date, 1, 2)
        layout.addLayout(filters)
        self.warning = label("", "warning", True)
        layout.addWidget(self.warning)
        self.cards = QGridLayout()
        posture, box = card("Postura general")
        self.donut = Donut()
        box.addWidget(self.donut)
        self.ratio = label("Sin datos suficientes", "cardTitle", True)
        box.addWidget(self.ratio)
        self.legend = label("", "subtitle", True)
        box.addWidget(self.legend)
        self.metric_time = label("", "subtitle", True)
        box.addWidget(self.metric_time)
        sections, box = card("Resultados por sección")
        box.addWidget(label("Agrupación por cláusula de la política", "subtitle", True))
        self.sections = table(["SECCIÓN", "FALLOS", "COBERTURA"])
        self.sections.setColumnWidth(0, 175)
        self.sections.setColumnWidth(1, 60)
        box.addWidget(self.sections)
        device, box = card("Dispositivo evaluado")
        box.addWidget(label("◈", "metric"))
        self.device_name = label("Sin dispositivo", "cardTitle", True)
        self.device_info = label("", "subtitle", True)
        self.device_failures = label("—", "metric")
        box.addWidget(self.device_name)
        box.addWidget(self.device_info)
        box.addStretch()
        box.addWidget(self.device_failures)
        box.addWidget(label("controles fallidos / previstos", "subtitle"))
        self.card_widgets = [posture, sections, device]
        for i, widget in enumerate(self.card_widgets):
            self.cards.addWidget(widget, 0, i)
            self.cards.setColumnStretch(i, 1)
        layout.addLayout(self.cards)
        findings, box = card("Hallazgos que requieren atención")
        box.addWidget(
            label(
                "Fallidos, indeterminados y anomalías · seleccioná una fila para investigar.",
                "subtitle",
                True,
            )
        )
        self.dashboard_table = table(
            ["CONTROL", "RESULTADO", "DISPOSITIVO", "SECCIÓN", "TRAZABILIDAD"]
        )
        self.dashboard_table.setColumnWidth(0, 275)
        self.dashboard_table.setColumnWidth(1, 165)
        self.dashboard_table.setColumnWidth(2, 185)
        self.dashboard_table.setColumnWidth(3, 180)
        self.dashboard_table.cellDoubleClicked.connect(lambda *_: self.open_finding(True))
        box.addWidget(self.dashboard_table)
        box.addWidget(button("Ver evidencia y cláusula", lambda: self.open_finding(True)))
        layout.addWidget(findings)
        coverage, box = card("Cobertura de evaluación")
        self.coverage_text = label("Sin datos", "cardTitle", True)
        self.coverage_bar = QProgressBar()
        self.coverage_bar.setTextVisible(False)
        self.coverage_bar.setAccessibleName(
            "Cobertura de evaluación; no es progreso de la ejecución"
        )
        box.addWidget(self.coverage_text)
        box.addWidget(self.coverage_bar)
        self.exclusions = label("", "subtitle", True)
        box.addWidget(self.exclusions)
        layout.addWidget(coverage)
        self.provenance = label("", "subtitle", True)
        self.provenance.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.provenance)
        layout.addStretch()

    def _policies_page(self):
        layout = self.page(
            "Políticas de seguridad", "Documentos, versiones y controles propuestos por IA."
        )
        self.policy_search = QLineEdit()
        self.policy_search.setPlaceholderText("Buscar por nombre, versión o alcance…")
        self.policy_search.setAccessibleName("Buscar políticas")
        self.policy_search.textChanged.connect(self.render_policies)
        self.policy_status = QComboBox()
        self.policy_status.addItems(
            [
                "Todos los estados",
                "cargada",
                "procesando",
                "lista",
                "sin controles verificables",
                "error",
            ]
        )
        self.policy_status.setAccessibleName("Estado de la política")
        self.policy_status.currentIndexChanged.connect(self.render_policies)
        self.policy_device = QComboBox()
        self.policy_device.setAccessibleName("Dispositivo de la política")
        self.policy_device.currentIndexChanged.connect(self.render_policies)
        self.policy_use_dates = QCheckBox("Filtrar por fecha de carga")
        self.policy_from, self.policy_to = QDateEdit(), QDateEdit()
        for field in (self.policy_from, self.policy_to):
            field.setDisplayFormat("dd/MM/yyyy")
            field.setCalendarPopup(True)
            field.setDate(QDate.currentDate())
        self.policy_from.setDate(QDate.currentDate().addMonths(-1))
        self.policy_from.setAccessibleName("Políticas cargadas desde")
        self.policy_to.setAccessibleName("Políticas cargadas hasta")
        self.policy_use_dates.toggled.connect(self.render_policies)
        self.policy_from.dateChanged.connect(self.render_policies)
        self.policy_to.dateChanged.connect(self.render_policies)
        self.upload_button = button("+  Cargar e iniciar", self.upload, True)
        layout.addWidget(row(self.policy_search, self.policy_status))
        layout.addWidget(self.policy_device)
        layout.addWidget(row(self.policy_use_dates, self.policy_from, self.policy_to))
        layout.addWidget(
            row(self.upload_button, button("Abrir manifest + reporte…", self.import_report))
        )
        self.policy_table = table(
            ["POLÍTICA / VERSIÓN", "ESTADO", "ALCANCE", "CARGADOR", "FECHA", "CONTROLES"]
        )
        self.policy_table.setColumnWidth(0, 300)
        self.policy_table.setColumnWidth(1, 125)
        self.policy_table.setColumnWidth(2, 210)
        self.policy_table.setColumnWidth(3, 135)
        self.policy_table.setColumnWidth(4, 190)
        self.policy_table.cellDoubleClicked.connect(lambda *_: self.open_policy())
        layout.addWidget(self.policy_table)
        layout.addWidget(button("Ver política y controles", self.open_policy))
        layout.addWidget(
            label(
                "La carga inicia la auditoría. La aprobación humana previa requiere "
                "separar generación y ejecución en el servicio AWS.",
                "notice",
                True,
            )
        )
        layout.addStretch()

    def _audits_page(self):
        layout = self.page(
            "Análisis del sistema",
            "Fases confirmadas por el servicio. La consulta a FortiGate se realiza desde AWS.",
        )
        self.audit_table = table(["POLÍTICA / VERSIÓN", "DISPOSITIVO", "ESTADO", "INICIO"])
        self.audit_table.setColumnWidth(0, 300)
        self.audit_table.setColumnWidth(1, 210)
        self.audit_table.setColumnWidth(2, 210)
        self.audit_table.itemSelectionChanged.connect(self.render_timeline)
        layout.addWidget(self.audit_table)
        self.timeline_title = label("Seleccioná una ejecución", "cardTitle", True)
        layout.addWidget(self.timeline_title)
        self.timeline = table(["FASE", "HORA LOCAL", "DETALLE"])
        self.timeline.setColumnWidth(0, 215)
        self.timeline.setColumnWidth(1, 220)
        self.timeline.setMinimumHeight(370)
        layout.addWidget(self.timeline)
        self.audit_error = label("", "warning", True)
        layout.addWidget(self.audit_error)
        self.reaudit_button = button("Volver a analizar", self.reaudit)
        layout.addWidget(
            row(button("Abrir resultados", self.open_audit_result), self.reaudit_button)
        )
        layout.addWidget(
            label(
                "Sin porcentajes estimados: una fase sin evento permanece sin confirmar. "
                "Una invocación asíncrona no equivale a una auditoría finalizada.",
                "subtitle",
                True,
            )
        )
        layout.addStretch()

    def _results_page(self):
        layout = self.page(
            "Resultados y evidencias",
            "Cada resultado conserva su control, evidencia y referencia a la política.",
        )
        self.result_context = label(
            "Seleccioná una evaluación en Resumen o Análisis.", "notice", True
        )
        layout.addWidget(self.result_context)
        self.result_search = QLineEdit()
        self.result_search.setAccessibleName("Buscar controles")
        self.result_search.setPlaceholderText("Buscar control, requisito o evidencia…")
        self.result_search.textChanged.connect(self.render_findings)
        self.result_status = QComboBox()
        self.result_status.setAccessibleName("Resultado técnico")
        self.result_status.addItem("Todos los resultados", "")
        for code, text in STATUSES.items():
            self.result_status.addItem(text, code)
        self.result_status.currentIndexChanged.connect(self.render_findings)
        self.section_filter = QComboBox()
        self.section_filter.setAccessibleName("Sección de la política")
        self.section_filter.currentIndexChanged.connect(self.render_findings)
        layout.addWidget(row(self.result_search, self.result_status))
        layout.addWidget(self.section_filter)
        self.result_table = table(["CONTROL", "RESULTADO", "SECCIÓN", "EVIDENCIA", "REFERENCIA"])
        self.result_table.setColumnWidth(0, 280)
        self.result_table.setColumnWidth(1, 165)
        self.result_table.setColumnWidth(2, 200)
        self.result_table.setColumnWidth(3, 330)
        self.result_table.setMinimumHeight(350)
        self.result_table.cellDoubleClicked.connect(lambda *_: self.open_finding())
        layout.addWidget(self.result_table)
        layout.addWidget(
            row(
                button("Ver detalle del hallazgo", self.open_finding),
                button("Exportar…", self.export),
            )
        )
        self.anomaly_detail = QPlainTextEdit()
        self.anomaly_detail.setReadOnly(True)
        self.anomaly_detail.setAccessibleName("Anomalías y observaciones fuera del manifest")
        self.anomaly_detail.setMaximumHeight(160)
        layout.addWidget(self.anomaly_detail)
        layout.addWidget(
            label(
                "Los resultados técnicos son inmutables. El seguimiento humano se registra "
                "por separado. No se comparan tendencias de universos diferentes.",
                "subtitle",
                True,
            )
        )
        layout.addStretch()

    def _settings_page(self):
        layout = self.page(
            "Configuración", "Conectá tu organización mediante su servicio autenticado en AWS."
        )
        frame, box = card("Conexión institucional")
        box.addWidget(
            label(
                "La API y el proveedor de identidad deben estar desplegados. "
                "No ingreses claves AWS, tokens FortiGate ni credenciales de Claude.",
                "notice",
                True,
            )
        )
        form = QFormLayout()
        self.config_fields = {}
        for key, text, placeholder in [
            ("api_url", "URL del servicio", "https://api.institucion.edu"),
            ("issuer", "Emisor OIDC", "https://identidad.institucion.edu"),
            ("client_id", "Client ID público", "Identificador de aplicación de escritorio"),
            ("scope", "Scopes", "openid profile"),
            ("audience", "Audience (opcional)", "Identificador de la API"),
        ]:
            field = QLineEdit(
                str(self.settings.value(key, "openid profile" if key == "scope" else ""))
            )
            field.setPlaceholderText(placeholder)
            field.setAccessibleName(text)
            self.config_fields[key] = field
            form.addRow(text, field)
        box.addLayout(form)
        self.login_button = button("Iniciar sesión en el navegador", self.sign_in, True)
        box.addWidget(row(self.login_button, button("Cerrar sesión", self.sign_out)))
        layout.addWidget(frame)
        frame, box = card("Preferencias locales")
        self.font_size = QSpinBox()
        self.font_size.setRange(11, 19)
        self.font_size.setValue(int(self.settings.value("font_size", 13)))
        self.font_size.setAccessibleName("Tamaño de fuente")
        self.font_size.valueChanged.connect(self.change_font)
        box.addWidget(row(label("Tamaño de texto"), self.font_size))
        self.change_font(self.font_size.value())
        box.addWidget(
            label(
                "Caché cifrada: expira a las 24 horas. La clave permanece en el almacén "
                "seguro del sistema; si no está disponible, la caché se deshabilita. "
                "Los tokens de sesión solo permanecen en memoria.",
                "subtitle",
                True,
            )
        )
        box.addWidget(button("Borrar caché local", self.clear_cache))
        layout.addWidget(frame)
        frame, box = card("Explorar sin conexión")
        box.addWidget(
            label(
                "La demostración usa datos ficticios identificados. También podés abrir "
                "un manifest y su reporte JSON del pipeline actual.",
                "subtitle",
                True,
            )
        )
        box.addWidget(
            row(
                button("Abrir demostración", self.load_demo),
                button("Abrir reportes existentes…", self.import_report),
            )
        )
        layout.addWidget(frame)
        layout.addWidget(
            label(
                "Usuarios, conectores, retención y umbrales institucionales se administran "
                "en el servicio remoto. Esta versión no modifica infraestructura.",
                "subtitle",
                True,
            )
        )
        layout.addStretch()

    def navigate(self, index):
        self.pages.setCurrentIndex(index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "cards"):
            return
        columns = 3 if self.width() >= 1350 else (2 if self.width() >= 1050 else 1)
        for i, widget in enumerate(self.card_widgets):
            self.cards.removeWidget(widget)
            self.cards.addWidget(widget, i // columns, i % columns)
        for i in range(3):
            self.cards.setColumnStretch(i, 1 if i < columns else 0)

    def change_font(self, size):
        self.setStyleSheet(STYLE.replace("font-size: 13px", f"font-size: {size}px"))
        self.settings.setValue("font_size", size)

    def run_task(self, operation, success, failure=None):
        if self.busy:
            return
        self.busy = True
        self.update_permissions()
        generation = self.generation
        worker = Worker(operation, self)
        self.workers.add(worker)

        def done(value):
            if generation == self.generation:
                self.busy = False
                try:
                    success(value)
                except Exception as exc:
                    self.show_error(exc)
                self.update_permissions()

        def failed(exc):
            if generation == self.generation:
                self.busy = False
                (failure or self.show_error)(exc)
                self.update_permissions()

        worker.success.connect(done)
        worker.failure.connect(failed)
        worker.finished.connect(lambda: self.workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def show_error(self, exc):
        if isinstance(exc, (api.ApiError, ValueError)):
            message = str(exc)
        else:
            message = "No se pudo completar la operación. Revisá el archivo o la configuración del servicio."
        correlation = getattr(exc, "correlation_id", "")
        if correlation:
            message += "\nReferencia de soporte: " + correlation
        QMessageBox.warning(self, "PPS · Operación no completada", message)

    def reset_source(self):
        self.generation += 1
        self.timer.stop()
        self.client, self.cache = None, None
        self.busy, self.online = False, False
        self.current = None

    def load_demo(self):
        self.reset_source()
        self.mode = "demo"
        self.snapshot = demo.snapshot()
        self.render()
        self.navigation.setCurrentRow(0)

    def restore_cache(self):
        identity = self.settings.value("cache_identity", "")
        if not identity:
            return
        try:
            self.cache = SecureCache(self.cache_root, identity)
            cached = self.cache.load()
            if cached:
                self.snapshot = cached
                self.mode = "offline"
        except Exception:
            self.cache = None

    def save_cache(self):
        if self.cache and self.mode in {"connected", "offline"}:
            try:
                self.cache.save(redact(self.snapshot))
            except Exception:
                self.statusBar().showMessage(
                    "No se pudo guardar la caché cifrada; los datos siguen en memoria."
                )

    def clear_cache(self):
        try:
            SecureCache.clear_all(self.cache_root)
            self.settings.remove("cache_identity")
            if self.mode == "offline":
                self.sign_out()
            self.statusBar().showMessage("Caché local borrada.")
        except OSError as exc:
            self.show_error(exc)

    def sign_out(self):
        self.clear_session_cache()
        self.reset_source()
        self.mode = "empty"
        self.snapshot = {"session": {}, "policies": [], "audits": [], "results": {}}
        self.render()

    def clear_session_cache(self):
        if self.cache:
            self.cache.clear()
        self.settings.remove("cache_identity")

    def sign_in(self):
        config = {key: field.text().strip() for key, field in self.config_fields.items()}
        try:
            api.https_url(config["api_url"])
            api.https_url(config["issuer"])
            if not config["client_id"]:
                raise ValueError("Ingresá el Client ID público de la aplicación.")
        except ValueError as exc:
            self.show_error(exc)
            return
        for key, value in config.items():
            self.settings.setValue(key, value)
        self.statusBar().showMessage(
            "Completá el inicio de sesión en el navegador (máximo 2 minutos)."
        )

        def operation():
            client = api.login(config)
            return client, client.snapshot()

        def connected(value):
            client, snapshot = value
            self.reset_source()
            self.client, self.snapshot, self.online, self.mode = client, snapshot, True, "connected"
            session = snapshot["session"]
            identity = "|".join(
                [config["api_url"], session["organization"]["id"], session["user"]["id"]]
            )
            try:
                self.cache = SecureCache(self.cache_root, identity)
                self.settings.setValue("cache_identity", identity)
            except Exception:
                self.statusBar().showMessage(
                    "Sesión iniciada. Caché deshabilitada: almacén seguro no disponible."
                )
            self.save_cache()
            self.render()
            self.schedule_poll()

        self.run_task(operation, connected)

    def refresh(self):
        if self.busy or not self.client:
            return
        client = self.client
        old_identity = (
            self.snapshot["session"]["organization"]["id"],
            self.snapshot["session"]["user"]["id"],
        )
        results = dict(self.snapshot["results"])
        selected = self.audit_filter.currentData()

        def operation():
            snapshot = client.snapshot()
            identity = snapshot["session"]["organization"]["id"], snapshot["session"]["user"]["id"]
            if identity != old_identity:
                raise api.ApiError("La identidad cambió. Iniciá sesión nuevamente.", "401")
            authorized = {audit["id"] for audit in snapshot["audits"]}
            snapshot["results"] = {
                key: value for key, value in results.items() if key in authorized
            }
            for audit in snapshot["audits"]:
                if audit["status"] in TERMINAL and (
                    audit["id"] == selected or audit["id"] not in results
                ):
                    payload = client.results(audit["id"])
                    snapshot["results"][audit["id"]] = self.remote_result(payload, audit)
            return snapshot

        def success(snapshot):
            self.snapshot, self.online, self.mode, self.backoff = snapshot, True, "connected", 4000
            self.save_cache()
            self.render()
            self.statusBar().showMessage("Datos actualizados desde el servicio.")
            self.schedule_poll()

        def failure(exc):
            self.online, self.mode = False, "offline"
            self.backoff = min(self.backoff * 2, 60000)
            if getattr(exc, "code", "") in {"401", "403", "404"}:
                self.sign_out()
                self.show_error(exc)
            else:
                self.render()
                self.statusBar().showMessage(
                    "Sin conexión o servicio no disponible. Reintento automático con espera progresiva."
                )
                self.timer.start(self.backoff)

        self.run_task(operation, success, failure)

    @staticmethod
    def remote_result(payload, audit):
        return normalize(
            payload["manifest"],
            payload["report"],
            {
                "audit_id": audit["id"],
                "source": "remote",
                "device": audit.get("device", {}),
                "policy_name": audit.get("policy_name", "Política"),
                "policy_version": audit.get("policy_version", "Sin versión"),
                "policy_version_id": audit["policy_version_id"],
            },
        )

    def schedule_poll(self):
        if self.client and any(a["status"] not in TERMINAL for a in self.snapshot["audits"]):
            self.timer.start(self.backoff)

    def update_permissions(self):
        session = self.snapshot["session"]
        writable = session.get("role") in {"admin", "analyst"} and self.online and bool(self.client)
        self.upload_button.setEnabled(writable and not self.busy)
        self.upload_button.setToolTip(
            "Requiere una sesión de analista o administrador y conexión al servicio AWS."
        )
        self.reaudit_button.setEnabled(
            writable and not self.busy and session.get("capabilities", {}).get("reaudit", False)
        )
        self.reaudit_button.setToolTip(
            "Disponible solo si el servicio declara un disparador de reanálisis."
        )
        self.refresh_button.setEnabled(bool(self.client) and not self.busy)
        self.login_button.setEnabled(not self.busy)

    def render(self):
        session = self.snapshot["session"]
        organization = session.get("organization", {}).get("name", "Sin organización autenticada")
        user = session.get("user", {}).get("name", "Sesión local")
        roles = {"analyst": "Analista", "reader": "Lector / auditor", "admin": "Administrador"}
        self.header.setText(organization + "  /  " + session.get("environment", "LOCAL"))
        self.context.setText(
            f"{user} · {roles.get(session.get('role'), 'Solo lectura local')} · Hora local del equipo"
        )
        self.connection.setText("●  API conectada" if self.online else "○  Sin conexión a AWS")
        notices = {
            "demo": "DEMOSTRACIÓN · Datos ficticios. No hay conexión a AWS ni auditorías reales.",
            "import": "ARCHIVOS LOCALES · Reporte importado; identidad, dispositivo y permisos remotos no verificados.",
            "empty": "Sin datos · Iniciá sesión desde Configuración, abrí un reporte existente o explorá la demostración.",
            "offline": "DATOS SIN ACTUALIZAR · Vista local en caché. Carga, evaluación y seguimiento deshabilitados.",
            "connected": "Fuente: servicio AWS · Las métricas se vinculan a una política, versión y ejecución.",
        }
        self.mode_notice.setText(notices[self.mode])
        previous_device = self.device_filter.currentData()
        self.device_filter.blockSignals(True)
        self.device_filter.clear()
        self.device_filter.addItem("Todos los dispositivos", "")
        devices = {
            a.get("device", {}).get("id"): a.get("device", {}) for a in self.snapshot["audits"]
        }
        for did, device in devices.items():
            if did:
                self.device_filter.addItem(device["name"], did)
        index = self.device_filter.findData(previous_device)
        self.device_filter.setCurrentIndex(max(index, 0))
        self.device_filter.blockSignals(False)
        previous_policy_device = self.policy_device.currentData()
        self.policy_device.blockSignals(True)
        self.policy_device.clear()
        self.policy_device.addItem("Todos los dispositivos", "")
        for device in session.get("devices", []):
            self.policy_device.addItem(device["name"], device["id"])
        self.policy_device.setCurrentIndex(
            max(0, self.policy_device.findData(previous_policy_device))
        )
        self.policy_device.blockSignals(False)
        self.filter_audits()
        self.render_policies()
        selected_row = self.audit_table.currentRow()
        fill_table(
            self.audit_table,
            [
                [
                    a.get("policy_name", "Política") + " · " + a.get("policy_version", ""),
                    a.get("device", {}).get("name", "No informado"),
                    RUN_STATUSES.get(a["status"], a["status"]),
                    local_time(a.get("started_at")),
                ]
                for a in self.snapshot["audits"]
            ],
        )
        if self.snapshot["audits"]:
            self.audit_table.selectRow(max(0, min(selected_row, len(self.snapshot["audits"]) - 1)))
        else:
            self.render_timeline()
        self.update_permissions()

    def filter_audits(self, *_):
        previous = self.audit_filter.currentData()
        self.audit_filter.blockSignals(True)
        self.audit_filter.clear()
        did = self.device_filter.currentData()
        for audit in self.snapshot["audits"]:
            if did and audit.get("device", {}).get("id") != did:
                continue
            if self.use_dates.isChecked():
                timestamp = local_time(audit.get("finished_at") or audit.get("started_at"))[:10]
                day = QDate.fromString(timestamp, "dd/MM/yyyy")
                if not day.isValid() or not self.from_date.date() <= day <= self.to_date.date():
                    continue
            title = f"{audit.get('policy_name', 'Política')} · v{audit.get('policy_version', '—')} · {audit['id']}"
            self.audit_filter.addItem(title, audit["id"])
        index = self.audit_filter.findData(previous)
        self.audit_filter.setCurrentIndex(max(0, index))
        self.audit_filter.blockSignals(False)
        self.select_audit()

    def select_audit(self, *_):
        aid = self.audit_filter.currentData()
        self.current = self.snapshot["results"].get(aid)
        self.render_dashboard()
        self.section_filter.blockSignals(True)
        self.section_filter.clear()
        self.section_filter.addItem("Todas las secciones", "")
        for name in (self.current or {}).get("groups", {}):
            self.section_filter.addItem(name, name)
        self.section_filter.blockSignals(False)
        self.render_findings()
        if self.client and self.online and not self.busy and aid and not self.current:
            audit = next(a for a in self.snapshot["audits"] if a["id"] == aid)
            if audit["status"] in TERMINAL:
                client = self.client

                def done(payload):
                    self.snapshot["results"][aid] = self.remote_result(payload, audit)
                    self.save_cache()
                    if self.audit_filter.currentData() == aid:
                        self.select_audit()

                self.run_task(lambda: client.results(aid), done)

    def render_dashboard(self):
        result = self.current or {}
        session = self.snapshot["session"]
        user = session.get("user", {}).get("name", "Sesión local")
        role = {"analyst": "Analista", "reader": "Lector / auditor", "admin": "Administrador"}.get(
            session.get("role"), "Solo lectura local"
        )
        self.context.setText(
            f"{user} · {role} · {result.get('device', {}).get('name', 'Sin dispositivo')}\n"
            f"Último reporte: {local_time(result.get('timestamp'))}"
        )
        counts = result.get("counts", {})
        coverage, compliance = result.get("coverage_percent"), result.get("compliance_percent")
        pct = f"{compliance:.1f}%" if compliance is not None else "—"
        self.donut.set_data(counts, pct)
        self.ratio.setText(
            f"{counts.get('pass', 0)} / {counts.get('pass', 0) + counts.get('fail', 0)} aplicables aprobados"
            if compliance is not None
            else "Sin datos suficientes"
        )
        self.legend.setText(
            "   ·   ".join(f"{counts.get(s, 0)} {STATUSES[s].lower()}" for s in STATUSES)
        )
        self.metric_time.setText("Cumplimiento observado\n" + local_time(result.get("timestamp")))
        text = ""
        if not result:
            text = "Sin resultados disponibles. Seleccioná una evaluación finalizada o abrí una demostración."
        elif result.get("partial"):
            text = (
                "PARCIAL / NO CONFIABLE COMO POSTURA TOTAL · "
                + RUN_STATUSES.get(result.get("status"), result.get("status", ""))
                + ". "
                + result.get("failure_reason", "")
                + " No se interpreta como conformidad del sistema."
            )
        elif not counts.get("expected"):
            text = "Sin datos suficientes: el manifest no contiene controles previstos."
        self.warning.setText(text)
        self.warning.setVisible(bool(text))
        groups = []
        for name, values in result.get("groups", {}).items():
            expected = sum(values.values())
            evaluated = sum(
                values.get(s, 0) for s in ("pass", "fail", "indeterminate", "not_applicable")
            )
            groups.append([name, values.get("fail", 0), f"{evaluated}/{expected}"])
        fill_table(self.sections, groups)
        device = result.get("device", {})
        self.device_name.setText(device.get("name", "No informado"))
        self.device_info.setText(
            "FortiGate\nConector AWS → FortiGate: "
            + device.get("connector_status", "Sin sondeo informado")
            + "\nÚltimo sondeo: "
            + local_time(device.get("last_checked_at"))
        )
        self.device_failures.setText(f"{counts.get('fail', 0)} / {counts.get('expected', 0)}")
        self.dashboard_rows = [
            r for r in result.get("rows", []) if r["status"] in {"fail", "indeterminate", "anomaly"}
        ]
        fill_table(
            self.dashboard_table,
            [
                [
                    r["check_id"] + " · " + r["title"],
                    STATUSES[r["status"]],
                    device.get("name", "No informado"),
                    r["section"],
                    "Verificable" if r["traceable"] else "Sin referencia verificable",
                ]
                for r in self.dashboard_rows
            ],
        )
        self.color_results(self.dashboard_table, self.dashboard_rows)
        self.coverage_bar.setValue(round(coverage or 0))
        self.coverage_text.setText(
            f"{counts.get('evaluated', 0)} / {counts.get('expected', 0)} controles evaluados"
            + (f" · {coverage:.1f}%" if coverage is not None else " · Sin datos")
        )
        self.exclusions.setText(
            f"Excluidos del cumplimiento: {counts.get('not_applicable', 0)} no aplicables, "
            f"{counts.get('indeterminate', 0)} indeterminados, {counts.get('not_evaluated', 0)} no evaluados "
            f"y {counts.get('anomaly', 0)} anomalías.\nReporte: {local_time(result.get('timestamp'))}"
        )
        self.provenance.setText(
            f"RUN  {result.get('run_id', '—')}   ·   VERSIÓN  {result.get('policy_version', '—')}\n"
            "Alcance: configuración de FortiGate consultada por el pipeline; no es un inventario AWS."
        )

    @staticmethod
    def color_results(widget, rows):
        from PySide6.QtGui import QColor

        for i, data in enumerate(rows):
            widget.item(i, 1).setForeground(QColor(COLORS[data["status"]]))

    def render_policies(self, *_):
        search, status = self.policy_search.text().casefold(), self.policy_status.currentText()
        device = self.policy_device.currentData()

        def in_date_range(policy):
            if not self.policy_use_dates.isChecked():
                return True
            day = QDate.fromString(local_time(policy.get("uploaded_at"))[:10], "dd/MM/yyyy")
            return day.isValid() and self.policy_from.date() <= day <= self.policy_to.date()

        self.policy_rows = [
            p
            for p in self.snapshot["policies"]
            if (status == "Todos los estados" or p.get("status") == status)
            and (not device or p.get("device_id") == device)
            and in_date_range(p)
            and search
            in " ".join(str(p.get(k, "")) for k in ("name", "version_label", "scope")).casefold()
        ]
        fill_table(
            self.policy_table,
            [
                [
                    p["name"] + " · v" + p.get("version_label", "—"),
                    p.get("status", "—"),
                    p.get("scope", "—"),
                    p.get("uploaded_by", "—"),
                    local_time(p.get("uploaded_at")),
                    p.get("check_count", len(p.get("checks", []))),
                ]
                for p in self.policy_rows
            ],
        )

    def render_findings(self, *_):
        result = self.current or {}
        search, status, section = (
            self.result_search.text().casefold(),
            self.result_status.currentData(),
            self.section_filter.currentData(),
        )
        self.result_rows = [
            r
            for r in result.get("rows", [])
            if (not status or r["status"] == status)
            and (not section or r["section"] == section)
            and search in (r["check_id"] + " " + r["title"] + " " + str(r["evidence"])).casefold()
        ]
        fill_table(
            self.result_table,
            [
                [
                    r["check_id"] + " · " + r["title"],
                    STATUSES[r["status"]],
                    r["section"],
                    r["evidence"],
                    "Verificable" if r["traceable"] else "Sin referencia verificable",
                ]
                for r in self.result_rows
            ],
        )
        self.color_results(self.result_table, self.result_rows)
        self.result_context.setText(
            f"{result.get('policy_name', 'Sin evaluación seleccionada')} · "
            f"v{result.get('policy_version', '—')} · {result.get('run_id', '—')} · "
            f"{local_time(result.get('timestamp'))}"
        )
        anomalous = bool(result.get("anomalies"))
        self.anomaly_detail.setVisible(anomalous)
        self.anomaly_detail.setPlainText(
            "\n".join(result.get("anomalies", []))
            + "\n"
            + json.dumps(result.get("unknown_findings", []), ensure_ascii=False, indent=2)
        )

    def render_timeline(self):
        index = self.audit_table.currentRow()
        if not 0 <= index < len(self.snapshot["audits"]):
            fill_table(self.timeline, [])
            self.timeline_title.setText("Sin ejecuciones")
            self.audit_error.hide()
            return
        audit = self.snapshot["audits"][index]
        self.timeline_title.setText(
            f"{audit['id']} · {RUN_STATUSES.get(audit['status'], audit['status'])}"
        )
        events = audit.get("events", [])
        rows = [
            [
                e.get("phase", ""),
                local_time(e.get("timestamp")),
                e.get("message", "Evento confirmado"),
            ]
            for e in events
        ]
        confirmed = {e.get("phase") for e in events}
        rows.extend(
            [phase, "—", "Sin evento confirmado"] for phase in PHASES if phase not in confirmed
        )
        fill_table(self.timeline, rows)
        self.audit_error.setText(str(redact(audit.get("failure_reason", ""))))
        self.audit_error.setVisible(bool(audit.get("failure_reason")))

    def open_audit_result(self):
        index = self.audit_table.currentRow()
        if 0 <= index < len(self.snapshot["audits"]):
            aid = self.snapshot["audits"][index]["id"]
            self.device_filter.setCurrentIndex(0)
            self.use_dates.setChecked(False)
            self.audit_filter.setCurrentIndex(self.audit_filter.findData(aid))
            self.navigation.setCurrentRow(3)

    def text_dialog(self, title, content):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(760, 600)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(title, "cardTitle", True))
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(content)
        layout.addWidget(text)
        layout.addWidget(button("Cerrar", dialog.accept))
        return dialog, layout

    def open_policy(self):
        index = self.policy_table.currentRow()
        if not 0 <= index < len(self.policy_rows):
            return
        policy = self.policy_rows[index]

        def display(data):
            lines = [
                str(data.get("name", "Política")),
                "",
                "Versión: " + str(data.get("version_label", "No informada")),
                "Descripción: " + str(data.get("description", "—")),
                "Alcance: " + str(data.get("scope", "—")),
                "Cargador: " + str(data.get("uploaded_by", "—")),
                "Fecha: " + local_time(data.get("uploaded_at")),
                "Formato: " + str(data.get("mime_type", "—")),
                "Tamaño: " + str(data.get("size", "—")) + " bytes",
                "SHA-256: " + str(data.get("sha256", "—")),
                "Revisión: " + str(data.get("review_status", "Sin aprobación informada")),
                "",
                "CONTROLES PROPUESTOS POR IA",
                "No equivalen a aprobación humana.",
            ]
            for check in data.get("checks", []):
                ref = check.get("clause_ref") or {}
                lines.extend(
                    [
                        "",
                        f"{check.get('check_id')} · {check.get('title', '')}",
                        "Criterio: " + str(check.get("intent", "No informado")),
                        "Endpoints: " + ", ".join(check.get("endpoints", [])),
                        "Cláusula propuesta: " + str(ref.get("quote", "Sin referencia")),
                        "Página: " + str(ref.get("page", "No informada")),
                    ]
                )
            if data.get("versions"):
                lines.extend(
                    ["", "VERSIONES", json.dumps(data["versions"], ensure_ascii=False, indent=2)]
                )
            if data.get("preview_text"):
                lines.extend(["", "VISTA PREVIA DEL DOCUMENTO (TEXTO)", data["preview_text"]])
            else:
                lines.extend(["", "El servicio no proporcionó una vista previa del documento."])
            dialog, layout = self.text_dialog(
                "Política · versiones y controles propuestos", redact("\n".join(lines))
            )
            if self.online and self.client and data.get("original_download_available"):
                download = button(
                    "Guardar documento original…", lambda: self.download_original(data)
                )
                layout.insertWidget(2, download)
            dialog.exec()

        if self.online and self.client:
            client = self.client
            self.run_task(
                lambda: client.call("/api/policies/" + quote(policy["id"], safe="")), display
            )
        else:
            display(policy)

    def download_original(self, policy):
        if not self.client or not self.online:
            return
        extension = "pdf" if policy.get("mime_type") == "application/pdf" else "docx"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar documento institucional sensible",
            "politica." + extension,
            f"Documento (*.{extension})",
        )
        if not path:
            return
        if (
            QMessageBox.question(
                self,
                "Documento sensible",
                "Se guardará el documento original en:\n" + path + "\n¿Continuar?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        pid, vid = quote(policy["id"], safe=""), quote(policy["version_id"], safe="")
        client = self.client
        self.run_task(
            lambda: client.call(f"/api/policies/{pid}/versions/{vid}/document", raw=True),
            lambda data: Path(path).write_bytes(data),
        )

    def open_finding(self, dashboard=False):
        widget, rows = (
            (self.dashboard_table, self.dashboard_rows)
            if dashboard
            else (self.result_table, self.result_rows)
        )
        index = widget.currentRow()
        if not 0 <= index < len(rows) or not self.current:
            return
        finding, result = rows[index], self.current
        clause = finding["clause_ref"] if finding["traceable"] else "Sin referencia verificable"
        content = [
            "RESULTADO TÉCNICO · " + STATUSES[finding["status"]],
            "",
            "REQUISITO",
            finding["title"],
            "",
            "CRITERIO",
            str(finding["intent"]),
            "",
            "EVIDENCIA",
            str(finding["evidence"]),
            "",
            "CLÁUSULA DE LA POLÍTICA",
        ]
        if isinstance(clause, dict):
            content.extend(
                [
                    str(clause.get("quote", "")),
                    "Página: " + str(clause.get("page", "No informada")),
                    "Sección: " + finding["section"],
                ]
            )
        else:
            content.append(clause)
        content.extend(
            [
                "",
                "PROCEDENCIA",
                "Endpoints consultados: " + ", ".join(finding["endpoints_used"]),
                "Endpoints previstos: " + ", ".join(finding["expected_endpoints"]),
                "Hash SHA-256: " + str(result.get("policy_sha256", "No informado")),
                "Dispositivo: " + result.get("device", {}).get("name", "No informado"),
                "run_id: " + result["run_id"],
                "Hora local: " + local_time(result.get("timestamp")),
            ]
        )
        if finding["status"] == "anomaly":
            content.extend(
                [
                    "",
                    "ENTRADAS CONSERVADAS PARA INVESTIGACIÓN",
                    json.dumps(
                        {
                            "observations": finding["observations"],
                            "definitions": finding["definitions"],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                ]
            )
        dialog, layout = self.text_dialog(
            finding["check_id"] + " · " + finding["title"], redact("\n".join(content))
        )
        form = QFormLayout()
        owner, comment, state = QLineEdit(), QLineEdit(), QComboBox()
        state.addItems(["nuevo", "en revisión", "aceptado", "resuelto"])
        follow_up = finding.get("follow_up") or {}
        owner.setText(follow_up.get("owner_id", ""))
        comment.setText(follow_up.get("comment", ""))
        state.setCurrentText(follow_up.get("status", "nuevo"))
        for title, field in [
            ("Responsable (ID)", owner),
            ("Comentario", comment),
            ("Seguimiento humano", state),
        ]:
            field.setAccessibleName(title)
            form.addRow(title, field)
        layout.insertLayout(2, form)

        def save():
            if not self.client or not self.online:
                return
            client = self.client
            payload = {
                "owner_id": owner.text().strip(),
                "comment": comment.text().strip(),
                "status": state.currentText(),
            }
            fid = quote(finding["finding_id"], safe="")
            self.run_task(
                lambda: client.call(f"/api/findings/{fid}/follow-up", "PATCH", payload),
                lambda _: (dialog.accept(), self.refresh()),
            )

        save_button = button("Guardar seguimiento", save)
        enabled = (
            bool(finding.get("finding_id"))
            and self.online
            and self.client is not None
            and self.snapshot["session"].get("role") in {"admin", "analyst"}
            and self.snapshot["session"].get("capabilities", {}).get("follow_up", False)
        )
        save_button.setEnabled(enabled)
        for field in (owner, comment, state):
            field.setEnabled(enabled)
        layout.insertWidget(3, save_button)
        if not enabled:
            layout.insertWidget(
                4,
                label(
                    "El seguimiento requiere autorización y soporte del servicio remoto.",
                    "subtitle",
                    True,
                ),
            )
        dialog.exec()

    def import_report(self):
        manifest, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar manifest.json", "", "JSON (*.json)"
        )
        if not manifest:
            return
        report, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar report.json de la misma ejecución",
            str(Path(manifest).parent),
            "JSON (*.json)",
        )
        if not report:
            return
        try:
            result = load_pair(manifest, report)
        except (ValueError, OSError) as exc:
            self.show_error(exc)
            return
        self.reset_source()
        self.mode = "import"
        aid = result["run_id"]
        self.snapshot = {
            "session": {},
            "policies": [],
            "results": {aid: result},
            "audits": [
                {
                    "id": aid,
                    "run_id": aid,
                    "policy_name": "Reporte importado",
                    "policy_version": "No informada",
                    "status": result["status"],
                    "device": result["device"],
                    "started_at": result.get("timestamp"),
                    "finished_at": result.get("timestamp"),
                    "events": [],
                    "failure_reason": result.get("failure_reason", ""),
                }
            ],
        }
        self.render()
        self.navigation.setCurrentRow(0)

    def upload(self):
        if (
            not self.online
            or not self.client
            or self.snapshot["session"].get("role") not in {"admin", "analyst"}
        ):
            return
        dialog = UploadDialog(self.snapshot["session"], self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        metadata = {
            "name": dialog.name.text().strip(),
            "version_label": dialog.version.text().strip(),
            "scope": dialog.scope.text().strip(),
            "description": dialog.description.toPlainText().strip(),
            "device_id": dialog.device.currentData(),
        }
        # A stable key for the entire transaction, including completion. The server
        # must expire abandoned uploads and reconcile S3 events with this record.
        key = str(uuid.uuid4())
        client = self.client

        def operation():
            document = inspect_policy(dialog.path, dialog.max_bytes)
            data = document.pop("data")
            return client.upload({**metadata, **document}, data, key)

        def success(created):
            self.statusBar().showMessage(
                "Documento recibido. Auditoría pendiente: " + created["audit_id"]
            )
            self.navigation.setCurrentRow(2)
            self.refresh()

        def failure(exc):
            self.show_error(exc)
            self.statusBar().showMessage(
                "Verificá Análisis antes de volver a cargar: AWS pudo haber recibido el documento."
            )
            self.refresh()

        self.run_task(operation, success, failure)

    def reaudit(self):
        index = self.audit_table.currentRow()
        if (
            not self.reaudit_button.isEnabled()
            or not self.client
            or not 0 <= index < len(self.snapshot["audits"])
        ):
            return
        audit = self.snapshot["audits"][index]
        client = self.client
        key = str(uuid.uuid4())
        self.run_task(
            lambda: client.call(
                "/api/audits",
                "POST",
                {
                    "policy_version_id": audit["policy_version_id"],
                    "device_id": audit["device"]["id"],
                },
                key,
            ),
            lambda _: self.refresh(),
        )

    def export(self):
        if not self.current:
            self.show_error(ValueError("Seleccioná una evaluación con resultados."))
            return
        path, selected = QFileDialog.getSaveFileName(
            self,
            "Exportar reporte · archivo sensible",
            "pps-reporte.json",
            "JSON (*.json);;Markdown (*.md)",
        )
        if not path:
            return
        fmt = "md" if "Markdown" in selected else "json"
        if (
            QMessageBox.question(
                self,
                "Guardar archivo sensible",
                "El reporte puede contener información institucional.\n"
                "Destino: " + path + "\n\n¿Guardar en este destino?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        result, client = self.current, self.client

        def write(data):
            try:
                Path(path).write_bytes(data)
                self.statusBar().showMessage("Reporte exportado a " + path)
            except OSError as exc:
                self.show_error(exc)

        if self.online and client and result.get("source") == "remote":
            aid = quote(result["audit_id"], safe="")
            self.run_task(
                lambda: client.call(f"/api/audits/{aid}/export?format={fmt}", raw=True), write
            )
        else:
            # Offline cache and imported reports are never silently exported as
            # newly authorized remote artifacts.
            copy = {
                **result,
                "export_note": "Vista local; permisos remotos no revalidados.",
                "source": "demo" if self.mode == "demo" else "local",
            }
            write(export_local(copy, fmt))

    def closeEvent(self, event):
        if any(worker.isRunning() for worker in self.workers):
            self.statusBar().showMessage(
                "Esperá a que termine la operación activa antes de cerrar."
            )
            event.ignore()
            return
        self.timer.stop()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="PPS · consola de auditoría FortiGate")
    parser.add_argument("--demo", action="store_true", help="Abrir datos ficticios sin red")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("PPS Desktop")
    app.setOrganizationName("PPS")
    app.setFont(QFont("Segoe UI", 10))
    temporary = None
    preferences = None
    if args.smoke_test:
        import tempfile

        temporary = tempfile.TemporaryDirectory(prefix="pps-smoke-")
        preferences = QSettings(
            str(Path(temporary.name) / "settings.ini"), QSettings.Format.IniFormat
        )
    window = Window(demo_mode=args.demo or args.smoke_test, settings=preferences)
    window.show()
    if args.smoke_test:
        assert window.current["counts"]["expected"] == 12
        assert window.coverage_bar.value() == 75
        assert not window.upload_button.isEnabled()
        QTimer.singleShot(300, app.quit)
    status = app.exec()
    if temporary:
        preferences.sync()
        temporary.cleanup()
    sys.exit(status)
