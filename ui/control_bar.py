from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QToolButton, QWidget


class ControlBar(QWidget):
    opacity_changed = Signal(int)
    pin_changed = Signal(bool)

    def __init__(self, parent: QWidget, opacity: int) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("controlBar")
        self.setFixedHeight(36)

        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setObjectName("opacitySlider")
        slider.setAccessibleName("Opacidad")
        slider.setToolTip("Opacidad global")
        slider.setRange(25, 100)
        slider.setValue(opacity)
        slider.setFixedWidth(100)

        value_label = QLabel(f"{slider.value()}%", self)
        value_label.setObjectName("opacityValue")
        value_label.setFixedWidth(34)
        slider.valueChanged.connect(lambda value: value_label.setText(f"{value}%"))
        slider.valueChanged.connect(self.opacity_changed.emit)

        self.pin_button = QToolButton(self)
        self.pin_button.setObjectName("pinButton")
        self.pin_button.setAccessibleName("Pin")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(True)
        self.pin_button.setToolTip("Activar o desactivar la interacción con el fondo")
        self.pin_button.toggled.connect(self._pin_toggled)
        self._pin_toggled(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 6, 2)
        layout.setSpacing(6)
        layout.addWidget(QLabel("Opacidad", self))
        layout.addWidget(slider)
        layout.addWidget(value_label)
        layout.addStretch()
        layout.addWidget(self.pin_button)

    def _pin_toggled(self, checked: bool) -> None:
        self.pin_button.setText("PIN ON" if checked else "PIN OFF")
        self.pin_changed.emit(checked)
