from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QWidget,
)

COLORS = {
    "pass": "#147d68",
    "fail": "#c3414b",
    "indeterminate": "#b57916",
    "not_applicable": "#6e7d91",
    "not_evaluated": "#b6bfcd",
    "anomaly": "#8b52b7",
}

STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 13px; color: #22334b; }
QMainWindow, QDialog { background: #f3f5f9; }
QWidget#page { background: #f3f5f9; }
QLabel { background: transparent; }
QFrame#sidebar { background: #D8E2ED; border: none; }
QFrame#sidebar QLabel { color: #17324D; }
QListWidget#navigation { background: transparent; border: none; color: #17324D; outline: 0; }
QListWidget#navigation::item { padding: 14px 12px; margin: 3px 0; border-radius: 7px; }
QListWidget#navigation::item:hover { background: #DCE7EF; }
QListWidget#navigation::item:selected { color: #17324D; background: #D2E8E3; border-left: 3px solid #00857D; }
QFrame#card { background: white; border: 1px solid #e0e6ef; border-radius: 10px; }
QLabel#eyebrow { font-size: 11px; font-weight: 700; color: #748399; }
QLabel#title { font-size: 25px; font-weight: 700; color: #172b44; }
QLabel#subtitle { color: #6d7d91; }
QLabel#cardTitle { font-size: 15px; font-weight: 600; }
QLabel#metric { font-size: 28px; font-weight: 700; }
QLabel#warning { background: #fff4df; border: 1px solid #ecd3a0; color: #815812;
                 padding: 12px; border-radius: 7px; }
QLabel#notice { background: #eaf2fb; color: #315d86; padding: 10px; border-radius: 7px; }
QPushButton { background: white; border: 1px solid #d4dce7; border-radius: 6px;
              padding: 8px 13px; font-weight: 600; }
QPushButton:hover { background: #edf3fa; border-color: #9aadc5; }
QPushButton:pressed { background: #e0e9f3; }
QPushButton#primary { background: #167965; color: white; border-color: #167965; }
QPushButton#primary:hover { background: #116553; }
QPushButton:disabled { background: #edf0f5; color: #98a3b2; border-color: #e1e5ec; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QTableWidget:focus,
QListWidget:focus, QPlainTextEdit:focus { border: 2px solid #268bcd; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QPlainTextEdit { background: white;
    border: 1px solid #d5deea; padding: 7px; border-radius: 5px; min-height: 20px; }
QComboBox::drop-down { border: none; width: 24px; }
QTableWidget { background: white; alternate-background-color: #f8fafc;
               border: none; gridline-color: #edf0f5; selection-background-color: #e0f0eb;
               selection-color: #173b32; }
QTableWidget::item { padding: 9px; border-bottom: 1px solid #edf0f5; }
QHeaderView::section { background: #f7f9fc; padding: 10px 9px; border: none;
                       border-bottom: 1px solid #e1e7f0; color: #728198; font-size: 11px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #eef1f6; width: 10px; }
QScrollBar::handle:vertical { background: #bcc8d6; min-height: 30px; border-radius: 5px; }
QProgressBar { border: none; background: #e8edf4; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #23957d; border-radius: 4px; }
QToolTip { background: #20364f; color: white; padding: 6px; border: none; }
"""


def label(text, name=None, wrap=False):
    widget = QLabel(str(text))
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.setAccessibleName(text.replace("&", ""))
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


def card(title=None):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    if title:
        layout.addWidget(label(title, "cardTitle"))
    return frame, layout


def row(*widgets):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(48)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.setMinimumHeight(190)
    return widget


def fill_table(widget, rows):
    widget.setSortingEnabled(False)
    widget.setRowCount(len(rows))
    for index, values in enumerate(rows):
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setData(Qt.ItemDataRole.UserRole, index)
            widget.setItem(index, col, item)


class Donut(QWidget):
    def __init__(self):
        super().__init__()
        self.counts = {}
        self.text = "—"
        self.setMinimumSize(170, 170)
        self.setMaximumHeight(190)

    def set_data(self, counts, text):
        self.counts, self.text = counts, text
        self.setAccessibleName("Cumplimiento observado " + text)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height()) - 30
        rect = QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size)
        painter.setPen(QPen(QColor("#e9edf3"), 14))
        painter.drawEllipse(rect)
        total = sum(self.counts.get(status, 0) for status in COLORS)
        angle = 90 * 16
        for status, color in COLORS.items():
            span = round(self.counts.get(status, 0) / total * 360 * 16) if total else 0
            painter.setPen(QPen(QColor(color), 14))
            painter.drawArc(rect, angle, -span)
            angle -= span
        painter.setPen(QColor("#172b44"))
        font = painter.font()
        font.setPointSize(25)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)
        painter.end()
