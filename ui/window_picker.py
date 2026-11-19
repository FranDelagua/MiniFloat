from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from app.windows import WindowCandidate
from ui.styles import WINDOW_STYLES


class WindowPickerDialog(QDialog):
    def __init__(
        self, windows: list[WindowCandidate], parent=None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("windowPicker")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(WINDOW_STYLES)
        self.setWindowTitle("Añadir ventana")
        self.setMinimumSize(420, 300)

        self._window_list = QListWidget(self)
        self._window_list.setAccessibleName("Ventanas abiertas")
        for window in windows:
            item = QListWidgetItem(window.display_name, self._window_list)
            item.setData(Qt.ItemDataRole.UserRole, window)
            item.setToolTip(
                f"{window.title}\n{window.process_name} (PID {window.process_id})"
                f"\nHWND 0x{window.handle:x}"
            )
        if windows:
            self._window_list.setCurrentRow(0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self._add_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._add_button.setText("Añadir")
        self._add_button.setEnabled(bool(windows))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._window_list.itemDoubleClicked.connect(self._accept_selection)

        layout = QVBoxLayout(self)
        if windows:
            layout.addWidget(QLabel("Selecciona una ventana visible:", self))
        else:
            layout.addWidget(QLabel("No hay ventanas visibles compatibles.", self))
        layout.addWidget(self._window_list, 1)
        layout.addWidget(buttons)

    def selected_window(self) -> WindowCandidate | None:
        item = self._window_list.currentItem()
        if item is None:
            return None
        window = item.data(Qt.ItemDataRole.UserRole)
        return window if isinstance(window, WindowCandidate) else None

    def _accept_selection(self, _item: QListWidgetItem) -> None:
        if self.selected_window() is not None:
            self.accept()
