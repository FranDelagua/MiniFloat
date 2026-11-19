from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QSlider, QToolButton, QWidget

from ui.styles import WINDOW_STYLES


class ControlBar(QWidget):
    opacity_changed = Signal(int)
    pin_changed = Signal(bool)
    window_requested = Signal()
    external_window_selected = Signal(str)
    external_visibility_toggled = Signal()
    external_release_requested = Signal()

    def __init__(self, parent: QWidget, opacity: int) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("controlBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedHeight(36)
        self._always_on_top = False

        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setObjectName("opacitySlider")
        slider.setAccessibleName("Opacidad")
        slider.setToolTip("Opacidad global")
        slider.setRange(25, 100)
        slider.setValue(opacity)
        slider.setFixedWidth(100)
        self._opacity_slider = slider

        value_label = QLabel(f"{slider.value()}%", self)
        value_label.setObjectName("opacityValue")
        value_label.setFixedWidth(34)
        self._opacity_value_label = value_label
        slider.valueChanged.connect(lambda value: value_label.setText(f"{value}%"))
        slider.valueChanged.connect(self.opacity_changed.emit)

        self.add_window_button = QToolButton(self)
        self.add_window_button.setObjectName("addWindowButton")
        self.add_window_button.setText("+")
        self.add_window_button.setAccessibleName("Añadir ventana")
        self.add_window_button.setToolTip("Añadir una ventana de Windows")
        self.add_window_button.clicked.connect(self.window_requested.emit)
        self.add_window_button.setFixedSize(28, 28)

        self.external_window_menu = QMenu(self)
        self.external_window_menu.setStyleSheet(WINDOW_STYLES)
        self.external_window_button = QToolButton(self)
        self.external_window_button.setObjectName("externalWindowButton")
        self.external_window_button.setText("▾")
        self.external_window_button.setAccessibleName("Ventanas externas")
        self.external_window_button.setToolTip("Cambiar o liberar ventana externa")
        self.external_window_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.external_window_button.setMenu(self.external_window_menu)
        self.external_window_button.setFixedSize(28, 28)
        self.external_window_button.hide()

        self.pin_button = QToolButton(self)
        self.pin_button.setObjectName("pinButton")
        self.pin_button.setAccessibleName("Pin")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(True)
        self.pin_button.setToolTip("Activar o desactivar la interacción con el fondo")
        self.pin_button.toggled.connect(self._pin_toggled)
        self.pin_button.setFixedSize(32, 32)
        self.pin_button.setIconSize(QSize(20, 20))
        self._pin_icons = {
            True: self._load_pin_icon("pin_locked.png"),
            False: self._load_pin_icon("pin_unlocked.png"),
        }
        self._pin_slot = QWidget(self)
        self._pin_slot.setObjectName("pinButtonSlot")
        self._pin_slot.setFixedSize(32, 32)
        self._pin_slot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pin_slot.hide()
        self._pin_overlay = PinButtonOverlay(self)
        self._pin_only_mode = False
        self._pin_toggled(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 6, 2)
        layout.setSpacing(6)
        layout.addWidget(QLabel("Opacidad", self))
        layout.addWidget(slider)
        layout.addWidget(value_label)
        layout.addStretch()
        layout.addWidget(self.add_window_button)
        layout.addWidget(self.external_window_button)
        layout.addWidget(self.pin_button)
        layout.addWidget(self._pin_slot)

    def _pin_toggled(self, checked: bool) -> None:
        self.pin_button.setText("")
        self.pin_button.setIcon(self._pin_icons[checked])
        state = "activado" if checked else "desactivado"
        self.pin_button.setAccessibleName(f"Pin {state}")
        self.pin_button.setToolTip(f"PIN {state.upper()}")
        if hasattr(self, "_pin_overlay"):
            self._pin_overlay.set_pinned(checked)
        self.pin_changed.emit(checked)

    def set_pin_only_mode(self, enabled: bool) -> None:
        if self._pin_only_mode == enabled:
            return
        was_visible = self.isVisible()
        self._pin_only_mode = enabled
        self.pin_button.setVisible(not enabled)
        self._pin_slot.setVisible(enabled)
        self._pin_overlay.hide()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        if was_visible:
            self.show()
        layout = self.layout()
        if layout is not None:
            layout.activate()
        if enabled and was_visible:
            self.sync_pin_overlay()

    def set_always_on_top(self, enabled: bool) -> None:
        if self._always_on_top == enabled:
            return
        self._always_on_top = enabled
        self._set_topmost_flag(self, enabled)
        self._pin_overlay.set_always_on_top(enabled)

    def sync_pin_overlay(self) -> None:
        if not self._pin_only_mode or not self.isVisible():
            self._pin_overlay.hide()
            return
        position = self._pin_slot.mapToGlobal(QPoint(0, 0))
        self._pin_overlay.setGeometry(
            position.x(), position.y(), self._pin_slot.width(), self._pin_slot.height()
        )
        self._pin_overlay.setWindowOpacity(self.windowOpacity())
        self._pin_overlay.show()
        self._pin_overlay.raise_()

    @staticmethod
    def _set_topmost_flag(widget: QWidget, enabled: bool) -> None:
        was_visible = widget.isVisible()
        widget.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if was_visible:
            widget.show()

    def set_surface_opacity(self, opacity: float) -> None:
        self.setWindowOpacity(opacity)
        self._pin_overlay.setWindowOpacity(opacity)

    @staticmethod
    def _load_pin_icon(filename: str) -> QIcon:
        path = Path(__file__).resolve().parents[1] / "assets" / "icons" / filename
        if not path.is_file():
            raise FileNotFoundError(f"No se encontró el icono PIN: {path}")
        icon = QIcon(str(path))
        if icon.isNull():
            raise ValueError(f"No se pudo cargar el icono PIN: {path}")
        return icon

    def set_external_windows(
        self, windows: list[tuple[str, str]], active_id: str | None
    ) -> None:
        self.external_window_menu.clear()
        self.external_window_button.setVisible(bool(windows))
        titles = dict(windows)
        for instance_id, title in windows:
            action = self.external_window_menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(instance_id == active_id)
            action.triggered.connect(
                lambda _checked=False, selected_id=instance_id:
                self.external_window_selected.emit(selected_id)
            )

        if active_id not in titles:
            return

        self.external_window_menu.addSeparator()
        self.external_window_menu.addAction(
            "Minimizar / restaurar",
            self.external_visibility_toggled.emit,
        )
        self.external_window_menu.addAction(
            "Liberar ventana",
            self.external_release_requested.emit,
        )
        self.external_window_button.setToolTip(
            f"Ventana activa: {titles[active_id]}"
        )

    def set_opacity_value(self, value: int) -> None:
        signals_blocked = self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(value)
        self._opacity_slider.blockSignals(signals_blocked)
        self._opacity_value_label.setText(f"{value}%")


class PinButtonOverlay(QToolButton):
    def __init__(self, control_bar: ControlBar) -> None:
        super().__init__(control_bar)
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        )
        self.setObjectName("pinButton")
        self.setStyleSheet(WINDOW_STYLES)
        self._control_bar = control_bar
        self.setAccessibleName("Pin")
        self.setCheckable(True)
        self.setFixedSize(32, 32)
        self.setIconSize(QSize(20, 20))
        self.clicked.connect(control_bar.pin_button.click)
        control_bar.pin_button.toggled.connect(self.set_pinned)
        self.setIcon(control_bar._pin_icons[True])

    def set_pinned(self, checked: bool) -> None:
        self.setChecked(checked)
        self.setIcon(self._control_bar._pin_icons[checked])

    def set_always_on_top(self, enabled: bool) -> None:
        ControlBar._set_topmost_flag(self, enabled)
