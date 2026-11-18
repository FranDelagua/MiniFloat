import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget


logger = logging.getLogger(__name__)


class TitleBar(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")

        title = QLabel("MiniFloat", self)
        title.setObjectName("title")

        minimize = QToolButton(self)
        minimize.setText("\u2212")
        minimize.setAccessibleName("Minimizar")
        minimize.setToolTip("Minimizar")
        minimize.clicked.connect(self.window().showMinimized)

        close = QToolButton(self)
        close.setText("\u00d7")
        close.setObjectName("closeButton")
        close.setAccessibleName("Cerrar")
        close.setToolTip("Cerrar")
        close.clicked.connect(self.window().close)
        self._control_buttons = (minimize, close)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 4, 4)
        layout.setSpacing(2)
        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(minimize)
        layout.addWidget(close)

    def set_interactive(self, enabled: bool) -> None:
        for button in self._control_buttons:
            button.setEnabled(enabled)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self.window().windowFlags() & Qt.WindowType.WindowTransparentForInput:
                event.accept()
                return
            handle = self.window().windowHandle()
            if handle is not None and not handle.startSystemMove():
                logger.warning("Windows could not start moving the window.")
            event.accept()
            return
        super().mousePressEvent(event)
