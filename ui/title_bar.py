import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QToolButton, QWidget


logger = logging.getLogger(__name__)


class TitleBar(QWidget):
    opacity_changed = Signal(int)

    def __init__(self, parent: QWidget, opacity: int = 92) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")

        title = QLabel("MiniFloat", self)
        title.setObjectName("title")

        opacity_slider = QSlider(Qt.Orientation.Horizontal, self)
        opacity_slider.setObjectName("opacitySlider")
        opacity_slider.setAccessibleName("Opacidad")
        opacity_slider.setToolTip("Opacidad global")
        opacity_slider.setRange(25, 100)
        opacity_slider.setValue(opacity)
        opacity_slider.setFixedWidth(72)

        opacity_value = QLabel(f"{opacity_slider.value()}%", self)
        opacity_value.setObjectName("opacityValue")
        opacity_value.setFixedWidth(34)
        opacity_slider.valueChanged.connect(
            lambda value: opacity_value.setText(f"{value}%")
        )
        opacity_slider.valueChanged.connect(self.opacity_changed.emit)

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

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 4, 4)
        layout.setSpacing(2)
        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(opacity_slider)
        layout.addWidget(opacity_value)
        layout.addWidget(minimize)
        layout.addWidget(close)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and not handle.startSystemMove():
                logger.warning("Windows could not start moving the window.")
            event.accept()
            return
        super().mousePressEvent(event)
