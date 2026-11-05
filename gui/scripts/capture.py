"""Deterministic demo screenshots, no institutional data or network."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from pps_desktop.app import Window

root = Path(__file__).resolve().parents[1]
output = root / "docs"
output.mkdir(exist_ok=True)
app = QApplication([])
for font in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
    font_path = Path("C:/Windows/Fonts") / font
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
settings = QSettings(str(root / "build" / "capture.ini"), QSettings.Format.IniFormat)
window = Window(demo_mode=True, settings=settings)
window.resize(1510, 1150)
window.show()
app.processEvents()
window.grab().save(str(output / "resumen.png"))
window.navigation.setCurrentRow(3)
app.processEvents()
window.grab().save(str(output / "resultados.png"))
window.navigation.setCurrentRow(0)
window.resize(790, 850)
app.processEvents()
window.grab().save(str(output / "ventana-estrecha.png"))
window.close()
