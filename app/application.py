import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app.settings import SettingsError, load_settings, settings_path
from ui.window import MainWindow


def run() -> int:
    application = QApplication(sys.argv)
    try:
        settings = load_settings(settings_path())
    except SettingsError as error:
        QMessageBox.critical(None, "MiniFloat - Configuración", str(error))
        return 1
    window = MainWindow(
        always_on_top=settings.always_on_top,
        opacity=settings.opacity,
    )
    window.show()
    return application.exec()
